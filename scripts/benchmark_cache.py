"""Offline SQLite page benchmark; temporary synthetic records, no Telegram access."""
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from telegram_manager.chat_store import ChatStore
from telegram_manager.storage import Store


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='tgm-cache-benchmark-') as directory:
        store = Store(Path(directory) / 'manager.sqlite3')
        cache = ChatStore(store)
        for destination in range(1, 1001):
            cache.save(1, {'id': destination, 'name': f'Community {destination} ශ්‍රී தமிழ் 👩🏽‍💻', 'kind': 'private'})
        durations = []
        tracemalloc.start()
        for _ in range(100):
            start = time.perf_counter()
            result = cache.page(1, page=3, size=50)
            durations.append((time.perf_counter() - start) * 1000)
            assert len(result['chats']) == 50 and result['total'] == 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        store.close()
        print(json.dumps({'synthetic_dialogs': 1000, 'page_size': 50, 'iterations': 100,
                          'median_ms': round(statistics.median(durations), 3),
                          'p95_ms': round(sorted(durations)[94], 3),
                          'python_traced_peak_bytes': peak, 'telegram_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
