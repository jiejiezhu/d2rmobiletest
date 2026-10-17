"""Require macOS 26 and an installed Xcode with iOS 26.4+ SDK."""
import glob
import os
import platform
import subprocess

if platform.system() != 'Darwin' or int(platform.mac_ver()[0].split('.')[0]) < 26:
    raise SystemExit('Source builds require macOS 26 or later')
candidates=[]
for app in glob.glob('/Applications/Xcode*.app'):
    dev=app+'/Contents/Developer'
    try:
        sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-version'],
                                    env=dict(os.environ,DEVELOPER_DIR=dev),text=True).strip()
        version=tuple(map(int,sdk.split('.')))
        if version >= (26,4): candidates.append((version,dev))
    except (subprocess.CalledProcessError,ValueError):pass
if not candidates: raise SystemExit('Runner has no iOS 26.4+ SDK')
version,dev=max(candidates)
with open(os.environ['GITHUB_ENV'],'a') as f:f.write('DEVELOPER_DIR='+dev+'\n')
print('Selected macOS',platform.mac_ver()[0],'SDK',version,dev)
