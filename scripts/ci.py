#!/usr/bin/env python3
"""Remote input preparation, version verification and IPA verification."""
import hashlib
import json
import os
import plistlib
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'build-config.json').read_text())
DM = Path(os.environ.get('DM_ROOT', str(ROOT / '.dm-work')))
GAME = DM / 'data/switch/3.3.94012/Update'
TOOLS = ROOT / '.tools'
WORK = ROOT / '.downloads'
RAW = ROOT / '.game-downloads'
SHELL_NAMES = ('D2RMobile-shell-build-input.zip', 'D2RMobile-shell-ios18-build-input.zip')
SHELL = TOOLS / SHELL_NAMES[0]
PUBLIC_SHELL = DM / 'build/pack/D2RMobile-public-shell-build-input.zip'


def upstream_version(config=None):
    config = CONFIG if config is None else config
    path = unquote(urlparse(config['shell_url']).path)
    version = path.split('/releases/download/', 1)[1].split('/', 1)[0]
    if not re.fullmatch(r'v\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('Expected a stable upstream version tag')
    return version


def ipa_names(config=None):
    version = upstream_version(config)
    return (f'D2RMobile-{version}.ipa', f'D2RMobile-{version}-ios18.ipa')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def download(url, dest, expected=None):
    """Keep signed URLs out of logs; reject web landing pages."""
    if not url.startswith('https://'):
        raise ValueError('Input downloads must use HTTPS')
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + '.part')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'd2r-mobile-build/1.0'})
        with urllib.request.urlopen(req, timeout=120) as r:
            if 'text/html' in r.headers.get('Content-Type', '').lower():
                raise ValueError('Download returned an HTML page; supply a direct file URL')
            with partial.open('wb') as f:
                shutil.copyfileobj(r, f, length=8 * 1024 * 1024)
        if expected and sha256(partial) != expected.lower():
            raise ValueError('Download SHA256 mismatch: ' + dest.name)
        partial.replace(dest)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        # urllib exceptions can contain signed URL credentials.
        if isinstance(exc, ValueError):
            raise
        raise RuntimeError(f'Download failed for {dest.name}: {type(exc).__name__}') from None


def shell_info(path):
    with zipfile.ZipFile(path) as z:
        infos = [n for n in z.namelist() if n.endswith('/dm/shell_info.txt')]
        if len(infos) != 1:
            raise ValueError('Shell version manifest missing or ambiguous')
        return dict(line.split('=', 1) for line in z.read(infos[0]).decode().splitlines() if '=' in line)


def ensure_shell():
    if not SHELL.exists() or sha256(SHELL) != CONFIG['shell_sha256']:
        download(CONFIG['shell_url'], SHELL, CONFIG['shell_sha256'])
    other = TOOLS / SHELL_NAMES[1]
    if not other.exists() or sha256(other) != CONFIG['ios18_shell_sha256']:
        download(CONFIG['ios18_shell_url'], other, CONFIG['ios18_shell_sha256'])
    info = shell_info(SHELL)
    if shell_info(other) != info:
        raise ValueError('The two shells have different program or shader requirements')
    product = (ROOT / 'upstream/dm/PRODUCT').read_text().strip()
    if info['PRODUCT'] != product:
        raise ValueError('Pinned source and shell PRODUCT differ')
    print('Shell verified:', info['PRODUCT'], 'shader digest', info['SHADER_SRC'])


def public_manifest(data):
    # The pinned official shell does not require the unpublished prefetch list.
    # Reject a regression instead of silently editing the pinned shell.
    rows = [line.strip() for line in data.decode().splitlines() if line.strip()]
    if 'dm/bootlist.tsv' in rows:
        raise ValueError('Pinned public shell unexpectedly requires startup prefetch')
    return rows


def prepare_public_shell():
    if sha256(SHELL) != CONFIG['shell_sha256']:
        raise ValueError('Original shell SHA256 mismatch')
    PUBLIC_SHELL.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SHELL) as source:
        manifests = [name for name in source.namelist() if name.endswith('/dm/shell_manifest.txt')]
        if len(manifests) != 1:
            raise ValueError('Shell content manifest missing or ambiguous')
        public_manifest(source.read(manifests[0]))
    shutil.copyfile(SHELL, PUBLIC_SHELL)
    print('Official public shell verified and copied without modification')


