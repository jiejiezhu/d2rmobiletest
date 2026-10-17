#!/usr/bin/env python3
"""Export only the 18 archives used by the matching iOS app."""
import hashlib
import json
import os
import re
from pathlib import Path
import zipfile

import ci


def resource_identity(report):
    """Identify the phone resource contents, independently of a build or ZIP."""
    if not isinstance(report, dict):
        raise ValueError('Resource manifest must be an object')
    files = report.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('Resource manifest files missing')
    normalized = []
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('Resource entry must be an object')
        name, size, digest = item.get('name'), item.get('bytes'), item.get('sha256')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*\.data', name) or name in seen:
            raise ValueError('Invalid or duplicate resource filename')
        if type(size) is not int or size <= 0 or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('Invalid resource size or SHA256')
        seen.add(name)
        normalized.append({'name': name, 'bytes': size, 'sha256': digest})
    if report.get('archive_count', len(files)) != len(files) or report.get('resource_bytes', sum(f['bytes'] for f in normalized)) != sum(f['bytes'] for f in normalized):
        raise ValueError('Resource manifest totals differ')
    if any(not isinstance(report.get(k), str) or not report[k] for k in ('game_version', 'switch_version')):
        raise ValueError('Resource version missing')
    content = {'format': 1, 'game_version': report['game_version'],
               'switch_version': report['switch_version'],
               'files': sorted(normalized, key=lambda f: f['name'])}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if report.get('resource_id', digest) != digest:
        raise ValueError('Resource identity mismatch')
    return digest


def scan_resources(game=ci.GAME):
    """Read each required archive once before deciding whether to compress."""
    game = Path(game)
    ci.validate_game(game)
    files = []
    for name, size in sorted(ci.resource_sizes().items()):
        path = game / 'RomFS/data' / name
        if path.stat().st_size != size:
            raise ValueError('Resource missing or incomplete: ' + name)
        files.append({'name': name, 'bytes': size, 'sha256': ci.sha256(path)})
        print('Hashed resource:', name, size, flush=True)
    report = {'game_version': ci.CONFIG['game_version'],
              'switch_version': ci.CONFIG['switch_version'],
              'archive_count': len(files), 'resource_bytes': sum(f['bytes'] for f in files),
              'files': files}
    report['resource_id'] = resource_identity(report)
    return report


def export_resources(game=ci.GAME, output=None, manifest=None):
    game = Path(game)
    manifest = manifest or scan_resources(game)
    identity = resource_identity(manifest)
    for key in ('game_version', 'switch_version'):
        if manifest[key] != ci.CONFIG[key]:
            raise ValueError('Resource version differs: ' + key)
    expected_sizes = ci.resource_sizes()
    if {f['name']: f['bytes'] for f in manifest['files']} != expected_sizes:
        raise ValueError('Resource manifest does not match required archives')
    output = Path(output or ci.ROOT / 'outputs/D2R-Mobile-Resources.zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix('.zip.part')
    folder = 'D2R Mobile Resources'
    files = manifest['files']
    try:
        with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            for item in files:
                name, size = item['name'], item['bytes']
                source = game / 'RomFS/data' / name
                if source.stat().st_size != size:
                    raise ValueError('Resource missing or incomplete: ' + name)
                archive.write(source, f'{folder}/data/{name}')
                print('Packed:', name, size, flush=True)
            sums = ''.join(f"{f['sha256']}  data/{f['name']}\n" for f in files)
            archive.writestr(f'{folder}/SHA256SUMS.txt', sums)
            archive.writestr(f'{folder}/README.txt',
                'D2R Mobile 游戏资源（游戏版本 3.3.94012 / Switch 更新 1.0.34.0）\n\n'
                '1. 在电脑上解压本 ZIP，得到 D2R Mobile Resources 文件夹。\n'
                '2. 用数据线连接 iPhone，打开 Finder → iPhone → 文件。\n'
                '3. 将整个 D2R Mobile Resources 文件夹拖入 D2R Mobile 应用。\n'
                '   也可放入手机 文件 → 我的 iPhone → D2R Mobile。\n'
                '4. 打开应用，点击重试。首次启动等待着色器编译完成。\n\n'
                'data 文件夹包含完整的 18 个 .data 文件，合计约 5.56GB。\n'
                '无需向手机复制游戏包、ExeFS 或任何密钥。\n'
                '正常覆盖安装时请保持应用标识一致；卸载应用会删除资源和存档。\n')
        # Read every compressed member back and compare with the source digest.
        with zipfile.ZipFile(partial) as archive:
            expected = {f"{folder}/data/{f['name']}" for f in files}
            expected.update({f'{folder}/SHA256SUMS.txt', f'{folder}/README.txt'})
            if set(archive.namelist()) != expected:
                raise ValueError('Unexpected resource ZIP contents')
            for item in files:
                name = f"{folder}/data/{item['name']}"
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                        digest.update(chunk)
                if archive.getinfo(name).file_size != item['bytes'] or digest.hexdigest() != item['sha256']:
                    raise ValueError('Resource ZIP verification failed: ' + name)
                print('Verified ZIP entry:', item['name'], flush=True)
            for name in (f'{folder}/SHA256SUMS.txt', f'{folder}/README.txt'):
                archive.read(name)  # Also check metadata CRCs.
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    report = {'resource_id': identity, 'game_version': ci.CONFIG['game_version'],
              'input_revision': os.environ.get('INPUT_REVISION'),
              'switch_version': ci.CONFIG['switch_version'],
              'upstream_commit': ci.CONFIG['upstream_commit'],
              'archive_count': len(files), 'resource_bytes': sum(f['bytes'] for f in files),
              'zip_bytes': output.stat().st_size, 'zip_sha256': ci.sha256(output), 'files': files}
    output.with_name('resources-report.json').write_text(json.dumps(report, indent=2) + '\n')
    output.with_name('Resources-SHA256SUMS.txt').write_text(f"{report['zip_sha256']}  {output.name}\n")
    print('Resource export verified:', report['archive_count'], 'archives;', report['zip_bytes'], 'ZIP bytes', flush=True)
    return report


if __name__ == '__main__':
    export_resources()
