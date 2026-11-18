"""Keep an SSH forwarding session alive until its viewer process exits."""
from __future__ import annotations

import argparse
from pathlib import Path
import time


def process_start(pid):
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    if fields[0] in ("Z", "X"):
        return None
    return fields[19]


def wait_viewer_exit(pid):
    started = process_start(pid)
    if started is None:
        return
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, ProcessLookupError):
        return
    if not any(Path(part.decode()).name == "viewer.py" for part in command if part):
        raise ValueError("The supplied PID is not a viewer.py process")
    print(f"Forwarding is bound to viewer PID {pid}. Use the page exit button to finish.", flush=True)
    while process_start(pid) == started:
        time.sleep(0.25)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="Viewer PID printed at startup")
    args = parser.parse_args(argv)
    if args.pid <= 0:
        parser.error("--pid must be positive")
    try:
        wait_viewer_exit(args.pid)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
