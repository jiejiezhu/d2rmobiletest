#!/usr/bin/env python3
"""Automatically publish matching IPA and resources to a GitHub Release."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import ci
import export_resources
import release_notes

PART_BYTES = 1_900_000_000  # Strictly below GitHub's 2 GiB per-asset limit.
OUT = ci.ROOT / 'outputs'
STAGE = ci.ROOT / '.release-assets'
RESOURCE_PART_NAMES = tuple(f'D2R-Mobile-Resources.zip.{i:03d}' for i in range(1, 4))


def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)], text=True).strip()


def api(path):
    return json.loads(gh('api', path))


def validate_report(report):
    for key in ('game_version', 'switch_version', 'upstream_commit'):
        if report.get(key) != ci.CONFIG[key]:
            raise ValueError('Release input is incompatible: ' + key)
    revision = report.get('input_revision')
    if revision is not None and revision != os.environ['INPUT_REVISION']:
        raise ValueError('Release input cache revision differs')


def split_resources(source, destination, expected_sha, part_bytes=None):
    part_bytes = PART_BYTES if part_bytes is None else part_bytes
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    whole = hashlib.sha256()
    with source.open('rb') as stream:
        index = 1
        while True:
            first = stream.read(min(8 * 1024**2, part_bytes))
            if not first:
                break
            path = destination / f'D2R-Mobile-Resources.zip.{index:03d}'
            digest = hashlib.sha256()
            written = 0
            with path.open('wb') as part:
                data = first
                while data:
                    part.write(data)
                    digest.update(data)
                    whole.update(data)
                    written += len(data)
                    if written == part_bytes:
                        break
                    data = stream.read(min(8 * 1024**2, part_bytes - written))
            files.append((path, digest.hexdigest()))
            print('Prepared resource volume:', path.name, written, flush=True)
            index += 1
    if whole.hexdigest() != expected_sha:
        raise ValueError('Resource ZIP SHA256 mismatch before publishing')
    (destination / 'Resources-Parts-SHA256SUMS.txt').write_text(
        ''.join(f'{digest}  {path.name}\n' for path, digest in files))
    return [path for path, _ in files]


def release_info(repo, tag):
    # Only an explicit 404 means absent; never turn a permission/network error
    # into a request to create another release.
    result = subprocess.run(['gh', 'api', f'repos/{repo}/releases/tags/{tag}'],
                            text=True, capture_output=True)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if 'HTTP 404' in result.stderr:
        # Draft creation may not create the Git tag until publication, so the
        # tag endpoint can return 404 for an existing draft. Authenticated list
        # results include drafts and let the two workflows share that draft.
        pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100'))
        for page in pages:
            for release in page:
                if release['tag_name'] == tag:
                    return release
        return None
    raise RuntimeError('Could not inspect release: ' + result.stderr.strip())


def release_title():
    return f"D2R Mobile {ci.upstream_version()} · Game {ci.CONFIG['game_version']}"


def publish_complete(repo, tag, notes, title=None, latest=True):
    args = ['release', 'edit', tag, '--repo', repo, '--notes-file', notes, '--draft=false', '--latest=' + str(latest).lower()]
    if title is not None:
        args += ['--title', title]
    gh(*args)
    release = release_info(repo, tag)
    if release is None or release['draft']:
        raise RuntimeError('Release did not become published')
    return release


def wait_for_created_release(repo, tag):
    # A successful create can precede visibility in the tag/list endpoints.
    # Retry reads only: never create another draft after a successful create.
    for attempt in range(6):
        release = release_info(repo, tag)
        if release is not None:
            return release
        if attempt < 5:
            time.sleep(2)
    raise RuntimeError('Created release could not be found after retrying')


def write_install_guide(destination, reference=None):
    path = destination / 'RESOURCE-INSTALL.txt'
    standard, compatibility = ci.ipa_names()
    source = ('配套 Data 下载：' + reference['source_release']['url'] + '\n\n') if reference else ''
    path.write_text(
        source + '下载配套 Data 的全部 D2R-Mobile-Resources.zip.00* 分卷及两个 Resources 校验文件。\n\n'
        'Mac / Linux：在分卷所在目录执行：\n'
        'shasum -a 256 -c Resources-Parts-SHA256SUMS.txt\n'
        f"cat {' '.join(RESOURCE_PART_NAMES)} > D2R-Mobile-Resources.zip\n"
        'shasum -a 256 -c Resources-SHA256SUMS.txt\n\n'
        'Windows：在分卷所在目录用命令提示符执行：\n'
        f"copy /b {'+'.join(RESOURCE_PART_NAMES)} D2R-Mobile-Resources.zip\n\n"
        '解压后将 D2R Mobile Resources 文件夹通过 Finder → iPhone → 文件 → D2R Mobile 拷入应用。\n'
        '打开应用点击重试，等待首次着色器编译完成。配套 Data 不变时无需重新导入。\n'
        'IPA 可使用 Sideloadly、iloader、AltStore Classic 或 SideStore 签名安装，工具链接见 README。\n'
        f'{standard} 用于 iOS 26+；{compatibility} 用于 iOS 18–25。\n'
        'A14–A16设备还需下载本 IPA Release 正文链接的 Legacy-Device-Pack.zip，解压后将 Legacy Device Pack 文件夹与 D2R Mobile Resources 并排导入。\n'
        '首次着色器编译参考：iPhone 17 Pro Max 约 6 分钟。当前版本包尚未进行真机运行验证。\n')
    return path


def list_releases(repo):
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100'))
    return [release for page in pages for release in page]


def asset_digest(asset):
    digest = asset.get('digest', '')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('Release asset has no verifiable SHA256')
    if asset.get('state') != 'uploaded' or type(asset.get('size')) is not int or asset['size'] <= 0:
        raise ValueError('Release asset upload incomplete')
    return digest.removeprefix('sha256:')


def read_metadata(repo, asset):
    """Download small metadata only, including from private repositories."""
    digest = asset_digest(asset)
    if asset['size'] > 16 * 1024 * 1024:
        raise ValueError('Resource metadata unexpectedly large')
    content = subprocess.check_output(['gh', 'api', '-H', 'Accept: application/octet-stream',
                                       f"repos/{repo}/releases/assets/{asset['id']}"])
    if len(content) != asset['size'] or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('Resource metadata SHA256 mismatch')
    return content


def parse_checksums(content):
    result = {}
    for line in content.decode('utf-8').splitlines():
        fields = line.split()
        if len(fields) != 2 or not re.fullmatch(r'[a-f0-9]{64}', fields[0]) or fields[1] in result:
            raise ValueError('Invalid resource checksums')
        result[fields[1]] = fields[0]
    return result


def resource_reference(repo, release, manifest):
    """Return a verified reference, or reject an incompatible/incomplete bundle."""
    if release.get('draft') or release.get('prerelease'):
        return None
    names = (*RESOURCE_PART_NAMES, 'resources-report.json',
             'Resources-SHA256SUMS.txt', 'Resources-Parts-SHA256SUMS.txt')
    assets = {a['name']: a for a in release['assets']}
    if not set(names) <= assets.keys():
        return None
    try:
        identity = export_resources.resource_identity(manifest)
        for name in names:
            asset_digest(assets[name])
        report = json.loads(read_metadata(repo, assets['resources-report.json']))
        if export_resources.resource_identity(report) != identity:
            return None
        parts = parse_checksums(read_metadata(repo, assets['Resources-Parts-SHA256SUMS.txt']))
        whole = parse_checksums(read_metadata(repo, assets['Resources-SHA256SUMS.txt']))
        if set(parts) != set(RESOURCE_PART_NAMES) or whole != {'D2R-Mobile-Resources.zip': report['zip_sha256']}:
            return None
        if type(report['zip_bytes']) is not int or report['zip_bytes'] <= 0:
            return None
        remaining = report['zip_bytes']
        downloads = []
        for name in names:
            asset = assets[name]
            digest = asset_digest(asset)
            if name in RESOURCE_PART_NAMES:
                expected = min(PART_BYTES, remaining)
                if expected <= 0 or asset['size'] != expected or digest != parts[name]:
                    return None
                remaining -= expected
            url = asset['browser_download_url']
            if not url.startswith(f'https://github.com/{repo}/releases/download/'):
                return None
            downloads.append({'name': name, 'bytes': asset['size'], 'sha256': digest, 'url': url})
        if remaining or not release['html_url'].startswith(f'https://github.com/{repo}/releases/tag/'):
            return None
        return {'schema_version': 1, 'resource_id': identity,
                'game_version': manifest['game_version'], 'switch_version': manifest['switch_version'],
                'archive_count': manifest['archive_count'], 'resource_bytes': manifest['resource_bytes'],
                'zip_bytes': report['zip_bytes'], 'zip_sha256': report['zip_sha256'],
                'source_release': {'id': release['id'], 'tag': release['tag_name'], 'url': release['html_url']},
                'assets': downloads}
    except (ValueError, KeyError, TypeError, AttributeError):
        # Malformed or incomplete content is not reusable. Network/auth errors
        # deliberately propagate rather than silently triggering a large rebuild.
        return None


def find_resources(repo, manifest):
    # No cross-repository defaults: a fork uses resources in its own repository.
    releases = list_releases(repo)
    releases.sort(key=lambda r: not r['tag_name'].startswith('data-'))
    for release in releases:
        reference = resource_reference(repo, release, manifest)
        if reference:
            return reference
    return None


def ensure_release(repo, tag, title, notes):
    release = release_info(repo, tag)
    if release is None:
        gh('release', 'create', tag, '--repo', repo, '--target', os.environ['GITHUB_SHA'],
           '--title', title, '--notes-file', notes, '--draft')
        release = wait_for_created_release(repo, tag)
    if release.get('immutable'):
        raise ValueError('Cannot update an immutable release')
    return release


def upload_verified(repo, tag, assets):
    release = release_info(repo, tag)
    current = {item['name']: item for item in release['assets']}
    expected = {}
    for path in assets:
        digest = ci.sha256(path)
        expected[path.name] = (path.stat().st_size, digest)
        item = current.get(path.name)
        if item and item.get('state') == 'uploaded' and item.get('digest') == 'sha256:' + digest and item['size'] == path.stat().st_size:
            print('Release asset unchanged:', path.name, flush=True)
            continue
        print('Uploading release asset:', path.name, flush=True)
        gh('release', 'upload', tag, path, '--repo', repo, '--clobber')
    release = release_info(repo, tag)
    remote = {item['name']: item for item in release['assets']}
    for name, (size, digest) in expected.items():
        item = remote.get(name)
        if not item or item.get('size') != size or asset_digest(item) != digest:
            raise ValueError('Uploaded asset missing or SHA256 mismatch: ' + name)
    return release


def publish_resources(repo, manifest):
    """Create a Data release only when no complete matching resource set exists."""
    report = export_resources.export_resources(game=ci.GAME, output=OUT / 'D2R-Mobile-Resources.zip', manifest=manifest)
    parts = split_resources(OUT / 'D2R-Mobile-Resources.zip', STAGE, report['zip_sha256'])
    if tuple(p.name for p in parts) != RESOURCE_PART_NAMES:
        raise ValueError('Unexpected number of resource volumes')
    tag = f"data-{manifest['game_version']}-{manifest['resource_id']}"
    title = f"D2R Mobile Data · {manifest['game_version']} · {manifest['resource_id'][:12]}"
    notes = STAGE / 'DATA-RELEASE.md'
    notes.write_text(release_notes.data(repo, manifest))
    existing = ensure_release(repo, tag, title, notes)
    if not existing['draft']:
        # A published but incomplete bundle is hidden while it is repaired.
        gh('release', 'edit', tag, '--repo', repo, '--draft=true')
    upload_verified(repo, tag, [*parts, STAGE / 'Resources-Parts-SHA256SUMS.txt',
                               OUT / 'resources-report.json', OUT / 'Resources-SHA256SUMS.txt',
                               write_install_guide(STAGE)])
    release = publish_complete(repo, tag, notes, title, latest=False)
    reference = resource_reference(repo, release, manifest)
    if not reference:
        raise ValueError('Published Data release failed verification')
    return reference


def prepare_resources(repo):
    OUT.mkdir(exist_ok=True)
    STAGE.mkdir(exist_ok=True)
    manifest_path = OUT / 'resource-manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else export_resources.scan_resources(ci.GAME)
    export_resources.resource_identity(manifest)
    (OUT / 'resource-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    reference = find_resources(repo, manifest)
    reused = reference is not None
    if not reused:
        reference = publish_resources(repo, manifest)
    (OUT / 'resources.json').write_text(json.dumps(reference, indent=2) + '\n')
    write_install_guide(OUT, reference)
    message = ('Reused existing Data; skipped ZIP, splitting and upload' if reused else 'Published new Data')
    print(message + ': ' + reference['source_release']['url'], flush=True)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(f"\n{message}: [Download Data]({reference['source_release']['url']})\n\n")
            f.write(f"Resource ID: `{reference['resource_id']}`\n")
    return reference


def write_ipa_notes(repo, reference, legacy=None):
    path = STAGE / 'RELEASE.md'
    path.write_text(release_notes.ipa(repo, ci.CONFIG, reference, legacy))
    return path



def validate_packages(report):
    standard, compatibility = ci.ipa_names()
    expected = {standard: ('26.0', ci.CONFIG['shell_sha256']),
                compatibility: ('18.0', ci.CONFIG['ios18_shell_sha256'])}
    packages = report.get('packages', [])
    if len(packages) != 2 or {r['ipa_name'] for r in packages} != set(expected):
        raise ValueError('Both verified IPA variants are required')
    paths, sums = [], []
    for item in packages:
        validate_report(item)
        name = item['ipa_name']
        if (item['minimum_os'], item['shell_sha256']) != expected[name]:
            raise ValueError('IPA shell or minimum system mismatch: ' + name)
        path = OUT / name
        if path.stat().st_size != item['ipa_bytes'] or ci.sha256(path) != item['ipa_sha256']:
            raise ValueError('IPA SHA256 mismatch before publishing: ' + name)
        paths.append(path)
        sums.append(f"{item['ipa_sha256']}  {name}")
    if (OUT / 'SHA256SUMS.txt').read_text().splitlines() != sums:
        raise ValueError('IPA checksum file differs from build report')
    return paths


def verify_legacy_reference(repo, report):
    import legacy_pack
    reference = json.loads((OUT / 'legacy-resources.json').read_text())
    source = api(f"repos/{repo}/releases/{reference['source_release']['id']}")
    actual = legacy_pack.reference(repo, source, reference['recipe_id'])
    if actual != reference or reference['pack'] != report.get('legacy_pack'):
        raise ValueError('Referenced Legacy Device Pack is no longer compatible')
    return reference


def main(mode):
    repo = os.environ['GITHUB_REPOSITORY']
    revision = os.environ['INPUT_REVISION']
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', revision):
        raise ValueError('Invalid input revision')
    if mode == 'prepare-resources':
        return prepare_resources(repo)
    if mode != 'ipa':
        raise ValueError('Expected ipa or prepare-resources')
    report = json.loads((OUT / 'build-report.json').read_text())
    validate_report(report)
    paths = validate_packages(report)
    legacy = verify_legacy_reference(repo, report)
    manifest = json.loads((OUT / 'resource-manifest.json').read_text())
    for key in ('game_version', 'switch_version'):
        if manifest[key] != ci.CONFIG[key]:
            raise ValueError('IPA resource version differs: ' + key)
    reference = json.loads((OUT / 'resources.json').read_text())
    source = api(f"repos/{repo}/releases/{reference['source_release']['id']}")
    if resource_reference(repo, source, manifest) != reference:
        raise ValueError('Referenced Data is no longer complete or compatible')
    STAGE.mkdir(exist_ok=True)
    tag = ci.upstream_version()
    title = release_title()
    notes = write_ipa_notes(repo, reference, legacy)
    ensure_release(repo, tag, title, notes)
    upload_verified(repo, tag, [*paths, OUT / 'build-report.json', OUT / 'SHA256SUMS.txt',
                               OUT / 'legacy-resources.json',
                               OUT / 'resource-manifest.json', OUT / 'resources.json',
                               write_install_guide(OUT, reference)])
    release = publish_complete(repo, tag, notes, title)
    print('Published IPA with matching Data:', release['html_url'], flush=True)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(f"\n[Download IPA]({release['html_url']}) · [Download Data]({reference['source_release']['url']})\n")
    return release


if __name__ == '__main__':
    main(sys.argv[1])
