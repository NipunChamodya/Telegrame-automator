"""Owned offline subprocesses test kernel locks and orphan-safe shutdown."""
import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BackendLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.env = dict(os.environ, TGM_DATA_DIR=str(self.root),
                        PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        self.env.pop('TELEGRAM_API_ID', None)
        self.env.pop('TELEGRAM_API_HASH', None)
        self.children = []
        self.sequence = 0

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()  # Only PIDs created by this fixture.
            child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream:
                    stream.close()
        self.directory.cleanup()

    def spawn(self, code=None):
        command = [sys.executable, '-u', '-m', 'telegram_manager.ipc'] if code is None else [sys.executable, '-u', '-c', code]
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=self.env)
        self.children.append(child)
        return child

    def read(self, child):
        self.assertTrue(select.select([child.stdout], [], [], 10)[0], 'owned child response timeout')
        return json.loads(child.stdout.readline())

    def request(self, child, method, params=None):
        self.sequence += 1
        child.stdin.write((json.dumps({'id': str(self.sequence), 'method': method,
                                      'params': params or {}})+'\n').encode())
        child.stdin.flush()
        return self.read(child)

    def test_second_backend_and_cli_lock_preserve_first_then_crash_releases_lock(self):
        first = self.spawn()
        self.assertTrue(self.request(first, 'health')['ok'])
        second = self.spawn()
        self.assertEqual(self.read(second)['error']['code'], 'already_running')
        second.wait(timeout=5)
        cli = self.spawn("from pathlib import Path; import os; from telegram_manager.security import application_lock; "
                         "lock=application_lock(Path(os.environ['TGM_DATA_DIR'])); lock.__enter__()")
        cli.wait(timeout=5)
        self.assertNotEqual(cli.returncode, 0)
        self.assertTrue(self.request(first, 'status')['ok'])
        first.kill()
        first.wait(timeout=5)
        restored = self.spawn()
        self.assertTrue(self.request(restored, 'health')['ok'])
        restored.stdin.close()
        restored.wait(timeout=5)
        self.assertEqual(restored.returncode, 0)
        self.assertTrue((self.root/'manager.lock').is_file())

    def test_active_profile_lock_collision_does_not_reenter_legacy_lock(self):
        from telegram_manager.accounts import AccountRegistry
        from telegram_manager.configuration import load_configuration
        from telegram_manager.security import application_lock
        from telegram_manager.storage import Store
        registry = AccountRegistry(self.root, load_configuration(self.root))
        identity = registry.create('Offline fixture')
        profile_root = registry.root_for(identity)
        store = Store(profile_root/'manager.sqlite3')
        store.close()
        registry.activate(identity)
        with application_lock(profile_root):
            blocked = self.spawn()
            self.assertEqual(self.read(blocked)['error']['code'], 'already_running')
            blocked.wait(timeout=5)
        backend = self.spawn()
        self.assertTrue(self.request(backend, 'health')['ok'])
        response = self.request(backend, 'accounts.switch', {'profile_id':'legacy', 'confirm':True})
        self.assertTrue(response['ok'], response)
        self.assertTrue(self.request(backend, 'accounts.switch', {'profile_id':identity, 'confirm':True})['ok'])
        backend.stdin.close()
        backend.wait(timeout=5)
        self.assertEqual(backend.returncode, 0)
        with application_lock(profile_root):
            pass

    def test_parent_exit_with_inherited_writer_does_not_leave_backend_or_lock(self):
        # The fixture retains an inherited writer after the launching parent
        # exits, proving shutdown is from parent observation rather than EOF.
        code = """
import json, os, subprocess, sys
backend = subprocess.Popen([sys.executable,'-u','-m','telegram_manager.ipc'], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
os.set_inheritable(backend.stdin.fileno(), True)
backend.stdin.write(b'{"id":"ready","method":"health","params":{}}\\n'); backend.stdin.flush()
assert json.loads(backend.stdout.readline())['ok']
# Hand stdin's writer to our parent over a Unix socket via SCM_RIGHTS.
import socket, array
sock=socket.socket(fileno=int(sys.argv[1]))
sock.sendmsg([b'R'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[backend.stdin.fileno()]))])
"""
        import array
        import socket
        left, right = socket.socketpair()
        parent = subprocess.Popen([sys.executable, '-u', '-c', code, str(right.fileno())],
                                  pass_fds=(right.fileno(),), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=self.env)
        self.children.append(parent)
        right.close()
        left.settimeout(10)
        try:
            _, controls, _, _ = left.recvmsg(1, socket.CMSG_SPACE(array.array('i').itemsize))
            descriptors = array.array('i')
            descriptors.frombytes(controls[0][2][:descriptors.itemsize])
            inherited_writer = descriptors[0]
            try:
                parent.wait(timeout=5)
                # Kernel lock release is an observable endpoint; no process
                # inventory, unrelated PID probing or network is involved.
                from telegram_manager.security import ApplicationBusy, application_lock
                import time
                deadline = time.monotonic()+7
                while True:
                    try:
                        with application_lock(self.root):
                            break
                    except ApplicationBusy:
                        if time.monotonic() >= deadline:
                            self.fail('backend retained lock after its owner exited')
                        time.sleep(.05)
            finally:
                os.close(inherited_writer)
        finally:
            left.close()
