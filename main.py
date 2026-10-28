"""Launch from a checkout without installing into the system interpreter."""
import sys
from pathlib import Path

if sys.version_info < (3, 13):
    print("Python 3.13 or newer is required. Launch with python3.13 main.py.", file=sys.stderr)
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from telegram_manager.bootstrap import main

    main()
