# Backend ownership and lock lifecycle

The native app owns one Python JSONL subprocess. The CLI remains a separate
maintenance client; close it before opening the desktop app against the same
installation. A rejected second launch returns `already_running` and never
steals a lock, deletes a lock file, resets a session, or touches credentials.

`manager.lock` uses a nonblocking kernel advisory lock, not a PID file. Its
continued presence on disk after a crash is normal. The kernel releases the lock
when its owning process exits. Deleting this file while a process runs would
undermine exclusion and is not a recovery procedure.

## Account switching

The backend holds the original installation lock for its entire lifetime. When
a separate profile is active it additionally holds that profile's lock. Legacy
activation reuses the already-held installation lock; it never acquires that lock
a second time. Switching acquires and validates the destination first, disconnects
the old client, swaps the store and account generation, then releases the previous
profile lock. A busy destination leaves the current account intact. Successful
lock entry is tracked separately so startup failure cannot exit an unentered lock
context. Shutdown releases the profile lock even if Telegram disconnect fails;
disconnect has a five-second bound.

## EOF, broken pipes, and owner exit

Ordinary closure of the input pipe cancels outstanding operations, drains bounded
protocol output, disconnects Telegram and closes storage. Closed output also stops
processing. Protocol stdout never contains CLI banners or diagnostics.

EOF alone is insufficient when another process inherits an input writer. On macOS
the backend watches its actual launching parent using `kqueue` process-exit events.
This is idle event-driven observation, with no process enumeration, arbitrary PID
input, or signals. The registration/parent-exit race is checked explicitly. If
process filters are unavailable, a one-second check of the backend's own parent ID
provides a conservative fallback. Parent disappearance triggers the same orderly
cancellation path even if a sibling still holds an inherited writer. The native
client should still close its own pipe handles and await its exact child before
launching a replacement; the parent observer is an additional safeguard.

A send interrupted after submission keeps the existing delivery ledger's uncertain
outcome semantics. Neither shutdown nor reconnection retries that delivery.

## Verification and recovery

`tests/test_backend_lifecycle.py` runs real isolated subprocesses without Telegram
network calls or user storage. It verifies a sole backend, rejected second backend,
a competing CLI-style lock owner, crash/restart lock release, active-profile startup
collision, switching between legacy and a new profile, and parent exit while an
inherited input writer remains open. Other profile subprocess tests verify cached
drafts, account binding, delivery-ledger and opaque session preservation.

If a client reports `already_running`, quit the other CLI/desktop instance and
retry. If a child fails to stop, diagnose only the owned child's PID and parent;
never kill all Python processes or delete sessions/database/lock files. A process
inventory may be blocked in restricted development environments. The tests use
only their own spawned PIDs and do not bypass those restrictions.

These tests establish offline process and lock behavior; they do not verify live
Telegram authentication, discovery, or delivery.


## Native owner and explicit recovery

The app has a single workspace `Window` and one app-scoped model/transport; Settings shares that owner. Repeated appearances call an idempotent startup guard. A separate app process remains blocked by the same kernel lock. No lock is disabled to make an error disappear.

`BackendClient.request()` cannot start a process. Only explicit startup or Retry Connection does so. Cached views and failed requests cannot silently spawn replacements. Restart first shuts down and reaps the exact managed child, then starts one replacement. Concurrent shutdown callers wait for the same cleanup. Closing unused pipe ends and close-on-exec flags support prompt EOF/SIGPIPE detection. A typed startup error is drained before process-exit cleanup, preserving `already_running` instead of replacing it with a generic disconnected error.

Disconnect and logout close Telegram resources and invalidate previews, but deliberately retain the live backend's installation/database lock: cached writes still need a single owner. Quit the app/CLI to release that installation lock. Profile switches release the previous additional profile lock; switching back to the original profile does not reacquire its already-held root lock.

The recovery panel distinguishes another instance, missing backend, connecting, disconnected, authentication, interruption and cooldown. Retry makes one user-requested attempt, never an automatic restart loop. Diagnostics reads only the transport's owned child PID/state/request count and withheld-stderr byte count; it does not enumerate processes or expose logs/secrets.

## What is and is not established for the reported conflict

Controlled tests established dangerous old paths: implicit request-driven process spawning, dropping a child handle before waiting for its exit, and failure/EOF ordering that could hide the actual typed error. Those paths are fixed. Account-switch tests did not reproduce a double acquisition of the installation lock.

The exact process holding the user's installation at the time of the report is **not identified**. Safe `ps` inspection was denied by this execution sandbox. The reported error corresponds to a failed kernel lock acquisition; an existing lock file alone is not evidence of a live owner. A real CLI, another app build or an older orphan child remains possible. No unknown process was killed or session/database/lock file deleted.

From an ordinary Terminal session, you can inspect file users without printing process arguments:

```sh
lsof -nP "$HOME/Library/Application Support/TelegramGroupManager/manager.lock"
```

This lists processes with the file open; interpret their identity before taking any action. Quit the known owning application/CLI normally. If it is an old orphan, inspect that exact PID in Activity Monitor before ending only that verified process. Never kill every Python process. After the owner exits, choose Retry Connection. The new backend watches its own parent and should not leave the same orphan pattern after future app exits. This does not authorize automatic termination of an unknown old process.
