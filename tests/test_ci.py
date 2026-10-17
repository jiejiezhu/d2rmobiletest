import importlib.util
import json
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('ci', Path(__file__).parents[1] / 'scripts/ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class InputVerificationTests(unittest.TestCase):
    def test_macho_minimum_rejects_wrong_platform_and_malformed_commands(self):
        def binary(platform=2, count=1, size=24, command_size=24):
            return struct.pack('<8I6I', 0xfeedfacf, 0x0100000c, 0, 2, count, size, 0, 0,
                               0x32, command_size, platform, 18 << 16, 18 << 16, 0)
        self.assertEqual(ci.macho_minimum_os(binary()), (18, 0, 0))
        for data in (binary(platform=7), binary(size=32), binary(count=2),
                     binary(command_size=0), binary(command_size=16), binary()[:40],
                     bytes(56)):
            with self.subTest(data=data.hex()), self.assertRaises(ValueError):
                ci.macho_minimum_os(data)

    def test_ipa_names_follow_the_pinned_upstream_release(self):
        for version in ('v1.0.9', 'v1.0.10'):
            config = dict(ci.CONFIG, shell_url=f'https://github.com/owner/repo/releases/download/{version}/shell.ipa')
            self.assertEqual(ci.upstream_version(config), version)
            self.assertEqual(ci.ipa_names(config), (f'D2RMobile-{version}.ipa', f'D2RMobile-{version}-ios18.ipa'))
        with self.assertRaises(ValueError):
            ci.upstream_version(dict(ci.CONFIG, shell_url='https://github.com/owner/repo/releases/download/v1.0.11-rc1/shell.ipa'))

    def test_official_public_shell_is_copied_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / 'original.ipa', root / 'public.ipa'
            entries = {'Payload/Game.app/Game': b'unchanged executable',
                       'Payload/Game.app/dm/shell_info.txt': b'PRODUCT=test\n',
                       'Payload/Game.app/dm/shell_manifest.txt': b'Frameworks/Guest.framework/\ndm/main.cuts.tsv\n'}
            with zipfile.ZipFile(source, 'w') as archive:
                for name, content in entries.items():
                    archive.writestr(name, content)
            config = dict(ci.CONFIG, shell_sha256=ci.sha256(source))
            with patch.object(ci, 'SHELL', source), patch.object(ci, 'PUBLIC_SHELL', target), patch.object(ci, 'CONFIG', config):
                ci.prepare_public_shell()
                self.assertEqual(target.read_bytes(), source.read_bytes())
                with zipfile.ZipFile(target) as archive:
                    self.assertEqual(set(archive.namelist()), set(entries))
                    for name, content in entries.items():
                        self.assertEqual(archive.read(name), content)
                    self.assertIn(b'dm/main.cuts.tsv', archive.read('Payload/Game.app/dm/shell_manifest.txt'))
                source.write_bytes(b'tampered shell')
                with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                    ci.prepare_public_shell()

    def test_rejects_shell_requiring_unpublished_prefetch(self):
        with self.assertRaisesRegex(ValueError, 'requires startup prefetch'):
            ci.public_manifest(b'dm/main.cuts.tsv\ndm/bootlist.tsv\n')

    def test_rejects_wrong_program_even_if_cache_directory_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp)
            (game / 'ExeFS').mkdir()
            (game / 'ExeFS/main').write_bytes(b'wrong-version')
            with self.assertRaisesRegex(ValueError, 'original 3.3.94012'):
                ci.validate_game(game)

    def test_rejects_truncated_resource(self):
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp)
            (game / 'ExeFS').mkdir()
            (game / 'RomFS/data').mkdir(parents=True)
            config = dict(ci.CONFIG, nso_sha256={})
            (game / 'RomFS/data/test.data').write_bytes(b'123')
            with patch.object(ci, 'CONFIG', config), patch.object(ci, 'resource_sizes', return_value={'test.data': 4}):
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    ci.validate_game(game)

    def test_missing_inputs_cannot_be_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(ci, 'GAME', Path(temp) / 'absent'), patch.dict(ci.os.environ, {'GAME_INPUT_MANIFEST': ''}):
                with self.assertRaisesRegex(ValueError, 'secret missing'):
                    ci.prepare_game()

    def test_extraction_requires_keys_but_never_downloads_game(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {'GAME_INPUT_MANIFEST': json.dumps({'kind': 'packages', 'files': [{'name': 'game.nsp'}]}), 'PROD_KEYS': ''}
            with patch.object(ci, 'GAME', Path(temp) / 'absent'), patch.dict(ci.os.environ, env), patch.object(ci, 'verify_download_cache', return_value=True), patch.object(ci, 'download') as download:
                with self.assertRaisesRegex(ValueError, 'PROD_KEYS'):
                    ci.prepare_game()
                download.assert_not_called()

    def test_download_cache_survives_key_failure_and_skips_second_download(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {'kind': 'packages', 'files': [{'name': 'base.nsp', 'url': 'https://example.invalid/base.nsp'}]}
            env = {'GAME_INPUT_MANIFEST': json.dumps(manifest), 'PROD_KEYS': ''}
            with patch.object(ci, 'RAW', root / 'raw'), patch.object(ci, 'GAME', root / 'absent'), patch.dict(ci.os.environ, env):
                with patch.object(ci, 'download', side_effect=lambda url, path, digest: path.write_bytes(b'complete-package')) as download:
                    ci.download_game_inputs()
                    download.assert_called_once()
                self.assertTrue(ci.verify_download_cache(manifest))
                with self.assertRaisesRegex(ValueError, 'PROD_KEYS'):
                    ci.prepare_game()
                with patch.object(ci, 'download') as download:
                    ci.download_game_inputs()
                    download.assert_not_called()
                (ci.RAW / 'base.nsp').write_bytes(b'broken')
                with self.assertRaisesRegex(ValueError, 'corrupt'):
                    ci.verify_download_cache(manifest)

    def test_failed_download_is_not_eligible_for_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {'kind': 'packages', 'files': [{'name': 'base.nsp', 'url': 'https://example.invalid/base.nsp'}]}
            with patch.object(ci, 'RAW', root / 'raw'), patch.object(ci, 'GAME', root / 'absent'), patch.dict(ci.os.environ, {'GAME_INPUT_MANIFEST': json.dumps(manifest)}), patch.object(ci, 'download', side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    ci.download_game_inputs()
                self.assertFalse(ci.verify_download_cache(manifest))

    def test_rejects_non_https_download(self):
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            ci.download('http://example.invalid/game.zip', '/unused')

    def test_nca_keys_exclude_malformed_unused_derivation_sources(self):
        text = ('header_key = ' + 'ab' * 32 + '\nmaster_key_10 = ' + 'cd' * 16
                + '\nmaster_kek_source_10 = ' + 'ef' * 17
                + '\neticket_rsa_keypair = ' + '01' * 528)
        normalized = ci.normalize_prod_keys(text)
        self.assertIn('master_key_10 = ' + 'cd' * 16, normalized)
        self.assertNotIn('master_kek_source', normalized)
        self.assertNotIn('eticket', normalized)

    def test_invalid_required_nca_key_fails_without_disclosing_value(self):
        value = 'ab' * 17
        with self.assertRaisesRegex(ValueError, 'header_key') as error:
            ci.normalize_prod_keys('header_key = ' + value)
        self.assertNotIn(value, str(error.exception))
        with self.assertRaisesRegex(ValueError, 'header_key'):
            ci.normalize_prod_keys('master_key_10 = ' + '00' * 16)

    def test_torrent_requires_pinned_metadata_and_explicit_selection(self):
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            ci.download_torrent(Path('game.torrent'), {'select': [1, 2]})
        with self.assertRaisesRegex(ValueError, 'positive file indices'):
            ci.download_torrent(Path('game.torrent'), {'sha256': '0' * 64, 'select': [0]})

    def test_failed_torrent_cannot_continue_to_game_validation(self):
        with patch.object(ci.subprocess, 'run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(RuntimeError, 'did not finish'):
                ci.download_torrent(Path('game.torrent'), {'sha256': '0' * 64, 'select': [1, 2]})

    def test_ticket_extracts_common_encrypted_key_and_rights_id(self):
        # Real source packages contain a 0x2C0-byte common ticket, not 0x400.
        data = bytearray(0x2C0)
        # Literal bytes observed in the package; signature type is little endian.
        data[:4] = bytes.fromhex('04000100')
        data[0x180:0x190] = bytes(range(16))
        data[0x2A0:0x2B0] = bytes(range(16, 32))
        self.assertEqual(ci.ticket_title_key(data), (bytes(range(16, 32)).hex(), bytes(range(16)).hex()))
        data[0x281] = 1
        with self.assertRaisesRegex(ValueError, 'Personalized'):
            ci.ticket_title_key(data)
        with self.assertRaisesRegex(ValueError, '[Tt]runcated'):
            ci.ticket_title_key(data[:300])
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            ci.ticket_title_key(b'\x00\x00\x00\x00' + data[4:])

    def test_diagnostics_do_not_include_key_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logs = root / 'downloads'
            logs.mkdir()
            secret = '12ab' * 8
            (logs / 'extract.log').write_text('Titlekey (Encrypted) ' + secret + '\nerror: missing RomFS\n')
            with patch.object(ci, 'ROOT', root), patch.object(ci, 'WORK', logs), patch.object(ci, 'DM', root):
                ci.diagnostics()
            saved = next((root / 'outputs/diagnostics').glob('*.log')).read_text()
            self.assertNotIn(secret, saved)
            self.assertIn('error: missing RomFS', saved)

    def test_extracts_shell_version_from_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            shell = Path(temp) / 'shell.ipa'
            with zipfile.ZipFile(shell, 'w') as z:
                z.writestr('Payload/DmIOS.app/dm/shell_info.txt', 'PRODUCT=test\nCHAIN=abc\n')
            self.assertEqual(ci.shell_info(shell)['CHAIN'], 'abc')


if __name__ == '__main__':
    unittest.main()
