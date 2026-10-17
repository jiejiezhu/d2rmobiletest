#!/usr/bin/env python3
"""Check frozen native PNG hashes before the expensive packer runs."""
import hashlib
import io
import json
from pathlib import Path
import sys

from PIL import Image, features

import ci

sys.path.insert(0, str(ci.ROOT / 'upstream/dm/ios/tools'))
import romfs_art


def main():
    environment = {'pillow': Image.__version__,
                   'zlib': features.version('zlib'),
                   'zlib_ng': features.version('zlib_ng')}
    print('PNG encoder:', json.dumps(environment), flush=True)
    manifest = json.loads((ci.ROOT / 'upstream/dm/ios/Sources/TouchArt/native_art_manifest.json').read_text())
    for asset in manifest['assets']:
        path = asset['official_path'].split('data:data/', 1)[-1]
        raw = romfs_art.read(str(ci.GAME / 'RomFS'), path)
        if hashlib.sha256(raw).hexdigest() != asset['official_sprite_sha256'] or hashlib.md5(raw).hexdigest() != asset['official_sprite_md5']:
            raise ValueError('Original sprite mismatch: ' + asset['asset'])
        image = romfs_art.sprite(str(ci.GAME / 'RomFS'), path)
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        actual = hashlib.sha256(buffer.getvalue()).hexdigest()
        if actual != asset['decoded_png_sha256']:
            target = ci.ROOT / 'outputs/png-compat'
            target.mkdir(parents=True, exist_ok=True)
            (target / 'original.sprite').write_bytes(raw)
            (target / 'decoded.png').write_bytes(buffer.getvalue())
            (target / 'rgba.bin').write_bytes(image.tobytes())
            (target / 'report.json').write_text(json.dumps(dict(environment, asset=asset, actual_png_sha256=actual, mode=image.mode, size=image.size), indent=2))
            raise ValueError('Frozen PNG hash mismatch: ' + asset['asset'])
    print('All', len(manifest['assets']), 'native PNG hashes match the frozen manifest', flush=True)


if __name__ == '__main__':
    main()
