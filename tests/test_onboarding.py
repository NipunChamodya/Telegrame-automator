"""CLI onboarding tests: browser, Keychain and all Telegram calls are mocked."""
import importlib.util
import io
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from telegram_manager.configuration import Credentials
from telegram_manager.guidance import PORTAL, api_tutorial, show_help, welcome, yes


class GuidanceTests(unittest.TestCase):
    def test_tutorial_has_every_step_without_opening_browser(self):
        with patch('sys.stdout', new=io.StringIO()) as output, patch('webbrowser.open') as browser:
            api_tutorial()
        for text in ('STEP 1', 'STEP 2', 'STEP 3', 'STEP 4', 'STEP 5', PORTAL,
                     'API development tools', 'Telegram Group Manager', 'telegramgroupmanager',
                     'Desktop, if offered', 'Personal Telegram group management application',
                     'numeric identifier', 'secret credential'):
            self.assertIn(text, output.getvalue())
        browser.assert_not_called()

    def test_browser_requires_consent_and_only_uses_official_url(self):
        for response, expected in [('n', False), ('yes', True), ('', True)]:
            with self.subTest(response=response), patch('builtins.input', return_value=response), \
                    patch('webbrowser.open', return_value=True) as browser, patch('sys.stdout', new=io.StringIO()):
                api_tutorial(offer_browser=True)
                if expected:
                    browser.assert_called_once_with(PORTAL, new=2)
                else:
                    browser.assert_not_called()

    def test_browser_failure_gives_manual_option(self):
        with patch('builtins.input', return_value='y'), patch('webbrowser.open', side_effect=OSError), \
                patch('sys.stdout', new=io.StringIO()) as output:
            api_tutorial(offer_browser=True)
        self.assertIn('manually', output.getvalue())

    def test_cancel_browser_prompt_never_opens_browser(self):
        with patch('builtins.input', side_effect=KeyboardInterrupt), patch('webbrowser.open') as browser, \
                patch('sys.stdout', new=io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                api_tutorial(offer_browser=True)
        browser.assert_not_called()

    def test_welcome_and_help_are_cli_only(self):
        with patch('builtins.input', return_value='') as answer, patch('webbrowser.open') as browser, \
                patch('sys.stdout', new=io.StringIO()) as output:
            welcome()
            show_help()
        answer.assert_called_once()
        browser.assert_not_called()
        for text in ('Welcome!', 'Press ENTER', 'API ID', 'API Hash', 'RECONNECTING',
                     'GROUP DISCOVERY', 'Unknown', 'FLOOD_WAIT', 'account.session', 'Devices'):
            self.assertIn(text, output.getvalue() + answer.call_args.args[0])

    def test_yes_invalid_input_is_not_implicit_approval(self):
        with patch('builtins.input', side_effect=['maybe', 'n']), patch('sys.stdout', new=io.StringIO()):
            self.assertFalse(yes('Open?', default=True))
        with patch('builtins.input', return_value=''):
            self.assertFalse(yes('Save?'))

    def test_validation_is_specific_and_never_echoes_input(self):
        for api_id, api_hash, expected in [('bad-id', 'a' * 32, 'Invalid API ID'),
                                         ('123', 'sensitive-invalid-hash', 'Invalid API Hash')]:
            with self.subTest(expected=expected), self.assertRaises(ValueError) as caught:
                Credentials.parse(api_id, api_hash)
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn('sensitive-invalid-hash', str(caught.exception))
            self.assertNotIn('bad-id', str(caught.exception))


if importlib.util.find_spec('telethon') is not None:
    from telethon import errors
    from telegram_manager.application import main as application_main, startup
    from telegram_manager.configuration import load_configuration
    from telegram_manager.error_messages import telegram_error_message
    from telegram_manager.models import Group
    from telegram_manager.security import KeychainError
    from telegram_manager.setup_wizard import authenticate, credential_wizard
    from telegram_manager.storage import Store

    class CredentialWizardTests(unittest.TestCase):
        def test_invalid_fields_are_reprompted_and_hash_is_hidden(self):
            with tempfile.TemporaryDirectory() as directory, \
                    patch('telegram_manager.setup_wizard.resolve_credentials', return_value=(None, 'unset')), \
                    patch('telegram_manager.setup_wizard.api_tutorial') as tutorial, \
                    patch('builtins.input', side_effect=['not-numeric', '123']), \
                    patch('telegram_manager.setup_wizard.hidden', side_effect=['private-invalid-hash', 'a' * 32]) as hidden, \
                    patch('telegram_manager.setup_wizard.yes', return_value=False), \
                    patch('sys.stdout', new=io.StringIO()) as output:
                credentials, source = credential_wizard(Path(directory))
            self.assertEqual(credentials.api_id, 123)
            self.assertEqual(source, 'memory only')
            self.assertEqual(hidden.call_count, 2)
            tutorial.assert_called_once_with(offer_browser=True)
            self.assertIn('Invalid API ID', output.getvalue())
            self.assertIn('Invalid API Hash', output.getvalue())
            self.assertNotIn('private-invalid-hash', output.getvalue())
            self.assertNotIn('a' * 32, output.getvalue())

        def test_existing_credentials_do_not_repeat_tutorial_or_overwrite(self):
            for source in ('environment', 'macOS Keychain'):
                with self.subTest(source=source), \
                        patch('telegram_manager.setup_wizard.resolve_credentials', return_value=(Credentials(123, 'a' * 32), source)), \
                        patch('telegram_manager.setup_wizard.api_tutorial') as tutorial, \
                        patch('telegram_manager.setup_wizard.MacKeychain') as keychain, \
                        patch('builtins.input') as answer:
                    self.assertEqual(credential_wizard(Path('/tmp'))[1], source)
                    tutorial.assert_not_called()
                    keychain.assert_not_called()
                    answer.assert_not_called()

        def test_cancel_input_does_not_save_credentials(self):
            with patch('telegram_manager.setup_wizard.resolve_credentials', return_value=(None, 'unset')), \
                    patch('telegram_manager.setup_wizard.api_tutorial'), \
                    patch('builtins.input', side_effect=EOFError), \
                    patch('telegram_manager.setup_wizard.MacKeychain') as keychain:
                with self.assertRaises(EOFError):
                    credential_wizard(Path('/tmp'))
            keychain.assert_not_called()

        def test_failed_keychain_save_requires_explicit_memory_fallback(self):
            with patch('telegram_manager.setup_wizard.resolve_credentials', return_value=(None, 'unset')), \
                    patch('telegram_manager.setup_wizard.api_tutorial'), \
                    patch('telegram_manager.setup_wizard.platform.system', return_value='Darwin'), \
                    patch('builtins.input', return_value='123'), \
                    patch('telegram_manager.setup_wizard.hidden', return_value='a' * 32), \
                    patch('telegram_manager.setup_wizard.yes', side_effect=[True, False]), \
                    patch('telegram_manager.setup_wizard.MacKeychain') as keychain, \
                    patch('sys.stdout', new=io.StringIO()):
                keychain.return_value.save_new.side_effect = KeychainError('not overwritten')
                with self.assertRaises(ValueError):
                    credential_wizard(Path('/tmp'))
                keychain.return_value.save_new.assert_called_once()

    class AuthenticationFailureTests(unittest.IsolatedAsyncioTestCase):
        async def test_invalid_and_expired_codes_are_not_retried(self):
            for error_type in (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError):
                with self.subTest(error_type=error_type):
                    client = AsyncMock()
                    client.is_user_authorized.return_value = False
                    client.send_code_request.return_value = NS(phone_code_hash='opaque')
                    client.sign_in.side_effect = error_type(None)
                    with patch('telegram_manager.setup_wizard.hidden', side_effect=['+123456789', 'secret-test-code']), \
                            patch('sys.stdout', new=io.StringIO()) as output:
                        with self.assertRaises(error_type):
                            await authenticate(client)
                    client.send_code_request.assert_awaited_once()
                    client.sign_in.assert_awaited_once()
                    self.assertNotIn('secret-test-code', output.getvalue())

        async def test_wrong_2fa_stops_without_retry(self):
            client = AsyncMock()
            client.is_user_authorized.side_effect = [False, True]
            client.send_code_request.return_value = NS(phone_code_hash='opaque')
            client.sign_in.side_effect = [errors.SessionPasswordNeededError(None), errors.PasswordHashInvalidError(None)]
            with patch('telegram_manager.setup_wizard.hidden', side_effect=['+123456789', 'code', 'private-test-password']), \
                    patch('sys.stdout', new=io.StringIO()) as output:
                with self.assertRaises(errors.PasswordHashInvalidError):
                    await authenticate(client)
            self.assertEqual(client.sign_in.await_count, 2)
            self.assertNotIn('private-test-password', output.getvalue())

        async def test_cancel_welcome_does_not_connect(self):
            with tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, {'TGM_DATA_DIR': directory}), \
                    patch('telegram_manager.application.sys.stdin.isatty', return_value=True), \
                    patch('builtins.input', side_effect=KeyboardInterrupt), \
                    patch('telegram_manager.application.TelegramClient') as client, \
                    patch('sys.stdout', new=io.StringIO()):
                with self.assertRaises(KeyboardInterrupt):
                    await startup()
                self.assertFalse((Path(directory) / 'config.json').exists())
            client.assert_not_called()

    class ErrorMessageTests(unittest.TestCase):
        def test_specific_authentication_errors_are_understandable(self):
            cases = [(errors.ApiIdInvalidError(None), 'API ID/API Hash pair'),
                     (errors.PhoneCodeInvalidError(None), 'verification code was not accepted'),
                     (errors.PhoneCodeExpiredError(None), 'verification code expired'),
                     (errors.PasswordHashInvalidError(None), 'two-step verification password'),
                     (errors.SessionRevokedError(None), 'authorization expired'),
                     (errors.FloodWaitError(None, capture=60), '60 seconds')]
            for exc, expected in cases:
                with self.subTest(error=type(exc).__name__):
                    self.assertIn(expected, telegram_error_message(exc))

        def test_exception_payload_is_never_shown(self):
            exc = errors.RPCError(None, 'sensitive-request-value')
            self.assertNotIn('sensitive-request-value', telegram_error_message(exc))
            with patch('telegram_manager.application.startup', new=AsyncMock(side_effect=exc)), \
                    patch('sys.stderr', new=io.StringIO()) as output:
                with self.assertRaises(SystemExit):
                    application_main()
            self.assertNotIn('sensitive-request-value', output.getvalue())

        def test_network_failure_explains_recovery_without_payload(self):
            with patch('telegram_manager.application.startup', new=AsyncMock(side_effect=ConnectionError('private-payload'))), \
                    patch('sys.stderr', new=io.StringIO()) as output:
                with self.assertRaises(SystemExit):
                    application_main()
            self.assertIn('Check your internet connection', output.getvalue())
            self.assertNotIn('private-payload', output.getvalue())

    class MainEntryPointTests(unittest.TestCase):
        def test_main_first_run_and_restoration_reach_dashboard(self):
            client = AsyncMock()
            client.is_user_authorized.side_effect = [False, True]
            client.send_code_request.return_value = NS(phone_code_hash='opaque')
            client.sign_in.side_effect = [errors.SessionPasswordNeededError(None), None]
            client.get_me.return_value = NS(id=1234, bot=False, deleted=False)
            script = Path(__file__).resolve().parents[1] / 'main.py'
            with tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, {'TGM_DATA_DIR': directory}), \
                    patch('telegram_manager.application.sys.stdin.isatty', return_value=True), \
                    patch('telegram_manager.application.TelegramClient', return_value=client) as factory, \
                    patch('webbrowser.open') as browser, \
                    patch('telegram_manager.setup_wizard.platform.system', return_value='Darwin'):
                with patch('telegram_manager.setup_wizard.resolve_credentials', return_value=(None, 'unset')), \
                        patch('telegram_manager.setup_wizard.hidden', side_effect=['a' * 32, '+123456789', 'code', 'private-2fa']), \
                        patch('builtins.input', side_effect=['', 'n', '123', 'n', 'y', 'n', '11', '0']), \
                        patch('sys.stdout', new=io.StringIO()) as output:
                    runpy.run_path(str(script), run_name='__main__')
                self.assertIn('SETUP COMPLETED', output.getvalue())
                self.assertIn('HELP —', output.getvalue())
                self.assertIn('11. Help', output.getvalue())
                self.assertNotIn('private-2fa', output.getvalue())
                self.assertEqual(load_configuration(Path(directory))['account_id'], 1234)
                browser.assert_not_called()
                self.assertEqual(factory.call_count, 2)
                self.assertEqual([call.kwargs['request_retries'] for call in factory.call_args_list], [3, 0])
                self.assertEqual(factory.call_args.args[0], str(Path(directory) / 'account'))
                client.send_message.assert_not_awaited()
                client.assert_not_called()  # No low-level message request, including from Help.
                store = Store(Path(directory) / 'manager.sqlite3')
                store.save_group(1234, Group(-1, 'Preserved group', 'group'))
                store.reserve(1234, -1, 'prior message')
                store.set_cooldown(1234, 9999999999)
                history = store.history(1234)
                store.close()
                (Path(directory) / 'account.session').write_bytes(b'existing-session-fixture')
                client.reset_mock()
                client.is_user_authorized.return_value = True
                client.is_user_authorized.side_effect = None
                with patch('telegram_manager.setup_wizard.resolve_credentials', return_value=(Credentials(123, 'a' * 32), 'macOS Keychain')), \
                        patch('telegram_manager.setup_wizard.hidden') as hidden, \
                        patch('builtins.input', side_effect=['0']), patch('sys.stdout', new=io.StringIO()) as restored:
                    runpy.run_path(str(script), run_name='__main__')
                self.assertNotIn('Welcome!', restored.getvalue())
                self.assertNotIn('STEP 1', restored.getvalue())
                self.assertNotIn('SETUP COMPLETED', restored.getvalue())
                self.assertIn('Groups discovered: 1', restored.getvalue())
                hidden.assert_not_called()
                client.send_code_request.assert_not_awaited()
                self.assertEqual((Path(directory) / 'account.session').read_bytes(), b'existing-session-fixture')
                store = Store(Path(directory) / 'manager.sqlite3')
                try:
                    self.assertEqual(store.history(1234), history)
                    self.assertEqual(store.cooldown(1234), 9999999999)
                    self.assertEqual(len(store.groups(1234)), 1)
                finally:
                    store.close()
