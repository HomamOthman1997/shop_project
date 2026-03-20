import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot_manager.py"

POLL_SECONDS = 1.0
RESTART_DEBOUNCE_SECONDS = 2.0
INCLUDE_SUFFIXES = {".py", ".json", ".env", ".toml", ".yml", ".yaml"}
EXCLUDE_DIRS = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def _iter_files(base: Path):
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            path = Path(root) / name
            if path.suffix.lower() in INCLUDE_SUFFIXES or name == ".env":
                yield path


def _snapshot() -> dict[str, int]:
    snap: dict[str, int] = {}
    for path in _iter_files(ROOT):
        try:
            snap[str(path)] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snap


def _changed_paths(old: dict[str, int], new: dict[str, int]) -> list[str]:
    changed = []
    all_keys = set(old.keys()) | set(new.keys())
    for key in all_keys:
        if old.get(key) != new.get(key):
            changed.append(key)
    changed.sort()
    return changed


def _start_bot() -> subprocess.Popen:
    print("[dev-hot-reload] starting bot_manager.py")
    return subprocess.Popen([sys.executable, str(TARGET)], cwd=str(ROOT))


def _stop_bot(proc: subprocess.Popen, timeout: float = 8.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
            proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    if not TARGET.exists():
        print(f"[dev-hot-reload] target not found: {TARGET}")
        return 1

    before = _snapshot()
    proc = _start_bot()
    print("[dev-hot-reload] watching for file changes...")
    pending_changes: set[str] = set()
    restart_due_at: float | None = None

    try:
        while True:
            time.sleep(POLL_SECONDS)
            now = _snapshot()
            changed = _changed_paths(before, now)
            if changed:
                pending_changes.update(changed)
                restart_due_at = time.time() + RESTART_DEBOUNCE_SECONDS
                before = now
            if restart_due_at is not None and time.time() >= restart_due_at:
                changed_list = sorted(pending_changes)
                sample = ", ".join(Path(p).name for p in changed_list[:5])
                more = f" (+{len(changed_list) - 5} more)" if len(changed_list) > 5 else ""
                print(f"[dev-hot-reload] batched change detected: {sample}{more}")
                _stop_bot(proc)
                proc = _start_bot()
                pending_changes.clear()
                restart_due_at = None
                before = _snapshot()
            elif proc.poll() is not None:
                # If bot exits unexpectedly, bring it back.
                print("[dev-hot-reload] bot exited, restarting...")
                proc = _start_bot()
                before = _snapshot()
    except KeyboardInterrupt:
        print("\n[dev-hot-reload] stopping...")
    finally:
        _stop_bot(proc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