def resource_sizes():
    src = (ROOT / 'upstream/dm/host/romfs_validate.c').read_text()
    names = re.search(r'static const char \*need\[\] = \{(.*?)\};', src, re.S)
    sizes = re.search(r'static const long long size\[\] = \{(.*?)\};', src, re.S)
    files = re.findall(r'"([^"]+\.data)"', names.group(1))
    lengths = [int(n) for n in re.findall(r'\d+', sizes.group(1))]
    if len(files) != 18 or len(lengths) != 18:
        raise ValueError('Unexpected upstream resource manifest')
    return dict(zip(files, lengths))


def validate_game(game=GAME):
    game = Path(game)
    for name, expected in CONFIG['nso_sha256'].items():
        path = game / 'ExeFS' / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f'ExeFS/{name} is not the original 3.3.94012 program')
    for name, length in resource_sizes().items():
        path = game / 'RomFS/data' / name
        if not path.is_file() or path.stat().st_size != length:
            raise ValueError(f'Resource missing or incomplete: {name}')
    if not (game / 'RomFS/data/build_manifest.psv').is_file():
        raise ValueError('RomFS/data/build_manifest.psv missing')
    print('Game verified: 3 original NSO hashes and 18 archive sizes match 3.3.94012')


def run(args, logfile, env=None):
    logfile = Path(logfile)
    with logfile.open('wb') as f:
        p = subprocess.run([str(a) for a in args], stdout=f, stderr=subprocess.STDOUT, env=env)
    if p.returncode:
        raise RuntimeError(f'{Path(str(args[0])).name} failed; inspect private runner log {logfile.name}')
    return logfile.read_text(errors='replace')


def unpack_archives():
    for path in sorted(WORK.glob('*')):
        if not path.is_file():
            continue
        name = path.name.lower()
        if re.search(r'\.part\d+\.rar$', name) and not re.search(r'\.part0*1\.rar$', name):
            continue
        if re.search(r'\.(zip|rar|7z)(\.001)?$', name):
            target = WORK / (path.name + '.unpacked')
            target.mkdir(exist_ok=True)
            # Reject absolute/traversing paths before letting 7z extract.
            listing = subprocess.check_output(['7z', 'l', '-slt', str(path)], text=True)
            for member in re.findall(r'^Path = (.*)$', listing, re.M)[1:]:
                clean = member.replace('\\', '/')
                if clean.startswith('/') or '..' in clean.split('/') or re.match(r'^[A-Za-z]:', clean):
                    raise ValueError('Unsafe archive member path')
            run(['7z', 'x', '-y', f'-o{target}', path], WORK / 'archive.log')
    # Compressed wrappers are no longer needed; keep unpacked packages only.
    for path in WORK.iterdir():
        if path.is_file() and re.search(r'\.(zip|rar|7z)(\.\d{3})?$', path.name.lower()):
            path.unlink()


def download_torrent(path, item, directory=RAW):
    # Pin the metadata and explicitly select package files; never fetch an
    # unrelated executable/mod just because it shares the same torrent.
    if not item.get('sha256'):
        raise ValueError('Torrent metadata requires a pinned SHA256')
    selected = item.get('select', [])
    if not selected or any(type(n) is not int or n < 1 for n in selected):
        raise ValueError('Torrent input requires positive file indices in select')
    print('Downloading selected torrent files:', ','.join(map(str, selected)), flush=True)
    result = subprocess.run([
        'aria2c', f'--dir={directory}', '--seed-time=0', '--file-allocation=none',
        '--check-integrity=true', '--bt-stop-timeout=180',
        '--bt-remove-unselected-file=true',
        '--max-upload-limit=128K', '--summary-interval=30',
        '--console-log-level=warn', '--enable-color=false',
        '--select-file=' + ','.join(map(str, selected)), str(path),
    ], timeout=5400)
    if result.returncode:
        raise RuntimeError('Selected torrent download did not finish')


