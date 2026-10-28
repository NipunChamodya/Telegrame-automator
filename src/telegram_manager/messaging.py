"""Shared bounded Unicode message validation and regular UTF-8 file import."""
import os
import stat
from pathlib import Path

MAX_MESSAGE_UNITS = 4096
MAX_IMPORT_BYTES = 65536


def message_units(message: str) -> int:
    if not isinstance(message, str):
        raise ValueError('Message must be Unicode text.')
    try:
        return len(message.encode('utf-16-le')) // 2
    except UnicodeError:
        raise ValueError('Message contains invalid Unicode characters.') from None


def validate_message(message: str) -> int:
    count = message_units(message)
    if not message.strip():
        raise ValueError('Message must not be empty.')
    if count > MAX_MESSAGE_UNITS:
        raise ValueError('Message exceeds 4096 UTF-16 units; shorten the message before sending.')
    return count


def import_message(path: Path) -> str:
    """Never follow a final symlink or read a device/FIFO/unbounded file."""
    descriptor = None
    try:
        descriptor = os.open(path.expanduser(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_IMPORT_BYTES:
            raise ValueError('Choose a regular UTF-8 text file smaller than 64 KiB.')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            raw = stream.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise ValueError('The imported file is too large; choose a file smaller than 64 KiB.')
        message = raw.decode('utf-8-sig')
        validate_message(message)
        return message
    except UnicodeError:
        raise ValueError('The selected file is not valid UTF-8 text.') from None
    except OSError:
        raise ValueError('Cannot import that file. Choose a readable regular UTF-8 file, not a link or device.') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
