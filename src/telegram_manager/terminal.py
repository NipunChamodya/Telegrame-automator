"""Unicode-preserving, control-safe terminal rendering using the standard library."""
import json
import builtins
import re
import shutil
import sys
import unicodedata

ANSI = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]')
BIDI = set('\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')


class TerminalOutputError(BrokenPipeError):
    """The terminal/pipe failed, not Telegram's transport."""


def clean_text(value: str, *, multiline: bool = False) -> str:
    value = ANSI.sub('', value)
    return ''.join('�' if unicodedata.category(c) == 'Cs' else c for c in value
                   if c not in BIDI and (unicodedata.category(c) != 'Cc' or multiline and c in '\n\t'))


def json_text(value, *, indent: int | None = 2) -> str:
    # JSON already escapes C0 controls. Escape C1/bidi too, preserving the exact
    # preview as visible escapes rather than changing an outgoing message body.
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    return ''.join(f'\\u{ord(c):04x}' if c in BIDI or unicodedata.category(c) in {'Cc', 'Cs'} and c not in '\n\t'
                   else c for c in text)


def print(*values, sep: str = ' ', end: str = '\n', file=None, flush: bool = True) -> None:
    stream = sys.stdout if file is None else file
    text = clean_text(sep.join(str(v) for v in values) + end, multiline=True)
    encoding = getattr(stream, 'encoding', None) or 'utf-8'
    try:
        text = text.encode(encoding, errors='backslashreplace').decode(encoding)
    except LookupError:
        text = text.encode('ascii', errors='backslashreplace').decode('ascii')
    try:
        stream.write(text)
        if flush:
            stream.flush()
    except BrokenPipeError:
        raise TerminalOutputError('Terminal output is unavailable.') from None


def _clusters(value: str) -> list[str]:
    """Small conservative grapheme grouping without a heavy rendering dependency."""
    value = clean_text(value)
    clusters: list[str] = []
    for c in value:
        if clusters and (unicodedata.combining(c) or unicodedata.category(c) in {'Mn', 'Mc', 'Me'}
                         or c in {'\u200d', '\u200c'} or clusters[-1].endswith('\u200d')
                         or '\U0001f3fb' <= c <= '\U0001f3ff'
                         or '\U0001f1e6' <= c <= '\U0001f1ff' and len(clusters[-1]) == 1
                         and '\U0001f1e6' <= clusters[-1] <= '\U0001f1ff'):
            clusters[-1] += c
        else:
            clusters.append(c)
    return clusters


def _cluster_width(cluster: str) -> int:
    if any(ord(c) >= 0x1F000 for c in cluster) or '\ufe0f' in cluster or '\u20e3' in cluster:
        return 2
    return sum(2 if unicodedata.east_asian_width(c) in {'W', 'F'} else 1
               for c in cluster if unicodedata.category(c) not in {'Mn', 'Mc', 'Me', 'Cf'})


def display_width(value: str) -> int:
    return sum(_cluster_width(cluster) for cluster in _clusters(value))


def cell(value: str, width: int) -> str:
    """Pad/truncate complete clusters, counting Indic bases and joined emoji."""
    out, used = '', 0
    for cluster in _clusters(value):
        size = _cluster_width(cluster)
        if used + size > width:
            return out + ' ' * max(0, width - used)
        out += cluster
        used += size
    return out + ' ' * max(0, width - used)


def width() -> int:
    return max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)


def input(prompt: str = '') -> str:
    """Classify failures flushing input prompts as terminal I/O too."""
    prompt = clean_text(prompt, multiline=True)
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        prompt = prompt.encode(encoding, errors='backslashreplace').decode(encoding)
    except LookupError:
        prompt = prompt.encode('ascii', errors='backslashreplace').decode('ascii')
    try:
        return builtins.input(prompt)
    except BrokenPipeError:
        raise TerminalOutputError('Terminal prompt output is unavailable.') from None
