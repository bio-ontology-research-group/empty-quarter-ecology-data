#!/usr/bin/env python3
"""Stage 0b: Offline HMM Database Deployment for Pinned microTrait (commit b4344eb).

Verifies and presses the official HMM databases from staged downloads:
- microtrait.hmmdb.gz (trusted cutoffs TC)
- dbCAN-HMMdb-V14.txt subsetted by commit b4344eb's `dbcan.selectids.txt` (41 GH models)
  into `dbcan.select.v14.hmmdb` (verifying every requested HMM identifier is present)
- arcbacribosomal.hmmdb.gz (ribosomal protein HMMs for gRodon)

Deploys pressed databases into the isolated microtrait R package `extdata/hmm/hmmpress/`
without any V8 symlink disguise, exports project TMPDIR before invoking Rscript, and writes
`provenance/database_assets_manifest.json` and `inputs/STAGE0B_DONE`.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(
    os.environ.get(
        "EQ_MICROTRAIT_ROOT",
        "/scratch/project/k10018/eq-microtrait-20261110",
    )
)

EXPECTED_DB_SHAS = {
    "microtrait.hmmdb.gz": "98d106ce0ad84c916c489ecb7b9f4576b4034a7cb4ab111d02c09a6df1ccd690",
    "arcbacribosomal.hmmdb.gz": "1efab5824ef004408be8eb76e63ea8abd7c6a594957c4484e5bceb56b0c4bff9",
    "dbCAN-HMMdb-V14.txt": "396c791fb13defab152864d8046687ef03b492937ec6f9bbab008bc77cbaa7a5",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def parse_hmm_models(hmm_path: Path) -> dict[str, Any]:
    """Return model names and TC count in an uncompressed HMMER3 file."""
    names: list[str] = []
    n_models = 0
    n_tc = 0
    with open(hmm_path, "rt", errors="replace") as fh:
        for line in fh:
            if line.startswith("HMMER3/f"):
                n_models += 1
            elif line.startswith("NAME"):
                names.append(line.split()[1].strip())
            elif line.startswith("TC "):
                n_tc += 1
    return {"n_models": n_models, "n_with_tc": n_tc, "names": names}


def deploy_hmm_databases(root: Path, env_prefix: Path) -> dict[str, Any]:
    dl_dir = root / "db" / "downloads"
    build_dir = root / "db" / "hmmpress"
    build_dir.mkdir(parents=True, exist_ok=True)

    r_tmp = root / "tmp" / "stage0b_r"
    r_tmp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TMPDIR"] = str(r_tmp)
    env["TMP"] = str(r_tmp)
    env["TEMP"] = str(r_tmp)

    env_bin = env_prefix / "bin"
    hmmfetch_bin = str(env_bin / "hmmfetch")
    hmmpress_bin = str(env_bin / "hmmpress")
    rscript_bin = str(env_bin / "Rscript")

    download_records: dict[str, Any] = {}
    for fname, exp_sha in EXPECTED_DB_SHAS.items():
        fpath = dl_dir / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Missing staged HMM database asset: {fpath}")
        actual_sha = sha256_file(fpath)
        if actual_sha != exp_sha:
            raise ValueError(f"SHA-256 mismatch for {fpath}: expected {exp_sha}, got {actual_sha}")
        download_records[fname] = {
            "path": str(fpath),
            "bytes": fpath.stat().st_size,
            "sha256": actual_sha,
        }

    res = subprocess.run(
        [
            rscript_bin,
            "--vanilla",
            "-e",
            'stopifnot(!startsWith(tempdir(), "/tmp")); cat(system.file("extdata", package="microtrait"))',
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    pkg_extdata = Path(res.stdout.strip())
    if not pkg_extdata.exists():
        raise RuntimeError(f"Could not locate microtrait extdata directory: '{pkg_extdata}'")

    selectids_file = pkg_extdata / "dbcan.selectids.txt"
    if not selectids_file.exists():
        raise FileNotFoundError(f"Missing dbcan.selectids.txt in {pkg_extdata}")
    select_ids = [x.strip() for x in selectids_file.read_text().splitlines() if x.strip()]

    pkg_hmmpress_dir = pkg_extdata / "hmm" / "hmmpress"
    pkg_hmmpress_dir.mkdir(parents=True, exist_ok=True)

    # Remove any old v8 files if present so there is zero V8/V14 ambiguity
    for old_f in list(build_dir.glob("dbcan.select.v8*")) + list(pkg_hmmpress_dir.glob("dbcan.select.v8*")):
        if old_f.exists() or old_f.is_symlink():
            old_f.unlink()

    # 1. Official dbCAN V14 subset
    dbcan_v14_hmmdb = build_dir / "dbcan.select.v14.hmmdb"
    with open(dbcan_v14_hmmdb, "wb") as out_fh:
        subprocess.run(
            [hmmfetch_bin, "-f", str(dl_dir / "dbCAN-HMMdb-V14.txt"), str(selectids_file)],
            stdout=out_fh,
            check=True,
            env=env,
        )
    subprocess.run([hmmpress_bin, "-f", str(dbcan_v14_hmmdb)], check=True, env=env)

    # 2. arcbacribosomal
    rib_hmmdb = build_dir / "arcbacribosomal.hmmdb"
    if not (build_dir / "arcbacribosomal.hmmdb.h3f").exists():
        with gzip.open(dl_dir / "arcbacribosomal.hmmdb.gz", "rb") as gz_in, open(rib_hmmdb, "wb") as out_fh:
            shutil.copyfileobj(gz_in, out_fh)
        subprocess.run([hmmpress_bin, "-f", str(rib_hmmdb)], check=True, env=env)

    # 3. microtrait
    mt_hmmdb = build_dir / "microtrait.hmmdb"
    if not (build_dir / "microtrait.hmmdb.h3f").exists():
        with gzip.open(dl_dir / "microtrait.hmmdb.gz", "rb") as gz_in, open(mt_hmmdb, "wb") as out_fh:
            shutil.copyfileobj(gz_in, out_fh)
        subprocess.run([hmmpress_bin, "-f", str(mt_hmmdb)], check=True, env=env)

    exts = ["", ".h3f", ".h3i", ".h3m", ".h3p"]
    pressed_records: dict[str, Any] = {}
    for base in ["dbcan.select.v14.hmmdb", "arcbacribosomal.hmmdb", "microtrait.hmmdb"]:
        for ext in exts:
            src = build_dir / f"{base}{ext}"
            dst = pkg_hmmpress_dir / f"{base}{ext}"
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            os.symlink(src, dst)
            pressed_records[f"{base}{ext}"] = {
                "path": str(src),
                "bytes": src.stat().st_size,
                "sha256": sha256_file(src),
            }

    mt_info = parse_hmm_models(mt_hmmdb)
    dbcan_info = parse_hmm_models(dbcan_v14_hmmdb)
    rib_info = parse_hmm_models(rib_hmmdb)

    # hmmfetch emits in database order; require equal sets, same count, and no duplicates
    if (
        set(dbcan_info["names"]) != set(select_ids)
        or len(dbcan_info["names"]) != len(select_ids)
        or len(dbcan_info["names"]) != len(set(dbcan_info["names"]))
    ):
        missing = set(select_ids) - set(dbcan_info["names"])
        raise RuntimeError(
            f"dbcan.select.v14.hmmdb model mismatch! Expected {len(select_ids)}, got {len(dbcan_info['names'])}, missing={missing}"
        )
    if mt_info["n_models"] != mt_info["n_with_tc"]:
        raise RuntimeError(f"Expected all microtrait HMMs to have TC cutoffs, got {mt_info['n_with_tc']}/{mt_info['n_models']}")

    return {
        "microtrait_git_commit": "b4344ebd4e0cdc6f7f37f10e25a947a839d61eaa",
        "grodon_git_commit": "0b7e32e667580e2890b56009de8af208c9029f8b",
        "microtrait_package_extdata": str(pkg_extdata),
        "hmmpress_dir": str(pkg_hmmpress_dir),
        "dbcan_version_used": "V14 (official pinned commit b4344eb dbCAN-HMMdb-V14.txt -> dbcan.select.v14.hmmdb)",
        "dbcan_selectids_count": len(select_ids),
        "dbcan_selectids_verified_models": dbcan_info["names"],
        "dbcan_selectids_sha256": sha256_file(selectids_file),
        "model_counts": {
            "microtrait.hmmdb": {"n_models": mt_info["n_models"], "n_with_tc": mt_info["n_with_tc"]},
            "dbcan.select.v14.hmmdb": {"n_models": dbcan_info["n_models"], "n_with_tc": dbcan_info["n_with_tc"]},
            "arcbacribosomal.hmmdb": {"n_models": rib_info["n_models"], "n_with_tc": rib_info["n_with_tc"]},
        },
        "downloads": download_records,
        "pressed_files": pressed_records,
    }


def main() -> int:
    t0 = time.time()
    parser = argparse.ArgumentParser(description="Stage 0b: Deploy & verify official HMM databases (dbCAN V14)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--env-prefix", type=Path, default=DEFAULT_ROOT / "env" / "microtrait-r")
    args = parser.parse_args()

    root = args.root.resolve()
    prov_dir = root / "provenance"
    in_dir = root / "inputs"
    prov_dir.mkdir(parents=True, exist_ok=True)
    in_dir.mkdir(parents=True, exist_ok=True)

    print("[Stage 0b] Deploying & verifying official HMM databases (microtrait, dbCAN V14, arcbacribosomal)...", flush=True)
    db_manifest = deploy_hmm_databases(root, args.env_prefix.resolve())
    db_manifest["elapsed_seconds"] = round(time.time() - t0, 2)
    db_manifest["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (prov_dir / "database_assets_manifest.json").write_text(json.dumps(db_manifest, indent=2) + "\n")
    (in_dir / "STAGE0B_DONE").touch()
    print("[Stage 0b] Completed:", json.dumps(db_manifest["model_counts"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
