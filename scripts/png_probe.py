"""Reproduce the frozen PNG from a small private diagnostic RGBA sample."""
import hashlib
import io
import json
from pathlib import Path
import sys

from PIL import Image, features

sample = next(Path(sys.argv[1]).rglob('report.json')).parent
report = json.loads((sample / 'report.json').read_text())
image = Image.frombytes(report['mode'], tuple(report['size']), (sample / 'rgba.bin').read_bytes())
buffer = io.BytesIO()
image.save(buffer, 'PNG')
actual = hashlib.sha256(buffer.getvalue()).hexdigest()
print(json.dumps({'pillow': Image.__version__, 'zlib': features.version('zlib'),
                  'zlib_ng': features.version('zlib_ng'), 'actual': actual,
                  'expected': report['asset']['decoded_png_sha256']}, indent=2), flush=True)
if actual != report['asset']['decoded_png_sha256']:
    raise SystemExit('PNG compatibility mismatch')
