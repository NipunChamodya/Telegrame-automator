"""Private local storage and native macOS Keychain access (no shell secrets)."""
import ctypes
import fcntl
import os
import platform
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def private_directory(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Data directory must not be a symlink.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise ValueError("Data directory must be owned by the current user.")
    path.chmod(0o700)
    for child in path.iterdir():
        if child.is_symlink():
            raise ValueError("Data directory must not contain symlinks.")
        if child.is_file():
            if child.stat().st_uid != os.getuid() or child.stat().st_nlink != 1:
                raise ValueError("Application files must be privately owned and not hard linked.")
            child.chmod(0o600)
    return path


class ApplicationBusy(ValueError):
    """Another CLI/desktop backend already owns this private data directory."""


@contextmanager
def application_lock(root: Path) -> Iterator[None]:
    descriptor = os.open(root / "manager.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ApplicationBusy("Another manager process is running; close it first.") from None
        yield


class KeychainError(ValueError):
    pass


class MacKeychain:
    """One generic-password item per data directory; never replace existing secrets."""
    def __init__(self, service: str):
        if platform.system() != "Darwin":
            raise KeychainError("macOS Keychain is unavailable on this operating system.")
        self.service = service.encode()
        self.account = str(os.getuid()).encode()
        self.lib = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        pointer, integer = ctypes.c_void_p, ctypes.c_uint32
        self.lib.SecKeychainFindGenericPassword.argtypes = [
            pointer, integer, pointer, integer, pointer,
            ctypes.POINTER(integer), ctypes.POINTER(pointer), ctypes.POINTER(pointer)]
        self.lib.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        self.lib.SecKeychainAddGenericPassword.argtypes = [
            pointer, integer, pointer, integer, pointer, integer, pointer, ctypes.POINTER(pointer)]
        self.lib.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        self.lib.SecKeychainItemFreeContent.argtypes = [pointer, pointer]
        self.lib.SecKeychainItemFreeContent.restype = ctypes.c_int32

    def read(self) -> str | None:
        length, data = ctypes.c_uint32(), ctypes.c_void_p()
        status = self.lib.SecKeychainFindGenericPassword(
            None, len(self.service), self.service, len(self.account), self.account,
            ctypes.byref(length), ctypes.byref(data), None)
        if status == -25300:  # errSecItemNotFound
            return None
        if status:
            raise KeychainError("Keychain access failed or was declined. Unlock Keychain and try again.")
        try:
            return ctypes.string_at(data, length.value).decode("utf-8")
        finally:
            self.lib.SecKeychainItemFreeContent(None, data)

    def save_new(self, secret: str) -> None:
        data = secret.encode()
        status = self.lib.SecKeychainAddGenericPassword(
            None, len(self.service), self.service, len(self.account), self.account,
            len(data), data, None)
        if status:
            raise KeychainError("Keychain storage failed or an item already exists; nothing was overwritten.")
