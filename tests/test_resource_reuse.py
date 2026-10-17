import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import export_resources as resources
import publish_release as publish


class FakeGitHub:
    """A small Release store; binary downloads are restricted to metadata."""
    repo = 'owner/repo'

    def __init__(self):
        self.releases = {}
        self.content = {}
        self.calls = []
        self.downloaded = []
        self.latest = None

    def create(self, tag, draft=True):
        release = {'id': len(self.releases) + 1, 'tag_name': tag, 'draft': draft,
                   'prerelease': False, 'assets': [],
                   'html_url': f'https://github.com/{self.repo}/releases/tag/{tag}'}
        self.releases[tag] = release
        return release

    def add_asset(self, tag, name, content):
        release = self.releases[tag]
        release['assets'][:] = [a for a in release['assets'] if a['name'] != name]
        aid = len(self.content) + 100
        self.content[aid] = content
        asset = {'id': aid, 'name': name, 'state': 'uploaded', 'size': len(content),
                 'digest': 'sha256:' + hashlib.sha256(content).hexdigest(),
                 'browser_download_url': f'https://github.com/{self.repo}/releases/download/{tag}/{name}'}
        release['assets'].append(asset)
        return asset

    def gh(self, *values):
        args = tuple(map(str, values))
        self.calls.append(args)
        if args[0] == 'api':
            return json.dumps([list(self.releases.values())])
        action, tag = args[1:3]
        if action == 'create':
            self.create(tag)
        elif action == 'upload':
            path = Path(args[3])
            self.add_asset(tag, path.name, path.read_bytes())
        elif action == 'edit':
            if '--draft=false' in args:
                self.releases[tag]['draft'] = False
            if '--draft=true' in args:
                self.releases[tag]['draft'] = True
            if '--latest=true' in args:
                self.latest = tag
        else:
            raise AssertionError(args)
        return ''

    def download(self, args):
        aid = int(args[-1].rsplit('/', 1)[1])
        self.downloaded.append(aid)
        names = [a['name'] for r in self.releases.values() for a in r['assets'] if a['id'] == aid]
        assert names and not names[0].endswith(('.001', '.002', '.003')), 'Large Data download forbidden'
        return self.content[aid]

    def api(self, path):
        rid = int(path.rsplit('/', 1)[1])
        return next(r for r in self.releases.values() if r['id'] == rid)


def manifest():
    return {'game_version': publish.ci.CONFIG['game_version'],
            'switch_version': publish.ci.CONFIG['switch_version'],
            'archive_count': 1, 'resource_bytes': 8,
            'files': [{'name': '00-00000001.data', 'bytes': 8,
                       'sha256': hashlib.sha256(b'resource').hexdigest()}]}


def legacy_bundle(store):
    release = store.create('old-app-version', draft=False)
    report = dict(manifest(), upstream_commit='old-source', input_revision='old-revision',
                  zip_bytes=5, zip_sha256=hashlib.sha256(b'abcde').hexdigest())
    sums = []
    for name, data in zip(publish.RESOURCE_PART_NAMES, (b'ab', b'cd', b'e')):
        store.add_asset(release['tag_name'], name, data)
        sums.append(f'{hashlib.sha256(data).hexdigest()}  {name}\n')
    store.add_asset(release['tag_name'], 'resources-report.json', json.dumps(report).encode())
    store.add_asset(release['tag_name'], 'Resources-SHA256SUMS.txt',
                    f"{report['zip_sha256']}  D2R-Mobile-Resources.zip\n".encode())
    store.add_asset(release['tag_name'], 'Resources-Parts-SHA256SUMS.txt', ''.join(sums).encode())
    return release


