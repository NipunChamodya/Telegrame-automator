import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from telegram_manager import bootstrap
from telegram_manager.configuration import (
    Credentials, bind_account, load_configuration, resolve_credentials,
)
from telegram_manager.models import Group
from telegram_manager.security import KeychainError, MacKeychain, application_lock, private_directory
from telegram_manager.storage import DuplicateMessage, Store


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_first_run_and_existing_identity(self):
        config = load_configuration(self.root)
        self.assertIsNone(config['account_id'])
        bind_account(self.root, config, 123)
        original = (self.root / 'config.json').read_bytes()
        bind_account(self.root, config, 123)
        self.assertEqual((self.root / 'config.json').read_bytes(), original)
        self.assertEqual(load_configuration(self.root)['account_id'], 123)
        self.assertEqual((self.root / 'config.json').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            bind_account(self.root, config, 456)
        self.assertEqual((self.root / 'config.json').read_bytes(), original)

    def test_bad_configuration_preserved(self):
        path = self.root / 'config.json'
        for value in ('{broken', '[]', '{"version":2}', '{"version":1,"account_id":true}'):
            path.write_text(value)
            with self.assertRaises(ValueError):
                load_configuration(self.root)
            self.assertEqual(path.read_text(), value)

    def test_credentials_redacted_and_validated(self):
        value = Credentials.parse('123', 'a' * 32)
        self.assertNotIn('a' * 32, repr(value))
        for api_id, api_hash in [('0', 'a' * 32), ('123', 'secret'), ('123456789012', 'a' * 32)]:
            with self.assertRaises(ValueError):
                Credentials.parse(api_id, api_hash)

    @patch.dict(os.environ, {'TELEGRAM_API_ID': '123', 'TELEGRAM_API_HASH': 'b' * 32}, clear=True)
    @patch('telegram_manager.configuration.MacKeychain')
    def test_environment_precedence(self, keychain):
        credentials, source = resolve_credentials(self.root)
        self.assertEqual(credentials.api_id, 123)
        self.assertEqual(source, 'environment')
        keychain.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch('telegram_manager.configuration.MacKeychain')
    def test_keychain_credentials_and_missing_configuration(self, keychain):
        keychain.return_value.read.return_value = None
        self.assertEqual(resolve_credentials(self.root), (None, 'unset'))
        keychain.return_value.read.return_value = json.dumps({'api_id': 5, 'api_hash': 'c' * 32})
        self.assertEqual(resolve_credentials(self.root)[0].api_id, 5)
        self.assertFalse((self.root / 'config.json').exists())

    @patch.dict(os.environ, {'TELEGRAM_API_ID': '123'}, clear=True)
    def test_partial_environment_never_falls_back(self):
        with self.assertRaises(ValueError):
            resolve_credentials(self.root)

    @patch('telegram_manager.configuration.os.fsync', side_effect=KeyboardInterrupt)
    def test_interrupted_config_write_does_not_publish(self, sync):
        with self.assertRaises(KeyboardInterrupt):
            bind_account(self.root, load_configuration(self.root), 1)
        self.assertFalse((self.root / 'config.json').exists())
        self.assertEqual(list(self.root.glob('.config-*')), [])


class SecurityTests(unittest.TestCase):
    def test_private_modes_and_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = private_directory(Path(directory) / 'private')
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            with application_lock(root):
                with self.assertRaises(ValueError):
                    with application_lock(root):
                        pass
            with application_lock(root):
                pass

    def test_symlink_and_permission_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            link = root / 'link'
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                private_directory(link)
            link.unlink()
            with patch.object(Path, 'chmod', side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    private_directory(root)

    @patch('telegram_manager.security.platform.system', return_value='Linux')
    def test_keychain_unsupported(self, system):
        with self.assertRaises(KeychainError):
            MacKeychain('test')


class DatabaseStartupTests(unittest.TestCase):
    def test_database_reopen_preserves_all_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manager.sqlite3'
            store = Store(path)
            store.save_group(1, Group(-1, 'Existing', 'group'))
            delivery, _ = store.reserve(1, -1, 'message')
            store.finish(delivery, 'sent', 'acknowledged')
            store.set_cooldown(1, 9999999999)
            before = store.history(1)
            store.close()
            reopened = Store(path)
            try:
                self.assertEqual(reopened.history(1), before)
                self.assertEqual(reopened.groups(1)[0]['name'], 'Existing')
                self.assertEqual(reopened.cooldown(1), 9999999999)
                with self.assertRaises(DuplicateMessage):
                    reopened.reserve(1, -1, 'message')
            finally:
                reopened.close()

    def test_incompatible_and_corrupt_database_not_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manager.sqlite3'
            path.write_bytes(b'not a sqlite database')
            original = path.read_bytes()
            with self.assertRaises(sqlite3.DatabaseError):
                Store(path)
            self.assertEqual(path.read_bytes(), original)
            path.unlink()
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE deliveries (id INTEGER)')
            db.close()
            with self.assertRaises(sqlite3.DatabaseError):
                Store(path)
            db = sqlite3.connect(path)
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                             [('deliveries',)])
            db.close()


class BootstrapTests(unittest.TestCase):
    @patch('telegram_manager.bootstrap.importlib.metadata.version', side_effect=bootstrap.importlib.metadata.PackageNotFoundError)
    def test_missing_dependency_detected(self, version):
        self.assertEqual(bootstrap.missing_dependencies(), ['Telethon>=1.45,<2'])

    @patch('telegram_manager.bootstrap.importlib.util.find_spec', return_value=object())
    @patch('telegram_manager.bootstrap.importlib.metadata.version')
    def test_version_constraints(self, version, spec):
        for value, accepted in [('1.45.0', True), ('1.44.9', False), ('2.0.0', False), ('1.45.0rc1', False)]:
            version.return_value = value
            self.assertEqual(not bootstrap.missing_dependencies(), accepted)

    @patch('telegram_manager.bootstrap.missing_dependencies', return_value=['Telethon>=1.45,<2'])
    @patch('telegram_manager.bootstrap.venv_ready', return_value=False)
    @patch('telegram_manager.bootstrap.sys.stdin.isatty', return_value=True)
    @patch('builtins.input', return_value='n')
    @patch('telegram_manager.bootstrap.subprocess.run')
    @patch('telegram_manager.bootstrap.venv.EnvBuilder')
    def test_declined_install_changes_nothing(self, builder, run, answer, tty, ready, missing):
        with patch('sys.stdout', new=io.StringIO()):
            self.assertFalse(bootstrap.ensure_dependencies())
        builder.assert_not_called()
        run.assert_not_called()

    @patch('telegram_manager.bootstrap.missing_dependencies', return_value=['Telethon>=1.45,<2'])
    @patch('telegram_manager.bootstrap.venv_ready', return_value=True)
    @patch('telegram_manager.bootstrap.os.execv')
    def test_existing_environment_reexec_without_install(self, execute, ready, missing):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').touch()
            with patch('telegram_manager.bootstrap.PROJECT', root):
                self.assertFalse(bootstrap.ensure_dependencies())
            execute.assert_called_once_with(str(root / '.venv/bin/python'),
                                             [str(root / '.venv/bin/python'), str(root / 'main.py')])

    @patch('telegram_manager.bootstrap.missing_dependencies', return_value=['Telethon>=1.45,<2'])
    @patch('telegram_manager.bootstrap.venv_ready', return_value=False)
    @patch('telegram_manager.bootstrap.sys.stdin.isatty', return_value=True)
    @patch('builtins.input', return_value='y')
    @patch('telegram_manager.bootstrap.subprocess.run')
    def test_install_only_project_into_existing_venv(self, run, answer, tty, ready, missing):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').touch()
            (root / '.venv/pyvenv.cfg').touch()
            run.side_effect = [Mock(returncode=0), Mock(returncode=1)]
            with patch('telegram_manager.bootstrap.PROJECT', root), patch('sys.stdout', new=io.StringIO()):
                self.assertFalse(bootstrap.ensure_dependencies())
            command = run.call_args_list[1].args[0]
            self.assertEqual(command[0], str(root / '.venv/bin/python'))
            self.assertEqual(command[-2:], ['-e', str(root)])
            self.assertNotIn('--user', command)

    @patch('telegram_manager.bootstrap.missing_dependencies', return_value=[])
    def test_ready_does_not_install(self, missing):
        with patch('telegram_manager.bootstrap.subprocess.run') as run:
            self.assertTrue(bootstrap.ensure_dependencies())
            run.assert_not_called()


class NativeKeychainTests(unittest.TestCase):
    @patch('telegram_manager.security.platform.system', return_value='Darwin')
    @patch('telegram_manager.security.ctypes.CDLL')
    def test_missing_item_and_non_overwriting_storage(self, library, system):
        functions = library.return_value
        functions.SecKeychainFindGenericPassword.return_value = -25300
        keychain = MacKeychain('test-service')
        self.assertIsNone(keychain.read())
        functions.SecKeychainAddGenericPassword.return_value = -25299  # duplicate item
        with self.assertRaises(KeychainError):
            keychain.save_new('not-a-real-secret')
        # Native call, no shell command or subprocess argument containing credentials.
        self.assertEqual(functions.SecKeychainAddGenericPassword.call_count, 1)

    @patch('telegram_manager.security.platform.system', return_value='Darwin')
    @patch('telegram_manager.security.ctypes.CDLL')
    def test_declined_access_is_sanitized(self, library, system):
        library.return_value.SecKeychainFindGenericPassword.return_value = -128
        with self.assertRaises(KeychainError) as error:
            MacKeychain('test-service').read()
        self.assertIn('declined', str(error.exception))
