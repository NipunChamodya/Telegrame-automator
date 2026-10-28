"""Dependency setup must run before importing Telethon-dependent modules."""
import importlib.metadata
import importlib.util
import os
import platform
import re
import subprocess
import sys
import tomllib
import venv
from pathlib import Path
from .terminal import print, input

PROJECT = Path(__file__).resolve().parents[2]


def missing_dependencies(project: Path = PROJECT) -> list[str]:
    with (project / "pyproject.toml").open("rb") as stream:
        requirements = tomllib.load(stream)["project"]["dependencies"]
    missing = []
    for requirement in requirements:
        match = re.fullmatch(r"([\w-]+)((?:(?:>=|<=|==|<|>)\d+(?:\.\d+)*(?:,)?)+)", requirement)
        if not match:
            raise ValueError("Unsupported dependency declaration; review pyproject.toml.")
        name, constraints = match.groups()
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement)
            continue
        if not re.fullmatch(r"\d+(?:\.\d+)*", installed):
            missing.append(requirement)
            continue
        version = tuple(int(n) for n in installed.split("."))
        for operator, value in re.findall(r"(>=|<=|==|<|>)(\d+(?:\.\d+)*)", constraints):
            required = tuple(int(n) for n in value.split("."))
            length = max(len(version), len(required))
            actual = version + (0,) * (length - len(version))
            target = required + (0,) * (length - len(required))
            valid = {">=": actual >= target, "<=": actual <= target, "==": actual == target,
                     "<": actual < target, ">": actual > target}[operator]
            if not valid:
                missing.append(requirement)
                break
    if "Telethon" not in " ".join(missing) and importlib.util.find_spec("telethon") is None:
        missing.append("Telethon (import unavailable)")
    return missing


def venv_ready(interpreter: Path) -> bool:
    probe = ("import sys; assert sys.version_info >= (3,13); "
             f"sys.path.insert(0, {str(PROJECT / 'src')!r}); "
             "from telegram_manager.bootstrap import missing_dependencies; "
             "assert not missing_dependencies(); import telethon")
    result = subprocess.run([str(interpreter), "-c", probe], capture_output=True, timeout=30)
    return result.returncode == 0


def ensure_dependencies() -> bool:
    missing = missing_dependencies()
    if not missing:
        return True
    environment = PROJECT / ".venv"
    interpreter = environment / "bin" / "python"
    if environment.is_symlink():
        raise ValueError("Project .venv must not be a symlink.")
    if interpreter.exists() and venv_ready(interpreter):
        os.execv(str(interpreter), [str(interpreter), str(PROJECT / "main.py")])
        return False
    print("Missing or incompatible dependencies: " + ", ".join(missing))
    print("Setup will create/reuse the project .venv and install only this project's runtime dependencies.")
    print("System Python will not be modified. Network access is required.")
    if not sys.stdin.isatty() or input("Approve virtual environment setup? [y/N]: ").strip().lower() != "y":
        print("Setup cancelled. No packages installed.")
        return False
    if not (environment / "pyvenv.cfg").is_file():
        if environment.exists():
            raise ValueError("Existing .venv is not a virtual environment; it was left untouched.")
        venv.EnvBuilder(with_pip=True).create(environment)
    if not interpreter.exists():
        raise ValueError("Existing .venv has no interpreter; repair it manually. No files were removed.")
    check = subprocess.run([str(interpreter), "-c",
                            "import sys; assert sys.version_info >= (3,13); assert sys.prefix != sys.base_prefix"],
                           capture_output=True, timeout=30)
    if check.returncode:
        raise ValueError("Project .venv must use Python 3.13+ and be an isolated virtual environment.")
    result = subprocess.run([str(interpreter), "-m", "pip", "install", "--disable-pip-version-check",
                             "--no-input", "-e", str(PROJECT)])
    if result.returncode or not venv_ready(interpreter):
        print("Dependency setup failed. Check the pip output, network, disk space and .venv permissions.")
        print("Your configuration, database and Telegram session were not reset. Rerun python3 main.py.")
        return False
    os.execv(str(interpreter), [str(interpreter), str(PROJECT / "main.py")])
    return False


def main() -> None:
    try:
        if platform.system() not in {"Darwin", "Linux"}:
            raise ValueError("This application supports macOS; Linux can use environment credentials.")
        if sys.version_info < (3, 13):
            raise ValueError("Python 3.13 or newer is required.")
        if not ensure_dependencies():
            raise SystemExit(1)
        print(f"Telegram Group Manager — {platform.system()} / Python {platform.python_version()}")
        from .application import main as launch
        launch()
    except ImportError:
        print("A runtime dependency could not be imported. Repair the project .venv using the declared "
              "dependencies; existing application data was preserved.", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Startup failed ({type(exc).__name__}). Check Python, project permissions and dependency setup.",
              file=sys.stderr)
        raise SystemExit(1) from None
    except (KeyboardInterrupt, EOFError):
        print("Startup cancelled. Existing application data was preserved.")
        raise SystemExit(130) from None