def normalize_prod_keys(text):
    # NCA decryption needs no console-specific secrets or derivation-source
    # tables. Ignore those fields rather than guessing corrections to keys.
    fixed = {'header_key': 64, 'aes_kek_generation_source': 32,
             'aes_key_generation_source': 32,
             'key_area_key_application_source': 32, 'titlekek_source': 32}
    pairs = {}
    for line in text.lstrip('\ufeff').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r'[a-z0-9_]+', key):
            raise ValueError('Invalid prod.keys syntax')
        length = fixed.get(key)
        if re.fullmatch(r'(master_key|titlekek|key_area_key_application)_[0-9a-f]{2}', key):
            length = 32
        if length is None:
            continue
        if not re.fullmatch(r'[0-9a-fA-F]{' + str(length) + r'}', value):
            raise ValueError('Invalid prod.keys field length or encoding: ' + key)
        if key in pairs and pairs[key] != value.lower():
            raise ValueError('Conflicting prod.keys field: ' + key)
        pairs[key] = value.lower()
    if 'header_key' not in pairs:
        raise ValueError('Key input is missing a valid header_key')
    return ''.join(f'{key} = {value}\n' for key, value in sorted(pairs.items()))


def load_prod_keys(manifest):
    text = os.environ.get('PROD_KEYS', '').strip()
    if text:
        return normalize_prod_keys(text)
    source = manifest.get('key_archive')
    if not source:
        raise ValueError('PROD_KEYS secret required to decrypt NSP/XCI; alternatively provide prepared ExeFS/RomFS')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', source.get('sha256', '')):
        raise ValueError('Remote key archive requires a pinned SHA256')
    path = WORK / '.keyset.zip'
    download(source['url'], path, source['sha256'])
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith('prod.keys')]
            if len(names) != 1:
                raise ValueError('Key archive must contain one prod.keys file')
            text = z.read(names[0]).decode('utf-8-sig')
        text = normalize_prod_keys(text)
        print('Remote key archive checksum and syntax verified; values suppressed')
        return text
    finally:
        path.unlink(missing_ok=True)


def ticket_title_key(data):
    # https://switchbrew.org/wiki/Ticket ; hactool expects encrypted title keys.
    signature = int.from_bytes(data[:4], 'little')
    offsets = {0x10000: 0x240, 0x10001: 0x140, 0x10002: 0x80,
               0x10003: 0x240, 0x10004: 0x140, 0x10005: 0x80, 0x10006: 0x40}
    offset = offsets.get(signature)
    if offset is None:
        raise ValueError(f'Unsupported game ticket signature type: {signature:#x}; {len(data)} bytes')
    # Only the fields through Rights ID are required. Common NSP tickets can
    # omit the unused trailing area (the observed RSA-2048 tickets are 0x2C0
    # bytes total, with a 0x140-byte signature and 0x180-byte body).
    if len(data) < offset + 0x170:
        raise ValueError(f'Truncated game ticket: {len(data)} bytes')
    if data[offset + 0x141] != 0:
        raise ValueError('Personalized game ticket requires console-specific keys')
    return data[offset + 0x160:offset + 0x170].hex(), data[offset + 0x40:offset + 0x50].hex()


def input_manifest():
    raw = os.environ.get('GAME_INPUT_MANIFEST', '').strip()
    if not raw:
        raise ValueError('GAME_INPUT_MANIFEST secret missing and game cache not found. Supply direct download URLs for prepared ExeFS/RomFS or base+update packages.')
    manifest = json.loads(raw)
    kind = manifest.get('kind')
    if kind not in ('prepared', 'packages'):
        raise ValueError('Input manifest kind must be prepared or packages')
    files = manifest.get('files', [])
    if not files:
        raise ValueError('Input manifest files cannot be empty')
    return manifest


def download_identity(manifest):
    inputs = {'kind': manifest['kind'], 'files': manifest['files']}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def verify_download_cache(manifest):
    marker = RAW / '.complete.json'
    if not marker.is_file():
        return False
    record = json.loads(marker.read_text())
    if record.get('identity') != download_identity(manifest):
        raise ValueError('Download cache belongs to different inputs; change input_revision')
    if not record.get('files'):
        raise ValueError('Download cache contains no files')
    for item in record['files']:
        name = Path(item['name'])
        if name.is_absolute() or '..' in name.parts:
            raise ValueError('Invalid download cache path')
        path = RAW / name
        if not path.is_file() or path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']:
            raise ValueError('Incomplete or corrupt download cache: ' + str(name))
    return True


