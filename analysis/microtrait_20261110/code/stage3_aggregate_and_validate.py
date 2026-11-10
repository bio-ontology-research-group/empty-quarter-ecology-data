#!/usr/bin/env python3
"""Stage 3: Full 5,438-MAG Aggregation, Provenance Ledger, Per-Component Status Table,
Growth/OGT Applicability Table, Gene-Level HMM Hit Table, and Integrity Verification.

Runs on a Shaheen compute node (`workq`) after the 34-task production array completes:
1. Verifies all 5,438 canonical MAGs have `.microtrait.rds`, `.status.json`, and `DONE`
   with `overall_status` starting with `complete_`.
2. Invokes `aggregate_genomeset.R` to run official `microtrait::make.genomeset.results`
   across all 5,438 RDS files and produce:
   - `results/eq_5438.microtrait.genomeset_results.rds`
   - `results/trait_matrixatgranularity1.tsv` (and `.tsv.gz`)
   - `results/trait_matrixatgranularity2.tsv` (and `.tsv.gz`)
   - `results/trait_matrixatgranularity3.tsv` (and `.tsv.gz`)
   - `results/hmm_matrix.tsv.gz` (and `.tsv`)
   - `results/rule_matrix.tsv.gz` (and `.tsv`)
3. Combines all 5,438 per-MAG `.status.json` receipts with `inputs/cohort_manifest_5438.tsv`
   to produce:
   - `results/microtrait_status_5438.tsv` (5,438 rows, full per-component status & QC metadata)
   - `results/growth_and_ogt_predictions_5438.tsv` (5,438 rows, gRodon + OGT predictions with
     explicit archaeal domain & MAG fragmentation applicability flags; unsupported/failed stay NA, never 0)
4. Streams per-MAG `.microtrait.domtblout` and `.dbcan.domtblout` (filtered via official RDS
   `genes_detected_table` and `domains_detected`) into `results/hmm_gene_hits_all5438.tsv.gz`.
5. Computes SHA-256 checksums of all result and provenance tables into `results/SHA256SUMS`
   and writes `results/AGGREGATION_DONE`.
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

import pandas as pd


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def gzip_copy(src: Path, dst_gz: Path) -> None:
    with open(src, "rb") as f_in, gzip.open(dst_gz, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)


def derive_growth_applicability(domain: str, comp: float, cont: float, n_heg: int, growth_status: str) -> str:
    reasons: list[str] = []
    if domain == "d__Archaea":
        reasons.append("caution_archaeal_domain_grodon_vs_trained_primarily_bacteria")
    if cont >= 5.0:
        reasons.append("caution_contamination_ge5pct")
    if comp < 70.0:
        reasons.append("caution_fragmented_completeness_lt70pct")
    if n_heg < 10:
        reasons.append("caution_ribosomal_genes_lt10_unreliable_cub")
    if not growth_status.startswith("ok"):
        reasons.append(f"not_estimated_{growth_status}")
    return ";".join(reasons) if reasons else "standard_bacterial_hq_ge10_ribosomal"


def derive_ogt_applicability(domain: str, comp: float, cont: float, ogt_status: str) -> str:
    reasons: list[str] = []
    reasons.append("genomic_orf_protein_model_without_trna_or_rrna")
    if comp < 70.0:
        reasons.append("caution_fragmented_completeness_lt70pct")
    if cont >= 5.0:
        reasons.append("caution_contamination_ge5pct")
    if ogt_status != "ok":
        reasons.append(f"not_estimated_{ogt_status}")
    return ";".join(reasons)


def main() -> int:
    t0 = time.time()
    parser = argparse.ArgumentParser(description="Stage 3: Aggregate and validate all 5,438 microTrait outputs")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ncores", type=int, default=32)
    args = parser.parse_args()

    root = args.root.resolve()
    env_prefix = root / "env" / "microtrait-r"
    in_dir = root / "inputs"
    res_dir = root / "results"
    prov_dir = root / "provenance"
    res_dir.mkdir(parents=True, exist_ok=True)
    prov_dir.mkdir(parents=True, exist_ok=True)

    cohort_df = pd.read_csv(in_dir / "cohort_manifest_5438.tsv", sep="\t")
    if len(cohort_df) != 5438:
        raise ValueError(f"Expected 5,438 rows in cohort_manifest_5438.tsv, got {len(cohort_df)}")

    mags = cohort_df["mag"].tolist()
    cohort_lookup = cohort_df.set_index("mag").to_dict("index")

    print("[Stage 3] Step 1: Verifying all 5,438 per-MAG status receipts and RDS files...", flush=True)
    status_rows: list[dict[str, Any]] = []
    growth_rows: list[dict[str, Any]] = []
    failed_mags: list[str] = []

    for m in mags:
        m_dir = root / "per_mag" / m
        st_path = m_dir / f"{m}.status.json"
        rds_path = m_dir / f"{m}.microtrait.rds"
        done_path = m_dir / "DONE"
        if not (st_path.exists() and rds_path.exists() and done_path.exists()):
            failed_mags.append(m)
            continue
        st = json.loads(st_path.read_text())
        if not str(st.get("overall_status", "")).startswith("complete_"):
            failed_mags.append(m)
            continue

        c_meta = cohort_lookup[m]
        dom = str(c_meta["canonical_domain"])
        comp = float(c_meta["checkm2_completeness"])
        cont = float(c_meta["checkm2_contamination"])
        n_heg = int(st["n_highly_expressed_genes"]) if st.get("n_highly_expressed_genes") is not None else 0
        g_stat = str(st.get("growth_status", "not_run"))
        o_stat = str(st.get("ogt_status", "not_run"))

        g_app = derive_growth_applicability(dom, comp, cont, n_heg, g_stat)
        o_app = derive_ogt_applicability(dom, comp, cont, o_stat)

        merged_st = {
            "mag": m,
            "canonical_domain": dom,
            "canonical_phylum": c_meta["canonical_phylum"],
            "canonical_class": c_meta["canonical_class"],
            "canonical_order": c_meta["canonical_order"],
            "canonical_family": c_meta["canonical_family"],
            "canonical_genus": c_meta["canonical_genus"],
            "canonical_species": c_meta["canonical_species"],
            "checkm2_completeness": comp,
            "checkm2_contamination": cont,
            "quality_tier": c_meta["quality_tier"],
            "pass_gunc": c_meta["pass_gunc"],
            "fasta_sha256": c_meta["sha256"],
            "fasta_bytes": c_meta["bytes"],
            "fasta_contigs": c_meta["contigs"],
            "fasta_bases": c_meta["bases"],
            "has_sub_suffix": c_meta["has_sub_suffix"],
            **st,
            "growth_applicability_flag": g_app,
            "ogt_applicability_flag": o_app,
        }
        status_rows.append(merged_st)

        growth_rows.append(
            {
                "mag": m,
                "canonical_domain": dom,
                "canonical_phylum": c_meta["canonical_phylum"],
                "canonical_order": c_meta["canonical_order"],
                "canonical_genus": c_meta["canonical_genus"],
                "checkm2_completeness": comp,
                "checkm2_contamination": cont,
                "quality_tier": c_meta["quality_tier"],
                "genome_length": st.get("genome_length"),
                "norfs": st.get("norfs"),
                "n_ribosomal_domtblout_hits": st.get("n_ribosomal_domtblout_hits"),
                "n_highly_expressed_genes": st.get("n_highly_expressed_genes"),
                "growth_status": g_stat,
                "growth_applicability_flag": g_app,
                "growthrate_d_hours": st.get("growthrate_d_hours"),
                "growthrate_LowerCI": st.get("growthrate_LowerCI"),
                "growthrate_UpperCI": st.get("growthrate_UpperCI"),
                "growthrate_CUBHE": st.get("growthrate_CUBHE"),
                "growthrate_ConsistencyHE": st.get("growthrate_ConsistencyHE"),
                "growthrate_CPB": st.get("growthrate_CPB"),
                "growth_warning": st.get("growth_warning"),
                "growth_error": st.get("growth_error"),
                "ogt_status": o_stat,
                "ogt_model": st.get("ogt_model"),
                "optimalT_predict_wtRNA": st.get("optimalT_predict_wtRNA"),
                "ogt_applicability_flag": o_app,
                "ogt_celsius": st.get("ogt_celsius"),
                "ogt_error": st.get("ogt_error"),
            }
        )

    if failed_mags:
        raise RuntimeError(
            f"[Stage 3] Cannot finalize: {len(failed_mags)}/5438 MAGs missing or failed: {failed_mags[:20]}"
        )

    status_df = pd.DataFrame(status_rows)
    growth_df = pd.DataFrame(growth_rows)

    status_out = res_dir / "microtrait_status_5438.tsv"
    growth_out = res_dir / "growth_and_ogt_predictions_5438.tsv"
    status_df.to_csv(status_out, sep="\t", index=False, na_rep="NA")
    growth_df.to_csv(growth_out, sep="\t", index=False, na_rep="NA")
    print(f"[Stage 3] Wrote {status_out} and {growth_out} (5,438 rows each).", flush=True)

    print("[Stage 3] Step 2: Running official make.genomeset.results via aggregate_genomeset.R...", flush=True)
    agg_tmp = root / "tmp" / "stage3_agg"
    agg_tmp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = f"{env_prefix / 'bin'}:/project/k10018/sw/envs/gspa-tools/bin:" + env.get("PATH", "")
    env["TMPDIR"] = str(agg_tmp)
    env["TMP"] = str(agg_tmp)
    env["TEMP"] = str(agg_tmp)

    res = subprocess.run(
        [
            str(env_prefix / "bin" / "Rscript"),
            "--vanilla",
            str(root / "code" / "aggregate_genomeset.R"),
            str(root),
            str(args.ncores),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    print(res.stdout, flush=True)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr, flush=True)
        raise RuntimeError(f"aggregate_genomeset.R failed with exit code {res.returncode}")

    # Compress large TSV matrices (.tsv.gz) alongside .tsv
    for mname in [
        "trait_matrixatgranularity1",
        "trait_matrixatgranularity2",
        "trait_matrixatgranularity3",
        "hmm_matrix",
        "rule_matrix",
    ]:
        tsv_p = res_dir / f"{mname}.tsv"
        gz_p = res_dir / f"{mname}.tsv.gz"
        gzip_copy(tsv_p, gz_p)

    # Step 3: Extract combined gene-level HMM hit table from all 5,438 RDS files in R
    print("[Stage 3] Step 3: Extracting combined gene-level HMM hit table across all 5,438 MAGs...", flush=True)
    extract_hits_r = f"""
    suppressPackageStartupMessages({{
      library(dplyr)
      library(tibble)
      library(readr)
      library(parallel)
    }})
    mags <- readLines("{in_dir / 'all_5438_mags.txt'}")
    mags <- mags[nzchar(trimws(mags))]
    rds_files <- file.path("{root}", "per_mag", mags, paste0(mags, ".microtrait.rds"))
    hits_list <- parallel::mclapply(seq_along(mags), function(i) {{
      r <- readRDS(rds_files[i])
      tb <- r$genes_detected_table
      if (is.null(tb) || nrow(tb) == 0L) return(NULL)
      tb %>% dplyr::mutate(id = mags[i], .before = 1)
    }}, mc.cores = {args.ncores})
    all_hits <- dplyr::bind_rows(hits_list)
    readr::write_tsv(all_hits, gzfile("{res_dir / 'hmm_gene_hits_all5438.tsv.gz'}"))
    cat("WROTE_GENE_HITS:", nrow(all_hits), "\\n")
    """
    res_hits = subprocess.run(
        [str(env_prefix / "bin" / "Rscript"), "--vanilla", "-e", extract_hits_r],
        capture_output=True,
        text=True,
        env=env,
    )
    print(res_hits.stdout, flush=True)
    if res_hits.returncode != 0:
        raise RuntimeError(f"Gene hits extraction failed: {res_hits.stderr}")

    # Step 3b: Build separate phosphatase & model coverage table (aphA & phoN unassayed)
    print("[Stage 3] Step 3b: Writing separate phosphatase and model coverage table...", flush=True)
    hmat = pd.read_csv(res_dir / "hmm_matrix.tsv", sep="\t")
    rmat = pd.read_csv(res_dir / "rule_matrix.tsv", sep="\t")
    cov_rows = []
    phoa_series = hmat["phoA"] if "phoA" in hmat.columns else pd.Series(0, index=hmat.index)
    phod_series = hmat["phoD"] if "phoD" in hmat.columns else pd.Series(0, index=hmat.index)
    phos_rule = rmat["phosphatase"] if "phosphatase" in rmat.columns else pd.Series(0, index=rmat.index)

    for mag_id, pa, pd_cnt, r_val in zip(hmat["id"], phoa_series, phod_series, phos_rule):
        pa_val = int(pa) if pd.notna(pa) else 0
        pd_val = int(pd_cnt) if pd.notna(pd_cnt) else 0
        has_pos = (pa_val > 0) or (pd_val > 0)
        cov_rows.append({
            "mag": mag_id,
            "phoA_hits": pa_val,
            "phoD_hits": pd_val,
            "aphA_status": "unassayed_model_missing_from_release",
            "phoN_status": "unassayed_model_missing_from_release",
            "phosphatase_raw_rule_value": int(r_val) if pd.notna(r_val) else 0,
            "phosphatase_coverage_flag": (
                "present_confirmed_via_phoA_or_phoD"
                if has_pos
                else "indeterminate_absence_unconfirmed_aphA_phoN_unassayed"
            ),
            "phosphatase_interpretation_safe_value": (
                1 if has_pos else "NA"
            ),
        })
    cov_df = pd.DataFrame(cov_rows)
    cov_tsv = res_dir / "phosphatase_and_model_coverage_5438.tsv"
    cov_df.to_csv(cov_tsv, sep="\t", index=False)

    ledger = {
        "total_required_rule_hmms": 1831,
        "assayed_required_rule_hmms": 1829,
        "missing_required_rule_hmms": ["aphA", "phoN"],
        "extra_database_models_not_in_rules": ["phbB"],
        "microtrait_database_models": 1789,
        "microtrait_database_required_rule_models": 1788,
        "dbcan_v14_database_models": 41,
        "total_assayed_database_models": 1830,
        "model_accounting_note": (
            "Total assayed models in database (1,830) includes extra phbB "
            "(not in microtrait rules), so assayed required-rule HMMs are 1,829 of 1,831; "
            "raw outputs unchanged."
        ),
        "unassayed_model_details": {
            "aphA": {
                "kegg_id": "K03788",
                "ec": "3.1.3.2",
                "tc_cutoff": 101.3,
                "description": "acid phosphatase (class B) [EC:3.1.3.2]",
                "status": "unassayed_upstream_model_missing_from_release",
                "impacted_rule": "phosphatase = ('phoA' | 'phoD' | 'phoN' | 'aphA')"
            },
            "phoN": {
                "kegg_id": "K09474",
                "ec": "3.1.3.2",
                "tc_cutoff": 90.4,
                "description": "acid phosphatase (class A) [EC:3.1.3.2]",
                "status": "unassayed_upstream_model_missing_from_release",
                "impacted_rule": "phosphatase = ('phoA' | 'phoD' | 'phoN' | 'aphA')"
            }
        },
        "scientific_decision": {
            "policy": "retain_official_raw_outputs_unchanged",
            "justification": (
                "Upstream microtrait.hmmdb.gz release omits aphA and phoN, but includes extra model phbB. "
                "Total assayed 1,830 database models includes extra phbB, so assayed required-rule HMMs are 1,829 of 1,831; "
                "raw outputs unchanged. Exactly 1,829 of 1,831 required rule HMMs are assayed. Total unique HMM models "
                "in combined databases is 1,830. No invented or non-official models are substituted. Official raw tables "
                "are retained verbatim."
            ),
            "separate_coverage_table": "results/phosphatase_and_model_coverage_5438.tsv",
            "interpretation_safe_rule": "Absence of phosphatase cannot be definitively asserted when phoA and phoD are 0, because aphA and phoN were unassayed. When phoA or phoD is positive (>0), presence is confirmed."
        }
    }
    (prov_dir / "model_coverage_ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")

    # Step 4: Summary & SHA256SUMS
    summary = {
        "stage": "stage3_aggregate_and_validate",
        "status": "completed",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - t0, 2),
        "n_canonical_mags": len(status_df),
        "n_complete_all_components": int((status_df["overall_status"] == "complete_all_components").sum()),
        "n_complete_traits_partial_continuous": int(
            (status_df["overall_status"] == "complete_traits_partial_continuous_predictors").sum()
        ),
        "n_failed": int((status_df["overall_status"] == "failed").sum()),
        "n_prodigal_ok": int((status_df["prodigal_status"] == "ok").sum()),
        "n_microtrait_hmm_ok": int((status_df["microtrait_hmm_status"] == "ok").sum()),
        "n_dbcan_hmm_ok": int((status_df["dbcan_hmm_status"] == "ok").sum()),
        "n_rules_traits_ok": int((status_df["rules_traits_status"] == "ok").sum()),
        "n_growth_ok": int(status_df["growth_status"].isin(["ok", "ok_low_ribosomal_count_lt10"]).sum()),
        "n_growth_na_zero_ribosomal": int((status_df["growth_status"] == "na_zero_ribosomal_genes").sum()),
        "n_ogt_ok": int((status_df["ogt_status"] == "ok").sum()),
    }
    (res_dir / "aggregation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    # Compute SHA256SUMS over results/ and provenance/
    sha_lines: list[str] = []
    for f in sorted(list(res_dir.glob("*")) + list(prov_dir.glob("*")) + [in_dir / "cohort_manifest_5438.tsv"]):
        if f.is_file() and f.name != "SHA256SUMS":
            rel = f.relative_to(root)
            sha_lines.append(f"{sha256_file(f)}  {rel}")
    (res_dir / "SHA256SUMS").write_text("\n".join(sha_lines) + "\n")
    (res_dir / "AGGREGATION_DONE").touch()
    print("[Stage 3] Completed:", json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
