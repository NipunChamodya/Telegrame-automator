"""Offline Unicode, incremental sync, cache, I/O and database upgrade regressions."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telegram_manager.cache import CachePolicy, fresh
from telegram_manager.models import Group, now
from telegram_manager.storage import Store
from telegram_manager.terminal import TerminalOutputError, clean_text, json_text, print as terminal_print


class UnicodeTests(unittest.TestCase):
    def test_names_combining_characters_and_emoji_round_trip(self):
        samples = ['ශ්‍රී ලංකා Chat', 'தமிழ் குழு', 'English 👩🏽‍💻 👨‍👩‍👧‍👦 🇱🇰', 'e\u0301']
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(clean_text(sample), sample)
                result = json_text({'name': sample})
                self.assertIn(sample, result)
                self.assertEqual(json.loads(result)['name'], sample)
                with patch('sys.stdout', new=io.StringIO()) as output:
                    terminal_print(result)
                self.assertIn(sample, output.getvalue())

    def test_terminal_escape_sequences_and_controls_are_removed(self):
        sample = '\x1b[31mශ්‍රී\x1b[0m\x1b]0;secret-title\x07 ලංකා\x08\r\u202e 👩\u200d💻'
        result = clean_text(sample)
        self.assertEqual(result, 'ශ්‍රී ලංකා 👩\u200d💻')
        self.assertEqual(json.loads(json_text({'message': '\x1b[31mதமிழ்\u202e'}))['message'], '\x1b[31mதமிழ்\u202e')
        self.assertNotIn('\x1b', json_text({'name': sample}))
        self.assertNotIn('\u202e', json_text({'name': sample}))

    def test_unsupported_terminal_encoding_falls_back_without_crashing(self):
        class AsciiStream(io.StringIO):
            encoding = 'ascii'
        with patch('sys.stdout', new=AsciiStream()) as output:
            terminal_print('ශ්‍රී 👩🏽‍💻')
        self.assertIn('\\u', output.getvalue())

    def test_closed_prompt_output_is_not_misclassified_as_network(self):
        from telegram_manager.terminal import input as terminal_input
        with patch('builtins.input', side_effect=BrokenPipeError('private-pipe')):
            with self.assertRaises(TerminalOutputError):
                terminal_input('Select: ')

    def test_closed_output_is_distinct_from_telegram_broken_pipe(self):
        stream = Mock()
        stream.encoding = 'utf-8'
        stream.write.side_effect = BrokenPipeError('private-output-details')
        with self.assertRaises(TerminalOutputError) as caught:
            terminal_print('ශ්‍රී', file=stream, flush=True)
        self.assertNotIn('private-output-details', str(caught.exception))
        stream.write.assert_called_once()


class StorageOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'manager.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_unicode_storage_and_legacy_json_search(self):
        group = Group(-1, 'ශ්‍රී ලංකා தமிழ் 👩🏽‍💻', 'group')
        self.store.save_group(1, group)
        # Existing ensure_ascii=True metadata still decodes without migrations.
        with self.store.db:
            self.store.db.execute('UPDATE groups SET metadata=? WHERE account=? AND id=?',
                                  (json.dumps(group.data(), ensure_ascii=True), 1, -1))
        page, count = self.store.page(1, query='ශ්‍රී')
        self.assertEqual(count, 1)
        self.assertEqual(page[0]['name'], group.name)
        self.assertEqual(self.store.page(2, query='ශ්‍රී')[1], 0)

    def test_identical_upsert_is_a_no_op_and_lookup_is_account_scoped(self):
        group = Group(-1, 'Test', 'group')
        self.store.save_group(1, group)
        changes = self.store.db.total_changes
        self.store.save_group(1, group)
        self.assertEqual(self.store.db.total_changes, changes)
        self.assertTrue(self.store.contains_group(1, -1))
        self.assertFalse(self.store.contains_group(2, -1))

    def test_pagination_filters_sorting_and_stale_permissions(self):
        for index in range(27):
            self.store.save_group(1, Group(-index - 1, f'Group {index:02}', 'group', permission='allowed',
                                           permissions_checked_at=now() if index < 12 else None))
        rows, count = self.store.page(1, permission='allowed', size=10)
        self.assertEqual((len(rows), count), (10, 12))
        self.assertEqual(len(self.store.page(1, permission='allowed', page=1, size=10)[0]), 2)
        rows, count = self.store.page(1, permission='unknown', sort='id', size=10)
        self.assertEqual(count, 15)
        self.assertEqual(rows[0]['id'], -27)
        self.assertEqual(self.store.overview(1)['pending'], 15)
        self.assertEqual(self.store.overview(2)['total'], 0)

    def test_legacy_database_upgrade_is_idempotent_and_preserves_ledger(self):
        self.store.save_group(1, Group(-1, 'Saved', 'group'))
        self.store.reserve(1, -1, 'already attempted')
        self.store.set_cooldown(1, 9999999999)
        history = self.store.history(1)
        self.store.close()
        # Model the previous schema by removing only the NEW empty test table.
        connection = sqlite3.connect(self.path)
        connection.execute('DROP TABLE sync_runs')
        connection.close()
        self.store = Store(self.path)
        self.store.save_scan(1, {'state': 'completed', 'processed': 1})
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.history(1), history)
        self.assertEqual(self.store.cooldown(1), 9999999999)
        self.assertEqual(self.store.groups(1)[0]['name'], 'Saved')
        self.assertEqual(self.store.scan(1)['processed'], 1)
        self.assertEqual(self.store.scan(2), {})


class CacheTests(unittest.TestCase):
    def test_independent_lifetimes_and_invalid_dates(self):
        policy = CachePolicy(permissions=60, members=120, metadata=3600)
        old = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        group = Group(-1, 'Cached', 'group', permission='allowed', metadata_status='complete',
                      permissions_checked_at=old, members_checked_at=old, metadata_checked_at=old).data()
        self.assertFalse(policy.details_fresh(group))
        self.assertEqual(policy.permission(group), 'unknown')
        self.assertTrue(fresh(old, policy.members))
        self.assertFalse(fresh('invalid', 999))
        self.assertFalse(fresh('2026-01-01', 999))

    def test_policy_environment_validation(self):
        with patch.dict(os.environ, {'TGM_PERMISSIONS_TTL_SECONDS': '17'}):
            self.assertEqual(CachePolicy.from_environment().permissions, 17)
        with patch.dict(os.environ, {'TGM_PERMISSIONS_TTL_SECONDS': '-1'}):
            with self.assertRaises(ValueError):
                CachePolicy.from_environment()


try:
    import telethon
except ImportError:
    telethon = None

if telethon:
    from telethon import errors, functions, types, utils
    from telegram_manager.dashboard import Dashboard
    from telegram_manager.telegram import TelegramService, discover_with_output
    from test_discovery import chat, channel, full_chat, participant

    class IncrementalSyncTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self):
            self.directory = tempfile.TemporaryDirectory()
            self.store = Store(Path(self.directory.name) / 'manager.sqlite3')
            self.client = AsyncMock()
            self.entities = [chat(), channel()]
            async def dialogs(**kwargs):
                for entity in self.entities:
                    yield NS(entity=entity, archived=True)
            self.client.iter_dialogs = Mock(side_effect=dialogs)
            self.client.get_entity.side_effect = lambda value: next(e for e in self.entities if utils.get_peer_id(e) == value) if isinstance(value, int) else value
            def response(request):
                entity = next(e for e in self.entities if e.id == (
                    request.chat_id if isinstance(request, functions.messages.GetFullChatRequest) else request.channel.id))
                return NS(participant=participant(entity).participant) if isinstance(request, functions.channels.GetParticipantRequest) else full_chat(entity)
            self.client.side_effect = response
            self.service = TelegramService(self.client, self.store, NS(id=10, restricted=False))
            self.service.request_interval = 0

        async def asyncTearDown(self):
            self.store.close()
            self.directory.cleanup()

        async def test_failed_group_write_does_not_advance_committed_scan_counts(self):
            original = self.store.save_group
            def write(account, group, **kwargs):
                if group.id == utils.get_peer_id(self.entities[1]):
                    raise sqlite3.OperationalError('private-db-path')
                return original(account, group, **kwargs)
            with patch.object(self.store, 'save_group', side_effect=write):
                with self.assertRaises(sqlite3.OperationalError):
                    await self.service.discover()
            self.assertEqual(self.store.scan(10)['processed'], 1)
            self.assertEqual(self.store.scan(10)['state'], 'database_error')
            self.assertEqual(len(self.store.groups(10)), 1)

        async def test_lightweight_scan_has_zero_per_group_api_requests(self):
            self.assertEqual(await self.service.discover(), 2)
            self.client.get_entity.assert_not_called()
            self.client.get_permissions.assert_not_called()
            self.client.assert_not_called()
            self.assertEqual(self.store.scan(10)['new'], 2)
            self.assertEqual(self.store.overview(10)['pending'], 2)
            self.assertTrue(all(g['archived'] for g in self.store.groups(10)))
            self.client.iter_dialogs.assert_called_once_with(ignore_migrated=True)

        async def test_incremental_sync_preserves_inspection_and_tracks_changes(self):
            await self.service.discover(detailed=True)
            self.assertEqual(self.store.overview(10)['allowed'], 2)
            self.client.reset_mock()
            self.entities[0].title = 'ශ්‍රී ලංකා 👩🏽‍💻'
            await self.service.discover()
            scan = self.store.scan(10)
            self.assertEqual((scan['new'], scan['updated'], scan['unchanged']), (0, 1, 1))
            self.assertEqual(scan['cache_skipped'], 2)
            self.assertEqual(self.store.get_group(10, -1)['name'], self.entities[0].title)
            self.assertEqual(self.store.overview(10)['allowed'], 2)
            self.client.assert_not_called()
            self.client.get_entity.assert_not_called()
            self.entities[0] = types.ChatForbidden(id=1, title=self.entities[0].title)
            await self.service.discover()
            self.assertEqual(self.store.scan(10)['updated'], 1)
            self.assertEqual(self.store.overview(10)['denied'], 1)

        async def test_basic_chat_full_metadata_is_fetched_once_not_twice(self):
            self.entities = [chat()]
            await self.service.discover(detailed=True)
            self.assertEqual(self.client.call_count, 1)
            self.assertIsInstance(self.client.call_args.args[0], functions.messages.GetFullChatRequest)
            self.client.get_permissions.assert_not_called()

        async def test_fresh_details_skip_all_requests_and_force_refreshes(self):
            await self.service.discover(detailed=True)
            self.client.reset_mock()
            self.assertEqual(await self.service.inspect_pending(), 0)
            self.client.assert_not_called()
            self.client.get_entity.assert_not_called()
            self.assertEqual(self.store.scan(10)['cache_skipped'], 2)
            self.assertEqual(await self.service.inspect_pending(force=True), 2)
            self.assertEqual(self.client.call_count, 3)  # One basic full + super full + single participant.

        async def test_expired_permission_refresh_avoids_fresh_supergroup_full_metadata(self):
            self.entities = [channel()]
            await self.service.discover(detailed=True)
            data = self.store.get_group(10, utils.get_peer_id(self.entities[0]))
            group = Group.from_data(data)
            group.permissions_checked_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            self.store.save_group(10, group)
            self.client.reset_mock()
            self.assertEqual(await self.service.inspect_pending(), 1)
            self.assertEqual(self.client.call_count, 1)
            self.assertIsInstance(self.client.call_args.args[0], functions.channels.GetParticipantRequest)
            self.assertEqual(self.store.overview(10)['allowed'], 1)

        async def test_unknown_metadata_attempt_is_briefly_cached_without_becoming_allowed(self):
            self.entities = [chat()]
            self.client.side_effect = errors.ChatAdminRequiredError(None)
            await self.service.discover(detailed=True)
            self.assertEqual(self.store.overview(10)['unknown'], 1)
            self.client.reset_mock()
            self.assertEqual(await self.service.inspect_pending(), 0)
            self.client.assert_not_called()
            self.assertEqual(self.store.overview(10)['unknown'], 1)

        async def test_floodwait_from_dialog_paging_is_saved_and_not_retried(self):
            async def interrupted(**kwargs):
                yield NS(entity=chat(), archived=True)
                raise errors.FloodWaitError(None, capture=16)
            self.client.iter_dialogs.side_effect = interrupted
            with patch('sys.stdout', new=io.StringIO()) as output:
                with self.assertRaises(errors.FloodWaitError):
                    await discover_with_output(self.service)
            self.assertEqual(self.store.scan(10)['state'], 'cooldown')
            self.assertEqual(self.store.scan(10)['processed'], 1)
            self.assertIn('16-second cooldown', output.getvalue())
            self.client.iter_dialogs.assert_called_once()
            self.client.assert_not_called()
            with self.assertRaises(ValueError):
                await self.service.discover()
            self.assertEqual(len(self.store.groups(10)), 1)

        async def test_cooldown_expires_but_only_explicit_continuation_resumes(self):
            self.store.set_cooldown(10, 100)
            self.client.iter_dialogs.assert_not_called()
            with patch('telegram_manager.telegram.time.time', return_value=101):
                await self.service.discover()
            self.client.iter_dialogs.assert_called_once()

        async def test_network_broken_pipe_has_sanitized_operation_and_preserves_progress(self):
            async def interrupted(**kwargs):
                yield NS(entity=chat(), archived=True)
                raise BrokenPipeError('private-phone-secret-address')
            self.client.iter_dialogs.side_effect = interrupted
            with self.assertLogs('telegram_manager.discovery') as logs:
                with self.assertRaises(BrokenPipeError):
                    await self.service.discover()
            result = ''.join(logs.output)
            self.assertIn('dialog_iteration', result)
            self.assertIn('"database_writes_completed": true', result)
            self.assertNotIn('private-phone-secret-address', result)
            self.assertEqual(self.store.scan(10)['state'], 'network_interrupted')
            self.assertEqual(len(self.store.groups(10)), 1)

        async def test_metadata_transport_broken_pipe_identifies_request_boundary(self):
            await self.service.discover()
            self.client.get_entity.side_effect = BrokenPipeError('private-host-token')
            with self.assertLogs('telegram_manager.discovery') as logs:
                with self.assertRaises(BrokenPipeError):
                    await self.service.inspect_pending()
            output = ''.join(logs.output)
            self.assertIn('entity_lookup', output)
            self.assertIn('"line":', output)
            self.assertNotIn('private-host-token', output)
            self.assertEqual(self.store.scan(10)['state'], 'network_interrupted')

        async def test_output_broken_pipe_stops_after_committing_current_group(self):
            def output(*args):
                raise TerminalOutputError('safe message')
            with self.assertLogs('telegram_manager.discovery') as logs:
                with self.assertRaises(TerminalOutputError):
                    await self.service.discover(on_group=output)
            self.assertIn('terminal_output', ''.join(logs.output))
            self.assertEqual(self.store.scan(10)['state'], 'output_unavailable')
            self.assertEqual(self.store.scan(10)['processed'], 1)
            self.assertEqual(len(self.store.groups(10)), 1)
            self.client.assert_not_called()

        async def test_pending_resume_skips_completed_inspections_after_partial_failure(self):
            self.entities = [chat(), chat(2)]
            self.client.side_effect = [full_chat(chat()), BrokenPipeError('private')]
            with self.assertLogs('telegram_manager.discovery'), self.assertRaises(BrokenPipeError):
                await self.service.discover(detailed=True)
            self.assertEqual(self.store.overview(10)['complete'], 1)
            self.client.side_effect = lambda request: full_chat(chat(request.chat_id))
            self.client.reset_mock()
            self.assertEqual(await self.service.inspect_pending(), 1)
            self.assertEqual(self.client.call_count, 1)
            self.assertEqual(self.store.overview(10)['complete'], 2)

        async def test_standalone_group_json_output_is_unicode_and_machine_readable(self):
            from telegram_manager.cli import parser, run
            self.entities[0].title = 'ශ්‍රී ලංකා தமிழ் 👩🏽‍💻'
            await self.service.discover()
            self.client.is_user_authorized.return_value = True
            self.client.get_me.return_value = NS(id=10, bot=False)
            with patch.dict(os.environ, {'TGM_DATA_DIR': self.directory.name,
                                         'TELEGRAM_API_ID': '123', 'TELEGRAM_API_HASH': 'a' * 32}), \
                    patch('telegram_manager.cli.TelegramClient', return_value=self.client), \
                    patch('sys.stdout', new=io.StringIO()) as output, patch('sys.stderr', new=io.StringIO()) as status:
                await run(parser().parse_args(['groups', '--search', 'ශ්‍රී']))
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['name'], self.entities[0].title)
            self.assertIn('ශ්‍රී', output.getvalue())
            self.assertIn('Page 1', status.getvalue())

        async def test_dashboard_statistics_and_unicode_paginated_filtering(self):
            self.entities[0].title = 'ශ්‍රී ලංකා தமிழ் 👩🏽‍💻'
            await self.service.discover()
            dashboard = Dashboard(self.service, Path(self.directory.name), 'test')
            with patch('builtins.input', side_effect=['f', 'unknown', 's', 'id', 'q']), patch('sys.stdout', new=io.StringIO()) as output:
                dashboard.header()
                dashboard.view_groups()
            self.assertIn('Posting unknown: 2', output.getvalue())
            self.assertIn('Awaiting permission inspection: 2', output.getvalue())
            self.assertIn('ශ්‍රී ලංකා தமிழ் 👩🏽‍💻', output.getvalue())
            self.assertNotIn('\\u0', output.getvalue())
            self.assertIn('filter: unknown', output.getvalue())

        async def test_narrow_terminal_does_not_crash_and_names_remain_intact_in_storage(self):
            self.entities[0].title = 'ශ්‍රී ලංකා 👩🏽‍💻' * 5
            await self.service.discover()
            with patch('telegram_manager.terminal.shutil.get_terminal_size', return_value=os.terminal_size((22, 20))), \
                    patch('builtins.input', return_value='q'), patch('sys.stdout', new=io.StringIO()):
                Dashboard(self.service, Path(self.directory.name), 'test').view_groups()
            self.assertEqual(self.store.get_group(10, -1)['name'], self.entities[0].title)

        async def test_output_failure_after_acknowledgement_keeps_ledger_and_clears_selection(self):
            group = Group(-1, 'ශ්‍රී', 'group', permission='allowed', permissions_checked_at=now())
            self.store.save_group(10, group)
            class Output(io.StringIO):
                broken = False
                def write(self, value):
                    if self.broken:
                        raise BrokenPipeError('private-pipe')
                    return super().write(value)
            output = Output()
            async def send(destination, message):
                delivery, _ = self.store.reserve(10, destination, message)
                self.store.finish(delivery, 'sent', 'acknowledged')
                output.broken = True
                return 'Sent'
            fake = NS(store=self.store, me=NS(id=10), client=self.client,
                      inspect=AsyncMock(return_value=group), send=AsyncMock(side_effect=send))
            dashboard = Dashboard(fake, Path(self.directory.name), 'test')
            dashboard.message, dashboard.destination = 'explicit message', -1
            with patch('telegram_manager.dashboard.authenticate', new=AsyncMock(return_value=NS(id=10))), \
                    patch('builtins.input', return_value='SEND -1'), patch('sys.stdout', output):
                with self.assertRaises(TerminalOutputError):
                    await dashboard.send()
            self.assertIsNone(dashboard.destination)
            self.assertEqual(self.store.history(10)[0]['status'], 'sent')
            fake.send.assert_awaited_once()

        async def test_cached_allowed_never_authorizes_delivery_without_fresh_inspection(self):
            await self.service.discover(detailed=True)
            self.client.is_user_authorized.return_value = True
            self.client.get_me.return_value = NS(id=10)
            self.client.get_entity.side_effect = errors.ChannelPrivateError(None)
            with self.assertRaises(ValueError):
                await self.service.send(-1, 'must not send')
            self.assertEqual(self.store.history(10), [])
            self.assertFalse(any(isinstance(c.args[0], functions.messages.SendMessageRequest)
                                 for c in self.client.call_args_list))
