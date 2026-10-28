"""Opt-in development tracebacks without exception text, source lines or locals."""
import json
import logging
import os
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def report_programming_error(logger: logging.Logger, exc: Exception) -> None:
    logger.error("ProgrammingError:%s", type(exc).__name__)
    if os.environ.get("TGM_DEV_MODE") != "1":
        return
    frames = []
    trusted_names: set[str] = set()
    cursor = exc.__traceback__
    while cursor is not None:
        code = cursor.tb_frame.f_code
        try:
            relative = Path(code.co_filename).resolve().relative_to(PACKAGE)
        except ValueError:
            pass  # Omit external absolute paths and user directory names.
        else:
            frames.append({"file": f"src/telegram_manager/{relative.as_posix()}",
                           "line": cursor.tb_lineno, "function": code.co_name})
            trusted_names.update(code.co_names)
        cursor = cursor.tb_next
    data = {"error": type(exc).__name__, "frames": frames}
    attribute = getattr(exc, "name", None) if isinstance(exc, AttributeError) else None
    if isinstance(attribute, str) and attribute in trusted_names and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", attribute):
        data["attribute"] = attribute
    logger.error("DevelopmentDiagnostic:%s", json.dumps(data, ensure_ascii=True))
