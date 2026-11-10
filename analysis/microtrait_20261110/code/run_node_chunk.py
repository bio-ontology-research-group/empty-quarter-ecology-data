#!/usr/bin/env python3
"""Parallel node-packed runner for microTrait on a Shaheen compute node.

Splits a chunk of canonical MAG IDs across `N` concurrent worker processes on one node
(e.g. 32 workers x 4 HMMER threads = 128 threads on a 384-CPU node), exporting an
isolated project TMPDIR (never /tmp) BEFORE every R invocation.

When `--smoke-check` is passed (Stage 1 Smoke Test):
1. Runs the production wrapper (`run_microtrait_batch.R`) on the smoke genomes
   (bacterial + Thermoplasmatota archaeal + other archaeal).
2. Runs unmodified official `microtrait::extract.traits(in_file, out_dir, type="genomic",
   mode="meta", growthrate_predict=TRUE, optimalT_predict=TRUE,
   optimalT_predict_wtRNA=FALSE, save_tempfiles=TRUE)` on the smoke genomes and
   verifies EXACT parity across `norfs`, `genome_length`, `genes_detected`,
   `domains_detected`, `rules_asserted`, and `trait_counts_atgranularity1/2/3`.
3. Verifies `microtrait::make.genomeset.results()` across the smoke RDS files.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def run_worker(
    worker_id: int,
    mag_ids: list[str],
    root: Path,
    env_prefix: Path,
    hmm_threads: int,
    job_tag: str,
) -> dict[str, Any]:
    t0 = time.time()
    worker_tmp = root / "tmp" / f"{job_tag}_w{worker_id:02d}"
    worker_tmp.mkdir(parents=True, exist_ok=True)
    mag_list_file = worker_tmp / "worker_mags.txt"
    mag_list_file.write_text("\n".join(mag_ids) + "\n")

    log_file = root / "logs" / f"{job_tag}_w{worker_id:02d}.log"
    rscript_bin = env_prefix / "bin" / "Rscript"
    batch_r = root / "code" / "run_microtrait_batch.R"

    env = os.environ.copy()
    env["PATH"] = f"{env_prefix / 'bin'}:/project/k10018/sw/envs/gspa-tools/bin:" + env.get("PATH", "")
    env["TMPDIR"] = str(worker_tmp)
    env["TMP"] = str(worker_tmp)
    env["TEMP"] = str(worker_tmp)
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"

    cmd = [
        str(rscript_bin),
        "--vanilla",
        str(batch_r),
        str(mag_list_file),
        str(root),
        str(hmm_threads),
    ]
    with open(log_file, "wt") as lfh:
        res = subprocess.run(cmd, stdout=lfh, stderr=subprocess.STDOUT, env=env)

    for item in worker_tmp.iterdir():
        if item.name != "worker_mags.txt":
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except Exception:
                pass

    n_done = sum(1 for m in mag_ids if (root / "per_mag" / m / "DONE").exists())
    return {
        "worker_id": worker_id,
        "n_assigned": len(mag_ids),
        "n_done": n_done,
        "exit_code": res.returncode,
        "elapsed_seconds": round(time.time() - t0, 2),
        "log_file": str(log_file),
    }


def main() -> int:
    t0 = time.time()
    parser = argparse.ArgumentParser(description="Run node-packed microTrait chunk")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mag-list", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--hmm-threads", type=int, default=4)
    parser.add_argument("--job-tag", type=str, default="chunk")
    parser.add_argument("--smoke-check", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    env_prefix = root / "env" / "microtrait-r"
    mags = [x.strip() for x in args.mag_list.read_text().splitlines() if x.strip()]
    if not mags:
        raise ValueError(f"Empty MAG list in {args.mag_list}")

    pending_mags = [
        m
        for m in mags
        if not (
            (root / "per_mag" / m / "DONE").exists()
            and (root / "per_mag" / m / f"{m}.microtrait.rds").exists()
            and (root / "per_mag" / m / f"{m}.status.json").exists()
        )
    ]
    print(
        f"[{args.job_tag}] Total MAGs in list: {len(mags)}; pending: {len(pending_mags)}; "
        f"workers={args.workers}, hmm_threads={args.hmm_threads}",
        flush=True,
    )

    worker_results: list[dict[str, Any]] = []
    if pending_mags:
        n_workers = min(args.workers, len(pending_mags))
        worker_slices = [pending_mags[i::n_workers] for i in range(n_workers)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = [
                ex.submit(
                    run_worker,
                    w_idx,
                    w_mags,
                    root,
                    env_prefix,
                    args.hmm_threads,
                    args.job_tag,
                )
                for w_idx, w_mags in enumerate(worker_slices)
                if w_mags
            ]
            for fut in concurrent.futures.as_completed(futs):
                wr = fut.result()
                worker_results.append(wr)
                print(f"[{args.job_tag}] Worker {wr['worker_id']:02d} finished: {wr}", flush=True)

    missing_or_failed: list[str] = []
    statuses: list[dict[str, Any]] = []
    for m in mags:
        m_dir = root / "per_mag" / m
        st_file = m_dir / f"{m}.status.json"
        rds_file = m_dir / f"{m}.microtrait.rds"
        core_rds_file = m_dir / f"{m}.core.microtrait.rds"
        done_file = m_dir / "DONE"
        if not (st_file.exists() and rds_file.exists() and core_rds_file.exists() and done_file.exists()):
            missing_or_failed.append(m)
            continue
        st = json.loads(st_file.read_text())
        statuses.append(st)
        if not str(st.get("overall_status", "")).startswith("complete_"):
            missing_or_failed.append(m)

    if missing_or_failed:
        raise RuntimeError(
            f"[{args.job_tag}] {len(missing_or_failed)}/{len(mags)} MAGs failed or incomplete: {missing_or_failed[:10]}"
        )

    if args.smoke_check:
        print(
            f"[{args.job_tag}] Running direct parity check against official microtrait::extract.traits() "
            "and make.genomeset.results() on smoke genomes...",
            flush=True,
        )
        smoke_tmp = root / "tmp" / "smoke_official_parity"
        smoke_tmp.mkdir(parents=True, exist_ok=True)
        official_out_dir = root / "tmp" / "smoke_official_outputs"
        official_out_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["PATH"] = f"{env_prefix / 'bin'}:/project/k10018/sw/envs/gspa-tools/bin:" + env.get("PATH", "")
        env["TMPDIR"] = str(smoke_tmp)
        env["TMP"] = str(smoke_tmp)
        env["TEMP"] = str(smoke_tmp)

        r_code = f"""
        if (startsWith(tempdir(), "/tmp")) {{
          stop(paste0("FATAL: R tempdir() resolved to /tmp: ", tempdir()))
        }}
        suppressPackageStartupMessages({{
          library(microtrait)
          library(dplyr)
        }})
        mags <- readLines("{args.mag_list.resolve()}")
        mags <- mags[nzchar(trimws(mags))]
        rds_files <- file.path("{root}", "per_mag", mags, paste0(mags, ".microtrait.rds"))
        stopifnot(all(file.exists(rds_files)))

        # 1. Compare wrapper outputs against unmodified official microtrait::extract.traits
        # across bacterial and archaeal smoke genomes
        parity_rows <- list()
        for (m in mags) {{
          fa <- file.path("{root}", "inputs", "fastas", paste0(m, ".fa"))
          off_dir <- file.path("{official_out_dir}", m)
          dir.create(off_dir, recursive = TRUE, showWarnings = FALSE)
          off_res <- microtrait::extract.traits(
            in_file = fa,
            out_dir = off_dir,
            type = "genomic",
            mode = "meta",
            growthrate_predict = TRUE,
            optimalT_predict = TRUE,
            optimalT_predict_wtRNA = FALSE,
            save_tempfiles = TRUE
          )
          off_r <- off_res$microtrait_result
          wrap_r <- readRDS(file.path("{root}", "per_mag", m, paste0(m, ".microtrait.rds")))

          stopifnot(identical(as.integer(wrap_r$norfs), as.integer(off_r$norfs)))
          stopifnot(identical(as.numeric(wrap_r$genome_length), as.numeric(off_r$genome_length)))
          stopifnot(setequal(wrap_r$genes_detected, off_r$genes_detected))
          stopifnot(setequal(wrap_r$domains_detected, off_r$domains_detected))
          stopifnot(identical(
            wrap_r$rules_asserted[, c("microtrait_rule-name", "microtrait_rule-asserted")],
            off_r$rules_asserted[, c("microtrait_rule-name", "microtrait_rule-asserted")]
          ))
          stopifnot(identical(
            wrap_r$trait_counts_atgranularity1[, c("microtrait_trait-name", "microtrait_trait-value")],
            off_r$trait_counts_atgranularity1[, c("microtrait_trait-name", "microtrait_trait-value")]
          ))
          stopifnot(identical(
            wrap_r$trait_counts_atgranularity2[, c("microtrait_trait-name", "microtrait_trait-value")],
            off_r$trait_counts_atgranularity2[, c("microtrait_trait-name", "microtrait_trait-value")]
          ))
          stopifnot(identical(
            wrap_r$trait_counts_atgranularity3[, c("microtrait_trait-name", "microtrait_trait-value")],
            off_r$trait_counts_atgranularity3[, c("microtrait_trait-name", "microtrait_trait-value")]
          ))
          if (!is.null(off_r$ogt) && !is.na(off_r$ogt)) {{
            stopifnot(isTRUE(all.equal(as.numeric(wrap_r$ogt), as.numeric(off_r$ogt), tolerance = 1e-8)))
          }}
          if (!is.null(off_r$growthrate_d) && !is.na(off_r$growthrate_d)) {{
            stopifnot(isTRUE(all.equal(as.numeric(wrap_r$growthrate_d), as.numeric(off_r$growthrate_d), tolerance = 1e-8)))
          }}
          cat("PARITY_EXACT_MATCH:", m, "genes=", length(wrap_r$genes_detected), "domains=", length(wrap_r$domains_detected), "\\n")
        }}

        # 2. Verify official make.genomeset.results on smoke RDS files
        gs <- microtrait::make.genomeset.results(rds_files = rds_files, ids = mags, growthrate = TRUE, optimumT = TRUE, ncores = 2)
        for (nm in c("trait_matrixatgranularity1", "trait_matrixatgranularity2", "trait_matrixatgranularity3", "hmm_matrix", "rule_matrix")) {{
          mat <- gs[[nm]]
          stopifnot(!is.null(mat))
          stopifnot(nrow(mat) == length(mags))
          stopifnot(all(mags %in% mat$id))
        }}
        saveRDS(gs, file = file.path("{root}", "results", "smoke_genomeset_results.rds"))
        cat("SMOKE_GENOMESET_OK\\n")
        """
        res = subprocess.run(
            [str(env_prefix / "bin" / "Rscript"), "--vanilla", "-e", r_code],
            capture_output=True,
            text=True,
            env=env,
        )
        print(res.stdout, flush=True)
        if res.returncode != 0 or "SMOKE_GENOMESET_OK" not in res.stdout:
            raise RuntimeError(f"Smoke parity / make.genomeset.results check failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

        parity_lines = [line.strip() for line in res.stdout.splitlines() if line.startswith("PARITY_EXACT_MATCH:")]
        parity_report = {
            "stage": "stage1_smoke_official_parity",
            "status": "exact_match_all_smoke_mags",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "compared_fields": [
                "norfs",
                "genome_length",
                "genes_detected",
                "domains_detected",
                "rules_asserted",
                "trait_counts_atgranularity1",
                "trait_counts_atgranularity2",
                "trait_counts_atgranularity3",
                "growthrate_d",
                "ogt",
            ],
            "parity_matches": parity_lines,
        }
        (root / "results" / "smoke_official_extract_traits_parity.json").write_text(
            json.dumps(parity_report, indent=2) + "\n"
        )

        smoke_summary = {
            "stage": "stage1_smoke_test",
            "status": "completed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(time.time() - t0, 2),
            "n_smoke_mags": len(mags),
            "smoke_mags": mags,
            "official_extract_traits_parity": "exact_match_verified",
            "per_mag_statuses": statuses,
        }
        (root / "results" / "smoke_test_validation.json").write_text(json.dumps(smoke_summary, indent=2) + "\n")
        (root / "results" / "SMOKE_OK").touch()
        print(f"[{args.job_tag}] SMOKE_OK written.", flush=True)

    receipt = {
        "job_tag": args.job_tag,
        "status": "completed",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - t0, 2),
        "n_mags": len(mags),
        "workers": sorted(worker_results, key=lambda x: x["worker_id"]),
    }
    (root / "logs" / f"{args.job_tag}_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