class ResourceReuseTests(unittest.TestCase):
    def setUp(self):
        # Test publication must not append fake links or paths to the real runner.
        isolated = patch.dict(os.environ, {'GITHUB_ENV': '', 'GITHUB_STEP_SUMMARY': ''})
        isolated.start()
        self.addCleanup(isolated.stop)

    def test_identity_ignores_build_revision_zip_metadata_and_file_order(self):
        first = manifest()
        first['files'].append(dict(first['files'][0], name='00-00000002.data'))
        first.update(archive_count=2, resource_bytes=16)
        second = dict(first, upstream_commit='new-source', input_revision='new-revision',
                      zip_sha256='f' * 64, zip_bytes=123)
        second['files'] = list(reversed(first['files']))
        self.assertEqual(resources.resource_identity(first), resources.resource_identity(second))
        second['files'] = [dict(item, sha256='a' * 64) for item in first['files']]
        self.assertNotEqual(resources.resource_identity(first), resources.resource_identity(second))

    def test_duplicate_names_and_false_identity_are_rejected(self):
        bad = manifest()
        bad['files'] = bad['files'] * 2
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            resources.resource_identity(bad)
        with self.assertRaisesRegex(ValueError, 'identity'):
            resources.resource_identity(dict(manifest(), resource_id='0' * 64))

    def test_legacy_data_is_reused_across_source_versions_without_downloading_parts(self):
        store = FakeGitHub()
        legacy = legacy_bundle(store)
        with patch.object(publish, 'PART_BYTES', 2), patch.object(publish, 'gh', side_effect=store.gh), patch.object(publish.subprocess, 'check_output', side_effect=store.download):
            ref = publish.find_resources(store.repo, manifest())
        self.assertEqual(ref['source_release']['id'], legacy['id'])
        self.assertEqual(len(store.downloaded), 3)  # Three small metadata files only.
        self.assertEqual(len(ref['assets']), 6)

    def test_missing_part_and_bad_digest_cannot_be_reused(self):
        store = FakeGitHub()
        legacy = legacy_bundle(store)
        with patch.object(publish, 'PART_BYTES', 2), patch.object(publish.subprocess, 'check_output', side_effect=store.download):
            legacy['assets'][0]['digest'] = 'sha256:' + '0' * 64
            self.assertIsNone(publish.resource_reference(store.repo, legacy, manifest()))
            legacy['assets'].pop(0)
            self.assertIsNone(publish.resource_reference(store.repo, legacy, manifest()))

    def test_draft_and_cross_repository_assets_are_not_reused(self):
        store = FakeGitHub()
        legacy = legacy_bundle(store)
        with patch.object(publish, 'PART_BYTES', 2), patch.object(publish.subprocess, 'check_output', side_effect=store.download):
            legacy['draft'] = True
            self.assertIsNone(publish.resource_reference(store.repo, legacy, manifest()))
            legacy['draft'] = False
            self.assertIsNone(publish.resource_reference('other/repo', legacy, manifest()))

    def test_metadata_corruption_is_rejected_and_network_errors_propagate(self):
        store = FakeGitHub()
        legacy = legacy_bundle(store)
        with patch.object(publish, 'PART_BYTES', 2):
            with patch.object(publish.subprocess, 'check_output', return_value=b'broken'):
                self.assertIsNone(publish.resource_reference(store.repo, legacy, manifest()))
            with patch.object(publish.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, ['gh'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    publish.resource_reference(store.repo, legacy, manifest())

    def test_reuse_skips_export_split_and_upload(self):
        store = FakeGitHub()
        legacy_bundle(store)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(publish, 'OUT', root / 'out'), patch.object(publish, 'STAGE', root / 'stage'), patch.object(publish, 'PART_BYTES', 2), patch.object(publish, 'gh', side_effect=store.gh), patch.object(publish.subprocess, 'check_output', side_effect=store.download), patch.object(resources, 'scan_resources', return_value=manifest()), patch.object(resources, 'export_resources') as export, patch.object(publish, 'split_resources') as split:
                ref = publish.prepare_resources(store.repo)
                export.assert_not_called()
                split.assert_not_called()
                self.assertTrue((root / 'out/resources.json').is_file())
                self.assertFalse((root / 'out/D2R-Mobile-Resources.zip').exists())
                self.assertIn(ref['source_release']['url'], (root / 'out/RESOURCE-INSTALL.txt').read_text())
            self.assertFalse(any(c[:2] == ('release', 'upload') for c in store.calls))

    def test_first_build_publishes_data_once_then_ipa_and_second_build_reuses_it(self):
        store = FakeGitHub()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / 'game'
            data = game / 'RomFS/data'
            data.mkdir(parents=True)
            raw = bytes(range(256)) * 50
            (data / '00-00000001.data').write_bytes(raw)
            output, stage = root / 'out', root / 'stage'
            original_split = publish.split_resources

            def small_parts(source, destination, digest):
                publish.PART_BYTES = (source.stat().st_size + 2) // 3
                return original_split(source, destination, digest, part_bytes=publish.PART_BYTES)

            env = {'GITHUB_REPOSITORY': store.repo, 'INPUT_REVISION': 'revision-1', 'GITHUB_SHA': 'abc'}
            with patch.dict(os.environ, env), patch.object(publish, 'OUT', output), patch.object(publish, 'STAGE', stage), patch.object(publish.ci, 'GAME', game), patch.object(resources.ci, 'validate_game'), patch.object(resources.ci, 'resource_sizes', return_value={'00-00000001.data': len(raw)}), patch.object(publish, 'PART_BYTES', 1), patch.object(publish, 'split_resources', side_effect=small_parts), patch.object(publish, 'gh', side_effect=store.gh), patch.object(publish, 'release_info', side_effect=lambda repo, tag: store.releases.get(tag)), patch.object(publish, 'api', side_effect=store.api), patch.object(publish.subprocess, 'check_output', side_effect=store.download):
                ref = publish.main('prepare-resources')
                data_tag = ref['source_release']['tag']
                self.assertFalse(store.releases[data_tag]['draft'])
                self.assertIsNone(store.latest)  # Data must never replace the latest IPA.
                content = b'verified IPA'
                (output / publish.ci.ipa_names()[0]).write_bytes(content)
                digest = hashlib.sha256(content).hexdigest()
                report = {k: publish.ci.CONFIG[k] for k in ('game_version', 'switch_version', 'upstream_commit')}
                report.update(ipa_bytes=len(content), ipa_sha256=digest, input_revision='revision-1')
                packages = []
                for name, minimum, shell_key in ((publish.ci.ipa_names()[0], '26.0', 'shell_sha256'), (publish.ci.ipa_names()[1], '18.0', 'ios18_shell_sha256')):
                    (output / name).write_bytes(content)
                    packages.append(dict(report, ipa_name=name, minimum_os=minimum, shell_sha256=publish.ci.CONFIG[shell_key]))
                report['packages'] = packages
                (output / 'build-report.json').write_text(json.dumps(report))
                (output / 'SHA256SUMS.txt').write_text(''.join(f"{digest}  {r['ipa_name']}\n" for r in packages))
                (output / 'legacy-resources.json').write_text('{}')
                with patch.object(publish, 'verify_legacy_reference', return_value=None):
                    release = publish.main('ipa')
                self.assertEqual(store.latest, release['tag_name'])
                self.assertEqual(release['tag_name'], publish.ci.upstream_version())
                notes = (stage / 'RELEASE.md').read_text()
                for name in publish.ci.ipa_names():
                    self.assertIn(name, notes)
                self.assertFalse(release['draft'])
                self.assertIn('resources.json', {a['name'] for a in release['assets']})
                self.assertTrue(set(publish.ci.ipa_names()) <= {a['name'] for a in release['assets']})
                self.assertFalse(any(a['name'].endswith(('.001', '.002', '.003')) for a in release['assets']))
                uploads_before = len([c for c in store.calls if c[:2] == ('release', 'upload')])
                with patch.object(resources, 'export_resources') as export, patch.object(publish, 'split_resources') as split:
                    second = publish.main('prepare-resources')
                    self.assertEqual(second, ref)
                    export.assert_not_called()
                    split.assert_not_called()
                self.assertEqual(uploads_before, len([c for c in store.calls if c[:2] == ('release', 'upload')]))


if __name__ == '__main__':
    unittest.main()