def download_game_inputs():
    if GAME.is_dir():
        validate_game()
        print('Using validated game cache; no game download required')
        return
    manifest = input_manifest()
    if verify_download_cache(manifest):
        print('Using complete download cache; no remote game download required', flush=True)
        return
    RAW.mkdir(parents=True, exist_ok=True)
    files = manifest['files']
    for item in files:
        name = item['name']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name.startswith('.'):
            raise ValueError('Unsafe input filename')
        digest = item.get('sha256')
        if digest and not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
            raise ValueError('Invalid input SHA256')
        print('Downloading remote input:', name, flush=True)
        download(item['url'], RAW / name, digest)
        if name.lower().endswith('.torrent'):
            download_torrent(RAW / name, item, RAW)
    payloads = sorted(p for p in RAW.rglob('*') if p.is_file() and p.name != '.complete.json')
    record = {'identity': download_identity(manifest), 'files': [
        {'name': str(p.relative_to(RAW)), 'bytes': p.stat().st_size, 'sha256': sha256(p)}
        for p in payloads]}
    (RAW / '.complete.json').write_text(json.dumps(record))
    print('Download complete and ready to cache BEFORE decryption or extraction', flush=True)


def prepare_game():
    if GAME.is_dir():
        validate_game()
        print('Using validated game cache; no extraction required')
        return
    manifest = input_manifest()
    if not verify_download_cache(manifest):
        raise ValueError('Complete download cache missing; run downloads before extraction')
    kind = manifest['kind']
    key_text = load_prod_keys(manifest) if kind == 'packages' else None
    WORK.mkdir(parents=True, exist_ok=True)
    # The Actions cache has already been saved. Move, do not copy, the local
    # packages so extraction can reclaim disk without touching that cache.
    for path in RAW.iterdir():
        if path.name != '.complete.json':
            shutil.move(str(path), str(WORK / path.name))
    shutil.rmtree(RAW)
    unpack_archives()
    GAME.parent.mkdir(parents=True, exist_ok=True)
    if kind == 'prepared':
        candidates = [p.parent for p in WORK.rglob('ExeFS') if p.is_dir() and (p.parent / 'RomFS').is_dir()]
        if len(candidates) != 1:
            raise ValueError('Prepared archive must contain exactly one ExeFS/RomFS pair')
        validate_game(candidates[0])
        shutil.move(str(candidates[0]), str(GAME))
    else:
        extract_packages(key_text)
        validate_game()
    (GAME / '.ci-verified.json').write_text(json.dumps({'game': CONFIG['game_version'], 'nso_sha256': CONFIG['nso_sha256']}))
    shutil.rmtree(WORK)
    print('Game input verified; original downloads remain in Actions cache')


