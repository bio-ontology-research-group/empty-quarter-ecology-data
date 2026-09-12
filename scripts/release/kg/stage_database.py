#!/usr/bin/env python3
"""Create a fresh, loopback-only KG release database without touching production."""
import argparse
import datetime as dt
import json
from pathlib import Path
import secrets
import subprocess

IMAGE = "openlink/virtuoso-opensource-7@sha256:0dbe1ab4fa0cb7bbafc1f6c0c2b0a5d6f22d918dbd17672f2ddb24580aa6756a"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--name", default="eq_kg_3_0_0")
    parser.add_argument("--port", type=int, default=18895)
    args = parser.parse_args()
    root = args.root.resolve()
    if root.parent != Path("/data/empty-quarter-releases"):
        parser.error("root must be a direct child of /data/empty-quarter-releases")
    if root.exists():
        parser.error("candidate directory already exists; inspect it rather than overwrite")
    names = run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
    if args.name in names:
        parser.error("candidate container already exists")
    root.mkdir(parents=True)
    for part in ("database", "inputs", "exports", "evidence", "scripts"):
        (root / part).mkdir()
    private = root / "database.private.env"
    private.touch(mode=0o600, exist_ok=False)
    private.write_text("DBA_PASSWORD=" + secrets.token_hex(32) + "\nSPARQL_UPDATE=false\n")
    command = [
        "docker", "run", "-d", "--name", args.name,
        "--label", "org.rubalkhali.kg.version=3.0.0",
        "--label", "org.rubalkhali.kg.role=release-candidate",
        "--memory", "128g", "--memory-swap", "128g", "--cpus", "12",
        "--restart", "unless-stopped", "--env-file", str(private),
        "-e", "VIRT_Parameters_NumberOfBuffers=8000000",
        "-e", "VIRT_Parameters_MaxDirtyBuffers=6000000",
        "-e", "VIRT_Parameters_MaxQueryMem=8G",
        "-e", "VIRT_Parameters_ThreadsPerQuery=8",
        "-e", "VIRT_Parameters_AsyncQueueMaxThreads=12",
        "-e", "VIRT_Parameters_TransactionAfterImageLimit=250000000",
        "-e", "VIRT_SPARQL_MaxConstructTriples=100000000",
        "-e", "VIRT_SPARQL_MaxMemInUse=17179869184",
        "-e", "VIRT_Flags_hash_join_enable=1",
        "-e", "VIRT_Parameters_DirsAllowed=., /database, /release-inputs, /release-exports",
        "-e", "VIRT_SPARQL_ResultSetMaxRows=1000000",
        "-e", "VIRT_SPARQL_MaxQueryExecutionTime=300",
        "-e", "VIRT_SPARQL_MaxQueryCostEstimationTime=60",
        "-e", "VIRT_HTTPServer_MaxClientConnections=30",
        "-e", "VIRT_HTTPServer_ServerThreads=20",
        "-p", f"127.0.0.1:{args.port}:8890",
        "-v", f"{root / 'database'}:/database",
        "-v", f"{root / 'inputs'}:/release-inputs:ro",
        "-v", f"{root / 'exports'}:/release-exports",
        IMAGE,
    ]
    container = run(*command)
    # The pinned official image runs virtuoso-t as 65532, not as root.
    run("docker", "exec", "-u", "0", args.name, "chown", "65532:65532", "/release-exports")
    evidence = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "kg_version": "3.0.0", "container": args.name,
        "container_id": container, "image": IMAGE, "root": str(root),
        "sparql_url": f"http://127.0.0.1:{args.port}/sparql",
        "public_updates_enabled": False, "query_time_inference_configured": False,
        "memory_limit_gib": 128, "cpu_limit": 12,
        "production_mutated": False,
    }
    (root / "evidence" / "stage_database.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
