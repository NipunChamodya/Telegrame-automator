"""Real child-process IPC checks using temporary bound data and NO Telegram calls."""
import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from telegram_manager.configuration import bind_account, load_configuration
from telegram_manager.models import Group
from telegram_manager.storage import Store


class IPCProcess:
    def __init__(self, root: Path):
        environment = os.environ.copy()
        environment['TGM_DATA_DIR'] = str(root)
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        # These tests never call connect/auth. Credential resolution must not run.
        environment.pop('TELEGRAM_API_ID', None)
        environment.pop('TELEGRAM_API_HASH', None)
        self.process = subprocess.Popen([sys.executable, '-u', '-m', 'telegram_manager.ipc'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env=environment, bufsize=0)
        self.buffer = bytearray()
        self.counter = 0

    def write(self, request: bytes) -> None:
        self.process.stdin.write(request + b'\n')
        self.process.stdin.flush()

    def receive(self, timeout: float = 5) -> tuple[dict, bytes]:
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            while b'\n' not in self.buffer:
                ready = selector.select(max(0, deadline - time.monotonic()))
                if not ready:
                    raise AssertionError('IPC child did not return a framed response before the test timeout.')
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise AssertionError('IPC child exited before responding.')
                self.buffer.extend(chunk)
            line, _, remaining = self.buffer.partition(b'\n')
            self.buffer = bytearray(remaining)
            return json.loads(line.decode('utf-8')), bytes(line)
        finally:
            selector.close()

    def request(self, method: str, **params) -> tuple[dict, bytes]:
        self.counter += 1
        request_id = f'process-{self.counter}'
        self.write(json.dumps({'id': request_id, 'method': method, 'params': params}, ensure_ascii=False).encode())
        response, line = self.receive()
        if response.get('id') != request_id:
            raise AssertionError('Unexpected response identity.')
        return response, line

    def close(self) -> None:
        process = self.process
        if process.poll() is None:
            try:
                self.request('shutdown')
                process.wait(timeout=5)
            except Exception:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


class DesktopProcessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        bind_account(self.root, load_configuration(self.root), 10)
        self.title = 'ශ්‍රී ලංකා தமிழ் 👩🏽‍💻'
        store = Store(self.root / 'manager.sqlite3')
        store.save_group(10, Group(-1, self.title, 'group'))
        store.reserve(10, -1, 'existing delivery')
        store.set_cooldown(10, 9999999999)
        self.ledger = store.history(10)
        store.close()
        self.session = self.root / 'account.session'
        self.session.write_bytes(b'opaque-session-preservation-fixture')
        self.children: list[IPCProcess] = []

    def tearDown(self):
        for child in reversed(self.children):
            child.close()
        self.directory.cleanup()

    def launch(self) -> IPCProcess:
        child = IPCProcess(self.root)
        self.children.append(child)
        return child

    def test_cached_unicode_drafts_approvals_and_graceful_shutdown_over_real_pipes(self):
        child = self.launch()
        health, _ = child.request('health')
        self.assertTrue(health['ok'])
        self.assertEqual(health['result']['protocol_version'], 1)
        status, _ = child.request('status')
        self.assertFalse(status['result']['connected'])
        self.assertEqual(status['result']['overview']['total'], 1)
        self.assertEqual(status['result']['bound_account_id'], 10)
        groups, raw = child.request('groups', query='ශ්‍රී')
        self.assertEqual(groups['result']['groups'][0]['name'], self.title)
        self.assertIn(self.title.encode(), raw)
        self.assertNotIn(b'\\u0d', raw)
        self.assertNotIn(b'Welcome', raw)
        draft = 'தமிழ் message 👩🏽‍💻'
        self.assertTrue(child.request('draft.save', message=draft)[0]['ok'])
        self.assertEqual(child.request('draft.get')[0]['result']['message'], draft)
        self.assertTrue(child.request('approval.set', destination=-1, approved=True)[0]['ok'])
        self.assertEqual(child.request('approvals')[0]['result']['groups'][0]['id'], -1)
        preview, _ = child.request('preview', destination=-1, message='never sent')
        self.assertFalse(preview['ok'])
        self.assertEqual(preview['error']['code'], 'not_connected')
        self.assertEqual(child.request('history')[0]['result']['deliveries'], self.ledger)
        shutdown, _ = child.request('shutdown')
        self.assertTrue(shutdown['ok'])
        self.assertEqual(child.process.wait(timeout=5), 0)
        self.assertEqual(self.session.read_bytes(), b'opaque-session-preservation-fixture')
        store = Store(self.root / 'manager.sqlite3')
        try:
            self.assertEqual(store.draft(10)['message'], draft)
            self.assertTrue(store.is_approved(10, -1))
            self.assertEqual(store.history(10), self.ledger)
            self.assertEqual(store.cooldown(10), 9999999999)
        finally:
            store.close()

    def test_malformed_and_concurrent_read_requests_keep_stdout_strict_json(self):
        child = self.launch()
        child.write(b'{"id":"broken","method":"health","params":{},"params":{"secret":"private-test"}}')
        invalid, raw = child.receive()
        self.assertFalse(invalid['ok'])
        self.assertEqual(invalid['error']['code'], 'invalid_request')
        self.assertNotIn(b'private-test', raw)
        for request_id, method in [('read-one', 'status'), ('read-two', 'groups'), ('read-three', 'history')]:
            child.write(json.dumps({'id': request_id, 'method': method, 'params': {}}).encode())
        responses = [child.receive()[0] for _ in range(3)]
        self.assertEqual({response['id'] for response in responses}, {'read-one', 'read-two', 'read-three'})
        self.assertTrue(all(response['ok'] for response in responses))
        self.assertFalse(child.request('shell', command='echo forbidden')[0]['ok'])

    def test_duplicate_process_is_rejected_and_lock_released_after_shutdown(self):
        first = self.launch()
        self.assertTrue(first.request('health')[0]['ok'])
        second = self.launch()
        failure, raw = second.receive()
        self.assertFalse(failure['ok'])
        self.assertIsNone(failure['id'])
        self.assertNotIn(b'opaque-session', raw)
        self.assertNotEqual(second.process.wait(timeout=5), 0)
        self.assertTrue(first.request('status')[0]['ok'])
        first.request('shutdown')
        self.assertEqual(first.process.wait(timeout=5), 0)
        third = self.launch()
        self.assertTrue(third.request('health')[0]['ok'])
        self.assertEqual(self.session.read_bytes(), b'opaque-session-preservation-fixture')

    def test_parent_eof_reaps_backend_without_session_or_ledger_reset(self):
        child = self.launch()
        self.assertTrue(child.request('health')[0]['ok'])
        child.process.stdin.close()
        self.assertEqual(child.process.wait(timeout=5), 0)
        store = Store(self.root / 'manager.sqlite3')
        try:
            self.assertEqual(store.history(10), self.ledger)
        finally:
            store.close()
        self.assertEqual(self.session.read_bytes(), b'opaque-session-preservation-fixture')