def extract_packages(key_text):
    keys = WORK / 'prod.keys'
    fd = os.open(keys, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(key_text)
    ht = TOOLS / 'bin/hactool'
    prefix = [ht, '-k', keys, '--disablekeywarns', '--suppresskeys']
    ncas = WORK / 'ncas'
    ncas.mkdir()
    title_keys = WORK / 'key-config/switch/title.keys'
    title_keys.parent.mkdir(parents=True)
    key_env = dict(os.environ, XDG_CONFIG_HOME=str(WORK / 'key-config'))
    try:
        packages = sorted(p for p in WORK.rglob('*') if p.suffix.lower() in ('.nsp', '.xci'))
        if not packages:
            raise ValueError('No NSP/XCI packages in downloads')
        for i, path in enumerate(packages):
            if path.suffix.lower() == '.xci':
                args = ['-t', 'xci', f'--securedir={ncas}', path]
            else:
                args = ['-t', 'pfs0', f'--outdir={ncas}', path]
            run(prefix + args, WORK / f'unpack-{i}.log')
            path.unlink()  # Reclaim space before materializing full RomFS.
        tickets = {}
        for path in ncas.glob('*.tik'):
            rights, encrypted = ticket_title_key(path.read_bytes())
            if rights in tickets and tickets[rights] != encrypted:
                raise ValueError('Conflicting tickets for one Rights ID')
            tickets[rights] = encrypted
        fd = os.open(title_keys, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(''.join(f'{rights} = {value}\n' for rights, value in tickets.items()))
        print('Loaded common package tickets; title-key values suppressed')
        base, update = [], []
        for i, path in enumerate(sorted(ncas.glob('*.nca'))):
            if path.name.endswith('.cnmt.nca'):
                continue
            info = run(prefix + ['-t', 'nca', path], WORK / f'nca-{i}.log', env=key_env)
            if re.search(r'Content Type:\s*Program', info) and re.search(r'Title ID:\s*0100726014352000', info):
                (update if 'BKTR' in info else base).append(path)
        if len(base) != 1 or len(update) != 1:
            raise ValueError('Need exactly one base Program NCA and one update Program NCA')
        temporary = GAME.with_name('Update.partial')
        temporary.mkdir()
        run(prefix + ['-t', 'nca', f'--basenca={base[0]}', f'--exefsdir={temporary / "ExeFS"}', f'--romfsdir={temporary / "RomFS"}', update[0]], WORK / 'extract.log', env=key_env)
        validate_game(temporary)
        temporary.rename(GAME)
    finally:
        keys.unlink(missing_ok=True)
        title_keys.unlink(missing_ok=True)


def macho_minimum_os(data):
    """Read the iOS minimum from a thin ARM64 executable's load commands."""
    if len(data) < 32 or struct.unpack_from('<II', data) != (0xfeedfacf, 0x0100000c):
        raise ValueError('Native executable is not Mach-O arm64')
    count, size = struct.unpack_from('<II', data, 16)
    end = 32 + size
    if end > len(data) or count > size // 8:
        raise ValueError('Truncated Mach-O load commands')
    offset, versions = 32, []
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError('Truncated Mach-O load command')
        command, length = struct.unpack_from('<II', data, offset)
        if length < 8 or length % 8 or offset + length > end:
            raise ValueError('Invalid Mach-O load command size')
        if command == 0x32:  # LC_BUILD_VERSION
            if length < 24:
                raise ValueError('Truncated Mach-O build version')
            platform, minimum = struct.unpack_from('<II', data, offset + 8)
            if platform != 2:
                raise ValueError('Native executable does not target iOS')
            versions.append((minimum >> 16, (minimum >> 8) & 255, minimum & 255))
        offset += length
    if offset != end or len(versions) != 1:
        raise ValueError('Missing or ambiguous Mach-O build version')
    return versions[0]


def verify_ipa(output=None, shell_path=SHELL, minimum_os=None, legacy_pack=None):
    output = Path(output or ROOT / 'outputs' / ipa_names()[0])
    info = shell_info(shell_path)
    with zipfile.ZipFile(shell_path) as shell, zipfile.ZipFile(output) as z:
        corrupt = z.testzip()
        if corrupt:
            raise ValueError('Corrupt IPA member: ' + corrupt)
        bases = [n.removesuffix('dm/shell_manifest.txt') for n in shell.namelist() if n.endswith('/dm/shell_manifest.txt')]
        if len(bases) != 1:
            raise ValueError('Shell app path ambiguous')
        base = bases[0]
        members = set(z.namelist())
        plist = plistlib.loads(z.read(base + 'Info.plist'))
        actual_os = plist['MinimumOSVersion']
        if minimum_os is not None and actual_os != minimum_os:
            raise ValueError('IPA minimum system mismatch: ' + actual_os)
        shell_plist = plistlib.loads(shell.read(base + 'Info.plist'))
        if (actual_os != shell_plist['MinimumOSVersion'] or
                plist['CFBundleExecutable'] != shell_plist['CFBundleExecutable']):
            raise ValueError('IPA executable metadata differs from official shell')
        executable = base + shell_plist['CFBundleExecutable']
        native = z.read(executable)
        if native != shell.read(executable):
            raise ValueError('IPA native executable differs from official shell')
        native_os = macho_minimum_os(native)
        plist_os = tuple(map(int, actual_os.split('.')))
        if native_os != plist_os + (0,) * (3 - len(plist_os)):
            raise ValueError('Native executable minimum system differs from Info.plist')
        if native_os[0] == 18 and b'MTL4CommandQueue' in native:
            raise ValueError('iOS 18 compatibility executable references Metal 4')
        if legacy_pack is not None:
            expected_pack = (Path(legacy_pack) / 'pack.json').read_bytes()
            if z.read(base + 'romfs_overlay_astc/pack.json') != expected_pack:
                raise ValueError('IPA Legacy Device Pack does not match')
            for folder in ('romfs_overlay_astc/', 'romfs_overlay_astc_variants/'):
                if not any(n.startswith(base + folder) and n.endswith('.data') for n in members):
                    raise ValueError('Legacy overlay missing: ' + folder)
        if base + 'dm/bootlist.tsv' in members or base + 'dm/bootlist.sha256' in members:
            raise ValueError('Unexpected stale startup prefetch files in IPA')
        required = public_manifest(shell.read(base + 'dm/shell_manifest.txt'))
        if z.read(base + 'dm/shell_manifest.txt').decode().splitlines() != required:
            raise ValueError('Final IPA content manifest differs from the verified public shell')
        if z.read(base + 'dm/shell_info.txt') != shell.read(base + 'dm/shell_info.txt'):
            raise ValueError('Final IPA shell metadata differs from the verified public shell')
        try:
            pack_lines = z.read(base + 'dm/pack_info.txt').decode().splitlines()
        except (KeyError, UnicodeError):
            raise ValueError('Missing or invalid IPA pack metadata') from None
        products = [line.removeprefix('PRODUCT=') for line in pack_lines if line.startswith('PRODUCT=')]
        if products != [info['PRODUCT']]:
            raise ValueError('IPA pack metadata PRODUCT differs from the verified public shell')
        for item in required:
            item = item.strip()
            if not item:
                continue
            target = base + item
            if not (any(n.startswith(target) for n in members) if item.endswith('/') else target in members):
                raise ValueError('Missing IPA content: ' + item)
        guest = z.read(base + 'Frameworks/Guest.framework/Guest')
        if len(guest) < 8 or struct.unpack_from('<II', guest) != (0xfeedfacf, 0x0100000c):
            raise ValueError('Guest dynamic library is not Mach-O arm64')
        # The packer itself checks the complete shader-source digest against the shell.
        shader_files = [n for n in members if '/msl/b-' + info['CHAIN'] + '/' in n and n.endswith('_b.metallib')]
        if not shader_files:
            raise ValueError('IPA shader library missing')
    digest = sha256(output)
    (output.parent / 'SHA256SUMS.txt').write_text(f'{digest}  {output.name}\n')
    report = {'upstream_commit': CONFIG['upstream_commit'], 'game_version': CONFIG['game_version'], 'switch_version': CONFIG['switch_version'], 'input_revision': os.environ.get('INPUT_REVISION'), 'shell_sha256': sha256(shell_path), 'minimum_os': actual_os, 'ipa_name': output.name, 'product': info['PRODUCT'], 'shader_chain': info['CHAIN'], 'shader_source_sha16': info['SHADER_SRC'], 'ipa_sha256': digest, 'ipa_bytes': output.stat().st_size, 'shader_libraries': len(shader_files), 'signed': False, 'startup_prefetch': False, 'startup_prefetch_reason': 'The pinned official public shell omits the unpublished bootlist; the host supports no prefetch when absent.'}
    report.update(pack_info_verified=True, pack_product=products[0],
                  native_matches_shell=True, native_sha256=hashlib.sha256(native).hexdigest(),
                  native_minimum_os='.'.join(map(str, native_os)), guest_arm64=True,
                  compatibility_no_metal4=(b'MTL4CommandQueue' not in native) if native_os[0] == 18 else None)
    (output.parent / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('IPA verified:', output.name, output.stat().st_size, 'bytes;', len(shader_files), 'shader libraries', flush=True)
    return report


def diagnostics():
    target = ROOT / 'outputs/diagnostics'
    target.mkdir(parents=True, exist_ok=True)
    sources = list(WORK.glob('*.log')) + list((DM / 'build/pack/stage').glob('*.log'))
    sources += list((DM / 'build/cache/dm/out').glob('*/*.patch.log'))
    for i, path in enumerate(sources):
        content = path.read_text(errors='replace')
        # Never publish 128-bit (or longer) key values from tool diagnostics.
        content = re.sub(r'(?i)(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])', '[hex redacted]', content)
        (target / f'{i:02}-{path.name}').write_text(content)
    print('Sanitized diagnostic logs:', len(sources))


if __name__ == '__main__':
    try:
        {'shell': ensure_shell, 'public-shell': prepare_public_shell, 'downloads': download_game_inputs, 'inputs': prepare_game, 'validate-game': validate_game, 'verify-ipa': verify_ipa, 'diagnostics': diagnostics}[sys.argv[1]]()
    except Exception as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
