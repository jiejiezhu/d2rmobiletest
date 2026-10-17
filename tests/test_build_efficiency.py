import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import build_ipas
import cache_keys
import ci


class BuildEfficiencyTests(unittest.TestCase):
    def test_shared_payload_preserves_target_native_files_and_all_generated_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = {'dm/shell_info.txt': b'PRODUCT=r44\nCHAIN=chain\n',
                      'dm/shell_manifest.txt': b'Frameworks/Guest.framework/\nmsl/\n'}
            def shell(name, base, minimum, native):
                entries = dict(common, **{'Info.plist': plistlib.dumps({'MinimumOSVersion': minimum}),
                                          'Game': native})
                with zipfile.ZipFile(root / name, 'w') as z:
                    for n, data in entries.items(): z.writestr(base+n, data)
                return {base+n:data for n,data in entries.items()}
            standard = shell('standard.ipa', 'Payload/A.app/', '26.0', b'new APIs')
            compatibility = shell('compatibility.ipa', 'Payload/B.app/', '18.0', b'old APIs')
            payload = {'Frameworks/Guest.framework/Guest': b'game program',
                       'msl/shader_b.metallib': b'shader',
                       'romfs_overlay/data/a.data': b'UI',
                       'romfs_overlay_astc/pack.json': b'paired pack'}
            with zipfile.ZipFile(root/'built.ipa', 'w') as z:
                for n, data in standard.items(): z.writestr(n, data)
                for n, data in payload.items(): z.writestr('Payload/A.app/'+n, data)
            build_ipas.reuse_payload(root/'built.ipa',root/'standard.ipa',root/'compatibility.ipa',root/'result.ipa')
            with zipfile.ZipFile(root/'result.ipa') as z:
                expected = dict(compatibility, **{'Payload/B.app/'+n:v for n,v in payload.items()})
                self.assertEqual(set(z.namelist()), set(expected))
                for n, data in expected.items(): self.assertEqual(z.read(n), data)
                self.assertIsNone(z.testzip())
            # Sharing must stop when the destination shell asks for different content.
            with zipfile.ZipFile(root/'other.ipa','w') as z:
                for n, data in compatibility.items():
                    z.writestr(n, b'new requirement\n' if n.endswith('shell_manifest.txt') else data)
            with self.assertRaisesRegex(ValueError, 'different shell manifests'):
                build_ipas.reuse_payload(root/'built.ipa',root/'standard.ipa',root/'other.ipa',root/'bad.ipa')
            self.assertFalse((root/'bad.ipa').exists())

    def test_shader_cache_depends_on_shader_inputs_not_release_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = {'dm/gfx/tools/dmsh_chain.py': "FILES = ['tools/dmsh_chain.py', 'tools/kernel.py']\n",
                       'dm/gfx/tools/kernel.py':'shader generation',
                       'dm/gfx/tools/nometal_run.py':'no metal', 'dm/tools/dmx.py':'reader',
                       'dm/third_party/ryujinx/src/Shader.cs':'translator'}
            for name,data in entries.items():
                p=root/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(data)
            with patch.dict(ci.os.environ, {'INPUT_REVISION':'game-v1'}):
                first=cache_keys.keys(root,ci.CONFIG,'10.0.100')
                changed=dict(ci.CONFIG,upstream_commit='different',shell_url='different',shell_sha256='different')
                self.assertEqual(first,cache_keys.keys(root,changed,'10.0.100'))
                self.assertNotEqual(first['shaders'],cache_keys.keys(root,changed,'10.0.101')['shaders'])
                (root/'dm/gfx/tools/kernel.py').write_text('changed generation')
                newer=cache_keys.keys(root,ci.CONFIG,'10.0.100')
                self.assertNotEqual(first['shaders'],newer['shaders'])
                self.assertEqual(first['tools'],newer['tools'])
                (root/'dm/third_party/ryujinx/src/Shader.cs').write_text('changed translator')
                self.assertNotEqual(newer['shaders'],cache_keys.keys(root,ci.CONFIG,'10.0.100')['shaders'])
                self.assertNotEqual(cache_keys.keys(root,ci.CONFIG,'10.0.100','toolchain-a')['shaders'],
                                    cache_keys.keys(root,ci.CONFIG,'10.0.100','toolchain-b')['shaders'])
                changed=dict(ci.CONFIG,spirv_commit='new compiler')
                self.assertNotEqual(first['tools'],cache_keys.keys(root,changed,'10.0.100')['tools'])
