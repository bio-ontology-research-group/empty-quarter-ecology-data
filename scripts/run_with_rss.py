#!/usr/bin/env python3
"""Run a subprocess and poll its peak RSS via /proc.

Usage: run_with_rss.py CMD [ARG ...]

Streams the child's stdout/stderr through unchanged, then prints a
final '[RSS] peak_kb=...' line so a parent script can grep it out.
"""
import os
import subprocess
import sys
import threading
import time


def poll_rss(pid, peak, stop):
    path = f"/proc/{pid}/status"
    while not stop.is_set():
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        if kb > peak[0]:
                            peak[0] = kb
                        break
                    if line.startswith("VmHWM:"):
                        kb = int(line.split()[1])
                        if kb > peak[0]:
                            peak[0] = kb
                        break
        except (FileNotFoundError, ProcessLookupError):
            return
        time.sleep(0.5)


def main():
    if len(sys.argv) < 2:
        print("usage: run_with_rss.py CMD [ARG ...]", file=sys.stderr)
        sys.exit(2)
    t0 = time.perf_counter()
    proc = subprocess.Popen(sys.argv[1:])
    peak = [0]
    stop = threading.Event()
    th = threading.Thread(target=poll_rss, args=(proc.pid, peak, stop), daemon=True)
    th.start()
    rc = proc.wait()
    stop.set()
    th.join(timeout=2)
    # Final read of VmHWM (peak resident set size).
    try:
        with open(f"/proc/{proc.pid}/status") as f:
            pass  # process is gone, nothing to read
    except Exception:
        pass
    dt = time.perf_counter() - t0
    print(f"[RSS] wall_seconds={dt:.2f}")
    print(f"[RSS] peak_kb={peak[0]}")
    print(f"[RSS] peak_mb={peak[0] / 1024:.1f}")
    print(f"[RSS] exit_code={rc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
