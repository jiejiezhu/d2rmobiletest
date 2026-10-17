import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('export_resources', Path(__file__).parents[1] / 'scripts/export_resources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ResourceExportTests(unittest.TestCase):
    def test_exports_only_required_archives_and_round_trips_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / 'game/RomFS/data'
            data.mkdir(parents=True)
            content = b'game-resource\x00' * 500
            (data / '00-00000001.data').write_bytes(content)
            (data / 'unused.data').write_bytes(b'not requested')
            (data / 'prod.keys').write_bytes(b'not exported')
            with patch.object(module.ci, 'validate_game'), patch.object(module.ci, 'resource_sizes', return_value={'00-00000001.data': len(content)}):
                report = module.export_resources(root / 'game', root / 'out/resources.zip')
            self.assertEqual(report['archive_count'], 1)
            self.assertEqual(report['resource_bytes'], len(content))
            with zipfile.ZipFile(root / 'out/resources.zip') as archive:
                self.assertEqual(len(archive.namelist()), 3)
                self.assertEqual(archive.read('D2R Mobile Resources/data/00-00000001.data'), content)
                self.assertFalse(any('keys' in name or 'unused' in name for name in archive.namelist()))
                self.assertIn(report['files'][0]['sha256'], archive.read('D2R Mobile Resources/SHA256SUMS.txt').decode())

    def test_changed_content_after_scan_is_rejected_without_publishing_zip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / 'game/RomFS/data'
            data.mkdir(parents=True)
            source = data / '00-00000001.data'
            source.write_bytes(b'original')
            with patch.object(module.ci, 'validate_game'), patch.object(module.ci, 'resource_sizes', return_value={source.name: 8}):
                manifest = module.scan_resources(root / 'game')
                source.write_bytes(b'modified')  # Same length; size alone would miss it.
                with self.assertRaisesRegex(ValueError, 'verification failed'):
                    module.export_resources(root / 'game', root / 'out/resources.zip', manifest=manifest)
            self.assertFalse((root / 'out/resources.zip').exists())
            self.assertFalse((root / 'out/resources.zip.part').exists())

    def test_incomplete_archive_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / 'game/RomFS/data'
            data.mkdir(parents=True)
            (data / '00-00000001.data').write_bytes(b'short')
            with patch.object(module.ci, 'validate_game'), patch.object(module.ci, 'resource_sizes', return_value={'00-00000001.data': 100}):
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    module.export_resources(root / 'game', root / 'out/resources.zip')
            self.assertFalse((root / 'out/resources.zip').exists())
            self.assertFalse((root / 'out/resources.zip.part').exists())
