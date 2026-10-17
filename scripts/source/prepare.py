"""Generate matching game payload and native compile inputs without a prebuilt IPA."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ci


def run(*args, **kwargs):
    return subprocess.check_output([str(a) for a in args], text=True, **kwargs)


def main():
    up=ci.ROOT/'upstream'; dm=up/'dm'; ios=dm/'ios'; out=ci.ROOT/'outputs'
    out.mkdir(exist_ok=True)
    romfs=ci.GAME/'RomFS'
    run(sys.executable,ios/'tools/gen_assets.py',romfs)
    chain=run(sys.executable,dm/'gfx/tools/nometal_run.py',dm/'gfx/tools/dmsh_chain.py').strip().splitlines()[-1]
    product=(dm/'PRODUCT').read_text().strip()
    manifest=[f'msl/b-{chain}/', 'romfs_overlay/', 'romfs_overlay_variants/',
              'hud_v4_ui/', 'mapgoal/', 'mercslots/', 'Frameworks/Guest.framework/',
              'dm/derived.tsv', 'dm/main.cuts.tsv', 'dm/c1_full.tsv']
    manifest += [f'dm/{m}{suffix}' for m in ('main','sdk') for suffix in ('.fixups.tsv','.gates.tsv')]
    manifest += sorted(p.name for p in (ios/'Sources/TouchArt').iterdir() if p.is_file())
    # This file is only a generation contract: it contains no executable and is never delivered.
    contract=ci.DM/'build/source-contract.zip'; contract.parent.mkdir(parents=True,exist_ok=True)
    base='Payload/DmIOS.app/'
    with zipfile.ZipFile(contract,'w') as z:
        z.writestr(base+'Info.plist',plistlib.dumps({'CFBundleExecutable':'DmIOS','MinimumOSVersion':'26.0'}))
        z.writestr(base+'dm/shell_manifest.txt','\n'.join(manifest)+'\n')
        z.writestr(base+'dm/shell_info.txt',f'PRODUCT={product}\nCHAIN={chain}\nKIND=ios\n')
    payload=out/'source-payload.zip'
    subprocess.run([sys.executable,str(dm/'tools/d2rm_pack.py'),str(contract),str(ci.GAME),str(payload)],check=True)
    # Keep generated build caches untouched: runtime-table stubs only belong in the native copy.
    native=ci.DM/'build/native-source/dm'
    shutil.rmtree(native.parent,ignore_errors=True)
    shutil.copytree(dm,native,ignore=shutil.ignore_patterns('.git','Gen','TouchArt','__pycache__','bin','obj'))
    (native/'host/dm_bright_levels.inc').write_text(run(sys.executable,dm/'tools/gen_bright_levels.py',romfs))
    run(sys.executable,ios/'tools/shell_stubs.py','stubs',native)
    source_commit=run('git','-C',up,'rev-parse','HEAD').strip()
    report={'source_repository':os.environ['SOURCE_REPOSITORY'],'source_commit':source_commit,
            'patch_sha256':ci.CONFIG.get('source_patch_sha256'), 'product':product,'shader_chain':chain,
            'payload_sha256':ci.sha256(payload),'legacy_pack':json.loads((Path(os.environ['D2RM_ASTC_PACK'])/'pack.json').read_text())}
    report['shader_source_sha16']=run(sys.executable,dm/'tools/d2rm_pack.py','--src-digest',ci.DM/'build/cache/metal_shader_cache'/('b-'+chain)).strip()
    (out/'build-config.json').write_bytes((ci.ROOT/'build-config.json').read_bytes())
    (out/'source-input-report.json').write_text(json.dumps(report,indent=2)+'\n')
    with tarfile.open(out/'native-inputs.tar.gz','w:gz') as tf:
        def include(item):
            parts=Path(item.name).parts
            if any(p in ('.git','Gen','TouchArt','__pycache__','bin','obj') for p in parts):return None
            return item
        tf.add(native,arcname='upstream/dm',filter=include)
    print('Prepared source build inputs:',source_commit,product,chain,flush=True)


if __name__=='__main__':main()
