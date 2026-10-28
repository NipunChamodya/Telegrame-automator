"""Private multi-account profiles, preserving the original CLI data location.

The registry contains only stable local IDs and verified account/display metadata.
Profile IDs never derive from phone numbers, and are never renamed after login.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import secrets
import shutil
import stat
import tempfile
from pathlib import Path

from .configuration import keychain_service
from .security import KeychainError, MacKeychain, private_directory
from .terminal import clean_text

LEGACY = 'legacy'
PROFILE_ID = re.compile(r'profile_[a-f0-9]{32}')
MAX_REGISTRY_BYTES = 262144


class ProfileError(ValueError):
    pass


def _read(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_size > MAX_REGISTRY_BYTES):
            raise ProfileError('Account registry is not a private bounded file.')
        raw = stream.read(MAX_REGISTRY_BYTES + 1)
    try:
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    raise ProfileError('Account registry contains duplicate JSON keys.')
                result[key] = item
            return result
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise ProfileError('Account registry is invalid and was not reset.') from None
    if not isinstance(value, dict):
        raise ProfileError('Account registry is invalid and was not reset.')
    return value


class AccountRegistry:
    def __init__(self, root: Path, legacy_config: dict):
        self.root = root
        self.path = root / 'account-profiles.json'
        if self.path.exists():
            self.data = _read(self.path)
            self._validate(self.data)
        else:
            self.data = {'version': 1, 'active_profile_id': LEGACY, 'profiles': [{
                'profile_id': LEGACY, 'label': 'Existing account', 'display_name': '',
                'telegram_id': legacy_config.get('account_id'), 'legacy': True,
                'archived': False, 'data_removed': False, 'session_state': 'unknown'}]}
            self._commit(self.data, create=True)

    @staticmethod
    def _validate(data: dict) -> None:
        if set(data) != {'version', 'active_profile_id', 'profiles'} or data.get('version') != 1 or not isinstance(data.get('profiles'), list) or not 1 <= len(data['profiles']) <= 1000:
            raise ProfileError('Account registry has an unsupported structure.')
        ids = set()
        known_accounts = set()
        for profile in data['profiles']:
            if not isinstance(profile, dict):
                raise ProfileError('Account registry has an invalid profile.')
            if set(profile) != {'profile_id', 'label', 'display_name', 'telegram_id', 'legacy', 'archived', 'data_removed', 'session_state'}:
                raise ProfileError('Account registry contains unsupported profile fields.')
            identity = profile.get('profile_id')
            if not isinstance(identity, str) or identity != LEGACY and not PROFILE_ID.fullmatch(identity) or identity in ids:
                raise ProfileError('Account registry has an invalid or duplicate local identifier.')
            ids.add(identity)
            if profile.get('legacy') is not (identity == LEGACY):
                raise ProfileError('Account registry legacy identity is invalid.')
            for key in ('archived', 'data_removed'):
                if type(profile.get(key)) is not bool:
                    raise ProfileError('Account registry flags are invalid.')
            for key in ('label', 'display_name', 'session_state'):
                if not isinstance(profile.get(key), str) or len(profile[key]) > 200:
                    raise ProfileError('Account registry display metadata is invalid.')
            account = profile.get('telegram_id')
            if account is not None and (type(account) is not int or not 0 < account < 2**63):
                raise ProfileError('Account registry account identity is invalid.')
            if account is not None and not profile['data_removed']:
                if account in known_accounts:
                    raise ProfileError('An account is bound to more than one local profile.')
                known_accounts.add(account)
        active = next((p for p in data['profiles'] if p['profile_id'] == data.get('active_profile_id')), None)
        if LEGACY not in ids or active is None or active['archived'] or active['data_removed']:
            raise ProfileError('Account registry active profile is invalid.')

    def _commit(self, updated: dict, *, create: bool = False) -> None:
        self._validate(updated)
        descriptor, temporary = tempfile.mkstemp(prefix='.account-profiles-', dir=self.root)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(updated, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            if create:
                os.link(temporary, self.path)
            else:
                if _read(self.path) != self.data:
                    raise ProfileError('Account registry changed externally and was not overwritten.')
                os.replace(temporary, self.path)
            self.data = updated
        finally:
            Path(temporary).unlink(missing_ok=True)

    @property
    def active(self) -> str:
        return self.data['active_profile_id']

    def profile(self, identity: str, *, allow_archived: bool = False) -> dict:
        if identity != LEGACY and (not isinstance(identity, str) or not PROFILE_ID.fullmatch(identity)):
            raise ProfileError('Choose an existing local account profile.')
        profile = next((p for p in self.data['profiles'] if p['profile_id'] == identity), None)
        if profile is None or profile['data_removed'] or profile['archived'] and not allow_archived:
            raise ProfileError('This account profile is unavailable or archived.')
        return dict(profile)

    def root_for(self, identity: str, *, allow_archived: bool = False) -> Path:
        self.profile(identity, allow_archived=allow_archived)
        if identity == LEGACY:
            return self.root
        parent = self.root / 'profiles'
        if parent.is_symlink():
            raise ProfileError('The account profile directory must not be a symlink.')
        candidate = parent / identity
        if candidate.is_symlink():
            raise ProfileError('An account profile must not be a symlink.')
        return candidate

    def create(self, label: str) -> str:
        label = clean_text(label).strip()
        if not label or len(label) > 80:
            raise ProfileError('Enter an account label containing 1–80 characters.')
        if sum(not p['data_removed'] and not p['archived'] for p in self.data['profiles']) >= 50:
            raise ProfileError('At most 50 active local profiles are supported. Archive an unused profile first.')
        identity = 'profile_' + secrets.token_hex(16)
        parent = private_directory(self.root / 'profiles')
        private_directory(parent / identity)
        profile = {'profile_id': identity, 'label': label, 'display_name': '', 'telegram_id': None,
                   'legacy': False, 'archived': False, 'data_removed': False, 'session_state': 'new'}
        self._commit(self.data | {'profiles': self.data['profiles'] + [profile]})
        return identity

    def activate(self, identity: str) -> None:
        self.profile(identity)
        self._commit(self.data | {'active_profile_id': identity})

    def identity_available(self, identity: str, account: int) -> None:
        profile = self.profile(identity)
        if profile['telegram_id'] not in (None, account):
            raise ProfileError('The verified account does not match this profile. Existing records were preserved.')
        if any(p['profile_id'] != identity and p.get('telegram_id') == account and not p['data_removed']
               for p in self.data['profiles']):
            raise ProfileError('This Telegram account already has a profile. Switch to or restore that profile to preserve its delivery ledger.')

    def update(self, identity: str, **changes) -> None:
        self.profile(identity, allow_archived=True)
        allowed = {'label', 'display_name', 'telegram_id', 'archived', 'data_removed', 'session_state'}
        if set(changes) - allowed:
            raise ProfileError('Unsupported account metadata update.')
        profiles = [p | changes if p['profile_id'] == identity else p for p in self.data['profiles']]
        self._commit(self.data | {'profiles': profiles})

    def verify(self, identity: str, account: int, display_name: str) -> None:
        self.identity_available(identity, account)
        self.update(identity, telegram_id=account, display_name=clean_text(display_name)[:200], session_state='authorized')

    def list(self, *, include_archived: bool = False) -> list[dict]:
        result = []
        for profile in self.data['profiles']:
            if profile['data_removed'] or profile['archived'] and not include_archived:
                continue
            root = self.root_for(profile['profile_id'], allow_archived=True)
            identity = profile['profile_id']
            result.append(profile | {'id': identity, 'is_active': identity == self.active,
                'session_present': (root / 'account.session').is_file(),
                'auth_state': profile['session_state'],
                'logout_confirmation': f'LOG OUT {identity}', 'remove_confirmation': f'REMOVE {identity}'})
        return result

    def remove_files(self, identity: str) -> None:
        """Delete only an explicitly selected new profile; never the legacy root."""
        if identity == LEGACY:
            raise ProfileError('The original account profile is protected. Disconnect it instead; its existing files were not removed.')
        if self.active == identity:
            raise ProfileError('Switch away from the profile before removing its local files.')
        source = self.root_for(identity, allow_archived=True)
        if not source.is_dir() or source.is_symlink() or source.stat().st_uid != os.getuid():
            raise ProfileError('The selected profile directory is unavailable. Other profiles were not changed.')
        # Refuse links/foreign objects before any destructive operation. rmtree's
        # fd-based implementation then protects against directory-symlink races.
        if not shutil.rmtree.avoids_symlink_attacks:
            raise ProfileError('Secure profile removal is unavailable on this Python runtime.')
        for directory, dirs, files in os.walk(source, followlinks=False):
            for name in dirs + files:
                path = Path(directory) / name
                info = path.lstat()
                if path.is_symlink() or info.st_uid != os.getuid() or path.is_file() and info.st_nlink != 1:
                    raise ProfileError('Profile removal refused an unsafe linked or foreign-owned file.')
        if _read(self.path) != self.data:
            raise ProfileError('Account registry changed externally; profile removal was not started.')
        delete_profile_credentials(source)
        staged = source.parent / ('.removing-' + identity + '-' + secrets.token_hex(8))
        os.rename(source, staged)
        try:
            shutil.rmtree(staged)
        except OSError:
            if staged.exists() and not source.exists():
                os.rename(staged, source)
            raise ProfileError('Selected profile removal did not finish. Other account profiles were not changed.') from None
        self.update(identity, archived=True, data_removed=True, session_state='removed')


def delete_profile_credentials(root: Path) -> bool:
    """Delete the one selected profile's native Keychain item without reading it."""
    if platform.system() != 'Darwin':
        return False
    keychain = MacKeychain(keychain_service(root))
    item = ctypes.c_void_p()
    status = keychain.lib.SecKeychainFindGenericPassword(None, len(keychain.service), keychain.service,
        len(keychain.account), keychain.account, None, None, ctypes.byref(item))
    if status == -25300:
        return False
    if status:
        raise KeychainError('Keychain removal was declined or failed; local profile files were preserved.')
    core = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    core.CFRelease.argtypes = [ctypes.c_void_p]
    core.CFRelease.restype = None
    keychain.lib.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
    keychain.lib.SecKeychainItemDelete.restype = ctypes.c_int32
    try:
        if keychain.lib.SecKeychainItemDelete(item):
            raise KeychainError('Keychain removal failed; local profile files were preserved.')
    finally:
        core.CFRelease(item)
    return True
