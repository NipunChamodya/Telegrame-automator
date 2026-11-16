"""Atomic non-overwriting publication, including macOS volumes without hard links."""

import ctypes
import errno
import os
import sys


def publish(directory, temporary, destination):
    try:
        os.link(
            temporary,
            destination,
            src_dir_fd=directory,
            dst_dir_fd=directory,
            follow_symlinks=False,
        )
    except OSError as exc:
        if sys.platform != "darwin" or exc.errno not in {
            errno.EPERM,
            errno.EOPNOTSUPP,
            errno.ENOSYS,
        }:
            raise
        library = ctypes.CDLL(None, use_errno=True)
        rename = library.renameatx_np
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        # RENAME_EXCL, defined by the installed macOS SDK in sys/stdio.h.
        if rename(
            directory,
            os.fsencode(temporary),
            directory,
            os.fsencode(destination),
            0x00000004,
        ):
            raise OSError(ctypes.get_errno(), "The file could not be published safely.")
