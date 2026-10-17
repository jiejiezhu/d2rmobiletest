import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('publish_release', Path(__file__).parents[1] / 'scripts/publish_release.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseTests(unittest.TestCase):
    def test_new_draft_lookup_retries_until_visible(self):
        draft = {'id': 123, 'draft': True, 'assets': []}
        with patch.object(module, 'release_info', side_effect=[None, None, draft]) as lookup, patch.object(module.time, 'sleep') as sleep:
            self.assertEqual(module.wait_for_created_release('owner/repo', 'tag'), draft)
            self.assertEqual(lookup.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_new_draft_lookup_stops_after_bounded_retries(self):
        with patch.object(module, 'release_info', return_value=None) as lookup, patch.object(module.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'after retrying'):
                module.wait_for_created_release('owner/repo', 'tag')
            self.assertEqual(lookup.call_count, 6)
            self.assertEqual(sleep.call_count, 5)

    def test_new_draft_lookup_does_not_hide_permission_errors(self):
        with patch.object(module, 'release_info', side_effect=RuntimeError('HTTP 403')), patch.object(module.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, '403'):
                module.wait_for_created_release('owner/repo', 'tag')
            sleep.assert_not_called()

    def test_split_parts_reassemble_exactly_and_include_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'resources.zip'
            original = bytes(range(256)) * 9
            source.write_bytes(original)
            parts = module.split_resources(source, root / 'parts', hashlib.sha256(original).hexdigest(), part_bytes=1000)
            self.assertEqual([path.stat().st_size for path in parts], [1000, 1000, 304])
            self.assertEqual(b''.join(path.read_bytes() for path in parts), original)
            checksums = (root / 'parts/Resources-Parts-SHA256SUMS.txt').read_text().splitlines()
            for line, path in zip(checksums, parts):
                self.assertEqual(line, f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}')

    def test_corrupt_source_is_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'resources.zip'
            source.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                module.split_resources(source, root / 'parts', '0' * 64, part_bytes=1000)

    def test_different_game_or_cache_revision_cannot_share_release(self):
        report = {key: module.ci.CONFIG[key] for key in ('game_version', 'switch_version', 'upstream_commit')}
        with patch.dict(os.environ, {'INPUT_REVISION': 'revision-1'}):
            module.validate_report(report)  # Existing verified reports predate revision metadata.
            with self.assertRaisesRegex(ValueError, 'revision differs'):
                module.validate_report(dict(report, input_revision='revision-2'))
            with self.assertRaisesRegex(ValueError, 'game_version'):
                module.validate_report(dict(report, game_version='wrong'))

    def test_network_failure_is_not_treated_as_missing_release(self):
        class Result:
            returncode = 1
            stdout = ''
            stderr = 'HTTP 403 forbidden'
        with patch.object(module.subprocess, 'run', return_value=Result()):
            with self.assertRaisesRegex(RuntimeError, '403'):
                module.release_info('owner/repo', 'tag')

    def test_existing_draft_is_found_when_tag_endpoint_returns_404(self):
        class Result:
            returncode = 1
            stdout = ''
            stderr = 'HTTP 404 not found'
        draft = {'id': 123, 'tag_name': 'tag', 'draft': True, 'assets': []}
        with patch.object(module.subprocess, 'run', return_value=Result()), patch.object(module, 'gh', return_value=module.json.dumps([[draft]])):
            self.assertEqual(module.release_info('owner/repo', 'tag'), draft)

    def test_publication_requires_confirmed_published_state(self):
        with patch.object(module, 'gh'), patch.object(module, 'release_info', return_value={'draft': True}):
            with self.assertRaisesRegex(RuntimeError, 'did not become published'):
                module.publish_complete('owner/repo', 'tag', 'notes.md')

    def test_publication_returns_final_release_url(self):
        published = {'draft': False, 'html_url': 'https://github.com/owner/repo/releases/tag/tag'}
        with patch.object(module, 'gh'), patch.object(module, 'release_info', return_value=published):
            self.assertEqual(module.publish_complete('owner/repo', 'tag', 'notes.md'), published)
