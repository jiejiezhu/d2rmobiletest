"""Compile the complete native iOS runtime on macOS; add the matching generated payload."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import zipfile
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ci


def run(*args, **kwargs):
    return subprocess.check_output([str(a) for a in args],text=True,**kwargs)


def main():
    minimum=sys.argv[1]
    if minimum not in ('26.0','18.0'):raise ValueError('Unsupported system variant')
    root=ci.ROOT; ios=root/'upstream/dm/ios'; gen=ios/'Gen'
    report=json.loads((root/'outputs/source-input-report.json').read_text())
    payload=root/'outputs/source-payload.zip'
    if ci.sha256(payload)!=report['payload_sha256']:raise ValueError('Payload checksum mismatch')
    shutil.rmtree(gen,ignore_errors=True);gen.mkdir()
    flags=run(sys.executable,ios/'tools/gen_build.py',ios.parent/'host',gen)
    settings=dict(line.split(' = ',1) for line in flags.splitlines() if ' = ' in line)
    # Use upstream's own free-account and iOS 18 transformations, including CPU baseline.
    free=ios/'source-free.yml'
    run(sys.executable,ios/'tools/project_free.py',ios/'project.yml',free)
    spec=free
    if minimum=='18.0':
        spec=ios/'source-m3.yml'
        run(sys.executable,ios/'tools/project_m3.py',free,spec,'free')
    text=spec.read_text().replace('${DM_BUNDLE_ID}','org.d2rmobile.app').replace('${DM_TEAM_ID}','0000000000')
    upstream=yaml.safe_load(text); target=upstream['targets']['DmIOS']
    cflags=settings['OTHER_CFLAGS']+' '+target['settings']['OTHER_CFLAGS'].replace('$(inherited)','')+' -DDM_SHELL'
    settings.update(target['settings'])
    settings.update({'PRODUCT_BUNDLE_IDENTIFIER':'org.d2rmobile.app','PRODUCT_NAME':'DmIOS',
                     'CODE_SIGNING_ALLOWED':'NO','CODE_SIGNING_REQUIRED':'NO',
                     'CLANG_ENABLE_MODULES':'YES','IPHONEOS_DEPLOYMENT_TARGET':minimum,
                     'TARGETED_DEVICE_FAMILY':'1,2','OTHER_CFLAGS':cflags,
                     'OTHER_LDFLAGS':'$(inherited) $(DM_FRAMEWORKS)','DM_BUILD_NUMBER':'1'})
    props=target['info']['properties']
    for key in list(props):
        if key.startswith('BA'):props.pop(key)
    props.update(CFBundleVersion='1',CFBundleShortVersionString='1.0',SWUpdateURL='')
    sources=[{'path':'Sources','excludes':['Info.plist','*.entitlements','TouchArt']},
             {'path':'Gen/src'},{'path':'Gen/main/main.c','compilerFlags':'-Dmain=dm_main'}]
    if (ios/'Assets.xcassets').exists():sources.append({'path':'Assets.xcassets'})
    deps=[{'sdk':name+'.framework'} for name in ('UIKit','Foundation','GameController','AVFoundation','CoreGraphics','CoreText')]
    deps += [d for d in target.get('dependencies',[]) if 'sdk' in d]
    project={'name':'SourceBuild','options':{'deploymentTarget':{'iOS':minimum}},'targets':{'DmIOS':{
        'type':'application','platform':'iOS','sources':sources,'settings':{'base':settings},
        'info':{'path':'SourceBuild-Info.plist','properties':props},'dependencies':deps}}}
    (ios/'source-build.yml').write_text(yaml.safe_dump(project,sort_keys=False))
    run('xcodegen','generate','--spec','source-build.yml',cwd=ios)
    derived=root/'native-build'
    subprocess.run(['xcodebuild','-project','SourceBuild.xcodeproj','-scheme','DmIOS','-configuration','Release',
                    '-sdk','iphoneos','-destination','generic/platform=iOS','-derivedDataPath',str(derived),
                    'CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO','build'],cwd=ios,check=True)
    app=derived/'Build/Products/Release-iphoneos/DmIOS.app'
    plist=plistlib.loads((app/'Info.plist').read_bytes());native=(app/plist['CFBundleExecutable']).read_bytes()
    native_os=ci.macho_minimum_os(native)
    if plist['MinimumOSVersion']!=minimum or native_os!=(int(minimum.split('.')[0]),0,0):
        raise ValueError('Compiled app targets wrong minimum iOS')
    if minimum=='18.0' and b'MTL4CommandQueue' in native:raise ValueError('Compatibility build references Metal 4')
    suffix='-ios18' if minimum=='18.0' else ''
    name=f"D2RMobile-source-{report['source_commit'][:8]}{suffix}.ipa"
    destination=root/'outputs'/name
    base='Payload/DmIOS.app/'
    with zipfile.ZipFile(payload) as src, zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as dst:
        names=set()
        for p in sorted(app.rglob('*')):
            if not p.is_file() or '_CodeSignature' in p.parts or p.name=='embedded.mobileprovision':continue
            n=base+p.relative_to(app).as_posix();dst.write(p,n);names.add(n)
        for item in src.infolist():
            if item.filename==base+'Info.plist':continue
            if not item.filename.startswith(base) or '..' in item.filename.split('/'):
                raise ValueError('Unexpected generated payload path')
            if item.filename in names:raise ValueError('Payload replaces compiled app content: '+item.filename)
            dst.writestr(item,src.read(item));names.add(item.filename)
    with zipfile.ZipFile(destination) as final, zipfile.ZipFile(payload) as original:
        if final.testzip():raise ValueError('Corrupt output IPA')
        for n in original.namelist():
            if n!=base+'Info.plist' and final.read(n)!=original.read(n):raise ValueError('Generated payload changed: '+n)
        guest=final.read(base+'Frameworks/Guest.framework/Guest')
        if guest[:8]!=bytes.fromhex('cffaedfe0c000001'):raise ValueError('Guest is not arm64')
        pack=json.loads(final.read(base+'romfs_overlay_astc/pack.json'))
        if pack!=report['legacy_pack']:raise ValueError('Legacy pack mismatch')
    report.update(ipa_name=name,ipa_sha256=ci.sha256(destination),ipa_bytes=destination.stat().st_size,
                  minimum_os=minimum,native_minimum_os='.'.join(map(str,native_os)),native_sha256=__import__('hashlib').sha256(native).hexdigest(),
                  native_built_from_source=True,payload_verified=True,device_tested=False,signed=False,
                  xcode=run('xcodebuild','-version').strip(),sdk=run('xcrun','--sdk','iphoneos','--show-sdk-version').strip())
    (root/'outputs'/f'source{suffix}-report.json').write_text(json.dumps(report,indent=2)+'\n')
    (root/'outputs'/f'source{suffix}-SHA256SUMS.txt').write_text(f"{report['ipa_sha256']}  {name}\n")
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
