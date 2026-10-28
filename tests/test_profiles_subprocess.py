"""Real offline process restarts preserve independent profile databases/sessions."""
import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from telegram_manager.configuration import bind_account, load_configuration
from telegram_manager.models import Group
from telegram_manager.storage import Store


class ProfileProcessTests(unittest.TestCase):
    def test_restart_restores_active_profile_and_switch_keeps_original_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bind_account(root, load_configuration(root), 11)
            store = Store(root/'manager.sqlite3')
            store.save_draft(11, 'Original ශ්‍රී draft')
            store.reserve(11, -1, 'already reserved')
            store.close()
            session = b'opaque test session; never opened by Telethon'
            (root/'account.session').write_bytes(session)
            sequence = 0

            def start():
                env = dict(os.environ, TGM_DATA_DIR=str(root), TGM_NO_AUTO_CONNECT='1',
                           PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
                env.pop('TELEGRAM_API_ID', None)
                env.pop('TELEGRAM_API_HASH', None)
                return subprocess.Popen([sys.executable, '-u', '-m', 'telegram_manager.ipc'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env)

            def request(process, method, params=None):
                nonlocal sequence
                sequence += 1
                process.stdin.write((json.dumps({'id':str(sequence),'method':method,'params':params or {}},
                                                ensure_ascii=False)+'\n').encode())
                process.stdin.flush()
                self.assertTrue(select.select([process.stdout], [], [], 10)[0], 'IPC response timeout')
                response = json.loads(process.stdout.readline())
                self.assertTrue(response['ok'], response.get('error'))
                return response['result']

            def stop(process):
                try:
                    if process.poll() is None:
                        request(process, 'shutdown')
                    process.wait(timeout=10)
                    self.assertEqual(process.returncode, 0)
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait(timeout=5)
                    for stream in (process.stdin, process.stdout, process.stderr):
                        stream.close()

            process = start()
            try:
                result = request(process, 'accounts.add', {'label':'Second தமிழ்', 'confirm':True})
                identity = result['created_profile_id']
                self.assertFalse(result['status']['connected'])
            finally:
                stop(process)
            second = root/'profiles'/identity
            bind_account(second, load_configuration(second), 22)
            store = Store(second/'manager.sqlite3')
            store.save_draft(22, 'Second 👩🏽‍💻 draft')
            store.save_group(22, Group(-2,'தமிழ் group','group'))
            store.close()
            # Bind verified fixture metadata without any authentication/network call.
            from telegram_manager.accounts import AccountRegistry
            registry = AccountRegistry(root, load_configuration(root))
            registry.verify(identity, 22, 'Synthetic second account')
            process = start()
            try:
                status = request(process,'status')
                self.assertEqual(status['profile_id'], identity)
                self.assertEqual(status['bound_account_id'],22)
                self.assertFalse(status['connected'])
                self.assertEqual(request(process,'draft.get')['message'],'Second 👩🏽‍💻 draft')
                self.assertEqual(request(process,'groups')['total'],1)
                request(process,'accounts.switch',{'profile_id':'legacy','confirm':True})
                self.assertEqual(request(process,'draft.get')['message'],'Original ශ්‍රී draft')
                self.assertEqual(request(process,'groups')['total'],0)
                self.assertEqual(len(request(process,'history')['deliveries']),1)
            finally:
                stop(process)
            self.assertEqual((root/'account.session').read_bytes(),session)
