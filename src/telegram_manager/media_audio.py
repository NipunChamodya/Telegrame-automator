"""Optional bounded local Ogg/Opus decoding; never used for protected media."""

import asyncio
import os
from pathlib import Path


def converter():
    # Fixed locations, no shell or user-supplied command arguments.
    return next(
        (
            path
            for path in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
            if Path(path).is_file() and os.access(path, os.X_OK)
        ),
        None,
    )


async def decode_voice(source, stream):
    from .ipc import IPCError

    executable = converter()
    if executable is None:
        raise IPCError(
            "playback_unavailable",
            "Audio preview is unavailable on this Mac. Save the attachment to open it in another application.",
        )
    process = await asyncio.create_subprocess_exec(
        executable,
        "-nostdin",
        "-threads",
        "1",
        "-max_alloc",
        "67108864",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-f",
        "ogg",
        "-i",
        str(source),
        "-vn",
        "-t",
        "600",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        "pipe:1",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    total = 0
    try:
        async with asyncio.timeout(30):
            while chunk := await process.stdout.read(65536):
                total += len(chunk)
                if total > 64 * 1024 * 1024:
                    raise IPCError("file_size", "This audio preview is too large.")
                stream.write(chunk)
            if await process.wait() or total < 44:
                raise IPCError(
                    "playback_unavailable",
                    "This audio could not be decoded. Save it to use another application.",
                )
        return total
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
