"""Pure rich metadata projection never fetches or guesses Telegram content."""
import unittest
from datetime import datetime, timezone
from telethon import types
from telegram_manager.message_projection import normalize_message, safe_url


class RichProjectionTests(unittest.TestCase):
    def message(self, text='😀 සිංහල தமிழ்', **kwargs):
        return types.Message(id=1, peer_id=types.PeerUser(22), message=text, **kwargs)

    def test_styles_use_valid_utf16_offsets(self):
        value = normalize_message(self.message(entities=[types.MessageEntityBold(0, 2),
            types.MessageEntityItalic(3, 6), types.MessageEntityCode(1, 1), types.MessageEntityBold(99, 1)]))
        self.assertEqual(value['entities'], [{'type': 'bold', 'offset': 0, 'length': 2},
                                           {'type': 'italic', 'offset': 3, 'length': 6}])

    def test_changed_sanitized_text_drops_shifted_spans(self):
        value = normalize_message(self.message('a\x1bb', entities=[types.MessageEntityBold(2, 1)]))
        self.assertEqual(value['text'], 'ab')
        self.assertEqual(value['entities'], [])

    def test_links_require_safe_absolute_http_urls(self):
        value = normalize_message(self.message('click', entities=[types.MessageEntityTextUrl(0, 5, 'https://example.com'),
                                                                 types.MessageEntityTextUrl(0, 5, 'file:///etc/passwd')]))
        self.assertEqual(len(value['entities']), 1)
        self.assertEqual(value['entities'][0]['url'], 'https://example.com')
        for value in ['javascript:alert(1)', 'https://user:password@example.com', 'https://example.com:invalid', 'https://example.com\x1b']:
            self.assertIsNone(safe_url(value))

    def test_spans_bound_and_unknown_types_ignored(self):
        value = normalize_message(self.message('x', entities=[types.MessageEntityMention(0, 1)]+[types.MessageEntityBold(0, 1)]*200))
        self.assertEqual(len(value['entities']), 32)

    def test_actual_forward_and_pin_without_fetch(self):
        date = datetime(2026, 10, 28, tzinfo=timezone.utc)
        value = normalize_message(self.message(fwd_from=types.MessageFwdHeader(date, from_id=types.PeerUser(44), from_name='தமிழ்'), pinned=True))
        self.assertEqual(value['forward'], {'name': 'தமிழ்', 'sender_id': 44, 'date': date.isoformat()})
        self.assertTrue(value['pinned'])

    def test_protected_metadata_never_escapes(self):
        value = normalize_message(self.message(noforwards=True, pinned=True, entities=[types.MessageEntityBold(0, 2)]))
        self.assertEqual(value['entities'], [])
        self.assertIsNone(value['forward'])
        self.assertFalse(value['pinned'])

    def test_modify_flags_require_known_own_plain_personal_message(self):
        own = self.message('hello', out=True, from_id=types.PeerUser(11))
        self.assertTrue(normalize_message(own, 11, 'private')['can_request_edit'])
        self.assertTrue(normalize_message(own, 11, 'saved')['can_request_delete'])
        self.assertFalse(normalize_message(own)['can_request_edit'])
        self.assertFalse(normalize_message(own, 11, 'group')['can_request_edit'])
        self.assertFalse(normalize_message(own, 22, 'private')['can_request_delete'])
        own.entities = [types.MessageEntityBold(0, 5)]
        self.assertFalse(normalize_message(own, 11, 'private')['can_request_edit'])
