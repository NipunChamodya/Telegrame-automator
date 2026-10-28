"""Observe only the backend's actual launching parent; never inspect other processes."""
from __future__ import annotations

import asyncio
import os
import select


async def wait_for_parent_exit(parent_pid: int) -> None:
    """Native event-driven macOS parent death detection, including inherited pipes.

    EOF is still the ordinary shutdown signal. A sibling can inherit a pipe's
    writer, so EOF alone cannot prove the owner remains alive. No PID is killed.
    """
    if parent_pid <= 1 or os.getppid() != parent_pid:
        return
    if hasattr(select, 'kqueue'):
        queue = select.kqueue()
        loop = asyncio.get_running_loop()
        exited = loop.create_future()
        registered = False
        try:
            event = select.kevent(parent_pid, filter=select.KQ_FILTER_PROC,
                                 flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                 fflags=select.KQ_NOTE_EXIT)
            try:
                queue.control([event], 0, 0)
            except ProcessLookupError:
                return
            def ready() -> None:
                if queue.control([], 1, 0) and not exited.done():
                    exited.set_result(None)
            loop.add_reader(queue.fileno(), ready)
            registered = True
            if os.getppid() != parent_pid:
                return
            await exited
            return
        except (OSError, NotImplementedError):
            # Some restricted environments deny proc filters. The fallback only
            # observes our own PPID, never enumerates or signals another process.
            pass
        finally:
            if registered:
                loop.remove_reader(queue.fileno())
            queue.close()
    while os.getppid() == parent_pid:
        await asyncio.sleep(1)
