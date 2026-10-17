"""Resolve the source checkout and apply this build repository's optional patches."""
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[2]
up=root/'upstream'
h=hashlib.sha256()
patches=sorted((root/'source-patches').glob('*.patch'))
for patch in patches:
    subprocess.run(['git','-C',str(up),'apply','--check',str(patch)],check=True)
    subprocess.run(['git','-C',str(up),'apply',str(patch)],check=True)
    h.update(patch.name.encode()+b'\0'+patch.read_bytes())
config=json.loads((root/'build-config.json').read_text())
config['upstream_commit']=subprocess.check_output(['git','-C',str(up),'rev-parse','HEAD'],text=True).strip()
if patches:config['source_patch_sha256']=h.hexdigest()
(root/'build-config.json').write_text(json.dumps(config,indent=2)+'\n')
print('Selected source:',config['upstream_commit'],'patch digest:',h.hexdigest())
