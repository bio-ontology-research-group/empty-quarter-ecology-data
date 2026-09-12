#!/usr/bin/env python3
"""Execute audited SQL in an explicitly named release database, never default production."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time


def execute(container, sql, timeout=7200):
    if not re.fullmatch(r"eq_kg_[0-9]+_[0-9]+_[0-9]+(?:_[a-z0-9]+)?", container):
        raise ValueError("an explicit KG release container name is required")
    result = subprocess.run(
        ["docker", "exec", "-i", container, "sh", "-c",
         'if command -v isql-v >/dev/null 2>&1; then exec isql-v localhost:1111 dba "$DBA_PASSWORD" VERBOSE=OFF PROMPT=OFF; else exec isql localhost:1111 dba "$DBA_PASSWORD" VERBOSE=OFF PROMPT=OFF; fi'],
        input=sql, text=True, capture_output=True, timeout=timeout,
    )
    output = result.stdout + result.stderr
    failed = result.returncode != 0 or bool(re.search(r"(?m)^\*\*\* (?:Error|Error:)", output))
    return output, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--sql", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    if args.log.exists():
        parser.error("refusing to overwrite an earlier execution log")
    started = time.time()
    output, failed = execute(args.container, args.sql.read_text(), args.timeout)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(output)
    print(json.dumps({"container": args.container, "sql": str(args.sql),
                      "log": str(args.log), "elapsed_seconds": time.time() - started,
                      "passed": not failed}))
    if failed:
        print(output[-6000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
