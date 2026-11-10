#!/usr/bin/env python3
"""Stage 0a: Independent Canonical 5,438-MAG One-Pass Extraction, Verification,
and Cohort Ledger Generation.

Runs on a Shaheen compute node (`workq`, never on login node), completely independent
of R environment or HMM database preparation.
1. Streams `/project/k10018/empty-quarter/data/mobilome/tars/refined_bins_all.tar` in ONE
   sequential pass to extract and verify all 5,438 canonical EQ species-representative MAGs
   (including 591 Archaea / 237 Thermoplasmatota and 4,847 Bacteria) against `genome_manifest.tsv`
   (exact SHA-256, byte count, contig count, base count). Never strips `_sub` or guesses aliases.
2. Joins with canonical taxonomy (`taxonomy_reconciliation_all5438.tsv.gz`), CheckM2 quality,
   and GUNC metadata to write `inputs/cohort_manifest_5438.tsv`.
3. Generates deterministic smoke test list (`inputs/smoke_mags.txt`, 6 representative MAGs
   spanning Bacteria, Thermoplasmatota Archaea, and other Archaea) and 34 array chunk lists
   (`inputs/chunks/chunk_00.txt` .. `inputs/chunks/chunk_33.txt`) covering all 5,438 MAGs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_ROOT = Path(
    os.environ.get(
        "EQ_MICROTRAIT_ROOT",
        "/scratch/project/k10018/eq-microtrait-20261110",
    )
)
P_REFINED_TAR = Path("/project/k10018/empty-quarter/data/mobilome/tars/refined_bins_all.tar")
P_TAX_5438 = Path(
    "/scratch/project/k10018/eq-science-20261109-canonical-taxonomy/results/taxonomy_reconciliation_all5438.tsv.gz"
)
P_GUNC = Path("/scratch/project/k10018/eq-archaeal-function-20261106/inputs/c3_gunc_per_genome.tsv")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def count_contigs_and_bases(raw_bytes: bytes) -> tuple[int, int]:
    n_contigs = 0
    n_bases = 0
    for line in raw_bytes.splitlines():
        if line.startswith(b">"):
            n_contigs += 1
        else:
            n_bases += len(line.strip())
    return n_contigs, n_bases


def assign_mimag_tier(comp: float, cont: float) -> str:
    if comp > 90.0 and cont < 5.0:
        return "HQ_candidate_gt90_lt5"
    if comp >= 50.0 and cont < 10.0:
        return "MQ_ge50_lt10"
    return "LQ_lt50_or_ge10"


def main() -> int:
    t0 = time.time()
    parser = argparse.ArgumentParser(description="Stage 0a: Canonical 5,438 MAG extraction & verification")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--n-chunks", type=int, default=34, help="Number of Slurm array chunks for 5,438 MAGs")
    args = parser.parse_args()

    root = args.root.resolve()
    in_dir = root / "inputs"
    fastas_dir = in_dir / "fastas"
    chunks_dir = in_dir / "chunks"
    prov_dir = root / "provenance"
    for d in (in_dir, fastas_dir, chunks_dir, prov_dir, root / "results", root / "per_mag", root / "logs", root / "tmp"):
        d.mkdir(parents=True, exist_ok=True)

    print("[Stage 0a] Loading canonical genome_manifest.tsv and taxonomy_reconciliation_all5438.tsv.gz...", flush=True)
    gman_path = in_dir / "genome_manifest.tsv"
    if not gman_path.exists():
        raise FileNotFoundError(f"Missing authoritative genome_manifest.tsv at {gman_path}")
    gman_df = pd.read_csv(gman_path, sep="\t")
    if len(gman_df) != 5438:
        raise ValueError(f"Expected 5,438 rows in genome_manifest.tsv, got {len(gman_df)}")
    if gman_df["mag"].nunique() != 5438:
        raise ValueError("Duplicate MAG IDs in genome_manifest.tsv")

    tax_path = in_dir / "taxonomy_reconciliation_all5438.tsv.gz"
    if not tax_path.exists():
        tax_path = P_TAX_5438
    tax_df = pd.read_csv(tax_path, sep="\t")
    if len(tax_df) != 5438:
        raise ValueError(f"Expected 5,438 rows in taxonomy_reconciliation_all5438.tsv.gz, got {len(tax_df)}")

    if set(gman_df["mag"]) != set(tax_df["genome"]):
        diff1 = set(gman_df["mag"]) - set(tax_df["genome"])
        diff2 = set(tax_df["genome"]) - set(gman_df["mag"])
        raise ValueError(f"Mismatch between genome_manifest and taxonomy_reconciliation: {len(diff1)}, {len(diff2)}")

    gunc_lookup: dict[str, dict[str, Any]] = {}
    if P_GUNC.exists():
        gdf = pd.read_csv(P_GUNC, sep="\t")
        gunc_lookup = gdf.set_index("genome").to_dict("index")

    gman_lookup = gman_df.set_index("mag").to_dict("index")
    tax_lookup = tax_df.set_index("genome").to_dict("index")

    already_verified: set[str] = set()
    for mag_id, m_exp in gman_lookup.items():
        fa_path = fastas_dir / f"{mag_id}.fa"
        if fa_path.exists() and fa_path.stat().st_size == int(m_exp["bytes"]):
            if sha256_file(fa_path) == str(m_exp["sha256"]):
                already_verified.add(mag_id)

    print(
        f"[Stage 0a] Already extracted & SHA-256 verified FASTAs: {len(already_verified)}/5438.",
        flush=True,
    )

    if len(already_verified) < 5438:
        if not P_REFINED_TAR.exists():
            raise FileNotFoundError(f"Missing refined_bins_all.tar at {P_REFINED_TAR}")
        print(f"[Stage 0a] Streaming {P_REFINED_TAR} in one single pass to extract remaining MAGs...", flush=True)
        with tarfile.open(P_REFINED_TAR, "r:") as tf:
            for member in tf:
                if not member.isfile() or not member.name.endswith(".fa"):
                    continue
                bname = Path(member.name).name
                mag_id = bname[:-3]
                if mag_id not in gman_lookup or mag_id in already_verified:
                    continue
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                raw_bytes = fobj.read()
                m_exp = gman_lookup[mag_id]
                actual_bytes = len(raw_bytes)
                actual_sha = hashlib.sha256(raw_bytes).hexdigest()
                n_contigs, n_bases = count_contigs_and_bases(raw_bytes)
                if (
                    actual_bytes != int(m_exp["bytes"])
                    or actual_sha != str(m_exp["sha256"])
                    or n_contigs != int(m_exp["contigs"])
                    or n_bases != int(m_exp["bases"])
                ):
                    raise RuntimeError(
                        f"Archive verification mismatch for {mag_id}: "
                        f"bytes={actual_bytes}/{m_exp['bytes']}, sha256={actual_sha}/{m_exp['sha256']}, "
                        f"contigs={n_contigs}/{m_exp['contigs']}, bases={n_bases}/{m_exp['bases']}"
                    )
                out_fa = fastas_dir / f"{mag_id}.fa"
                tmp_fa = fastas_dir / f".{mag_id}.fa.tmp"
                tmp_fa.write_bytes(raw_bytes)
                tmp_fa.replace(out_fa)
                already_verified.add(mag_id)
                if len(already_verified) % 1000 == 0:
                    print(f"  ...verified & staged {len(already_verified)}/5438 canonical MAGs", flush=True)

    if len(already_verified) != 5438:
        missing = sorted(set(gman_lookup.keys()) - already_verified)
        raise RuntimeError(f"Incomplete canonical cohort after tar stream! Missing {len(missing)}: {missing[:10]}")

    cohort_rows: list[dict[str, Any]] = []
    for mag_id in sorted(gman_lookup.keys()):
        m_exp = gman_lookup[mag_id]
        t_row = tax_lookup[mag_id]
        g_row = gunc_lookup.get(mag_id, {})
        comp = float(t_row["canonical_completeness"])
        cont = float(t_row["canonical_contamination"])
        source_sample = mag_id.split("__")[0] if "__" in mag_id else ""
        cohort_rows.append(
            {
                "mag": mag_id,
                "staged_fasta_path": str(fastas_dir / f"{mag_id}.fa"),
                "manifest_rel_path": str(m_exp["path"]),
                "bytes": int(m_exp["bytes"]),
                "sha256": str(m_exp["sha256"]),
                "contigs": int(m_exp["contigs"]),
                "bases": int(m_exp["bases"]),
                "source_sample": source_sample,
                "binning_strategy": "self" if "__self_" in mag_id else ("single" if "__single_" in mag_id else "other"),
                "has_sub_suffix": bool(mag_id.endswith("_sub")),
                "canonical_domain": str(t_row["canonical_domain"]),
                "canonical_phylum": str(t_row["canonical_phylum"]),
                "canonical_class": str(t_row["canonical_class"]),
                "canonical_order": str(t_row["canonical_order"]),
                "canonical_family": str(t_row["canonical_family"]),
                "canonical_genus": str(t_row["canonical_genus"]),
                "canonical_species": str(t_row["canonical_species"]),
                "checkm2_completeness": comp,
                "checkm2_contamination": cont,
                "quality_tier": assign_mimag_tier(comp, cont),
                "pass_gunc": str(g_row.get("pass.GUNC", "unscored")),
                "dna_verification_status": "verified_exact_sha256_bytes_contigs_bases",
            }
        )

    cohort_df = pd.DataFrame(cohort_rows)
    cohort_out = in_dir / "cohort_manifest_5438.tsv"
    cohort_df.to_csv(cohort_out, sep="\t", index=False)

    thermo_mags = cohort_df[cohort_df["canonical_phylum"] == "p__Thermoplasmatota"]["mag"].tolist()
    other_arch_mags = cohort_df[
        (cohort_df["canonical_domain"] == "d__Archaea") & (cohort_df["canonical_phylum"] != "p__Thermoplasmatota")
    ]["mag"].tolist()
    bac_mags = cohort_df[cohort_df["canonical_domain"] == "d__Bacteria"]["mag"].tolist()

    preferred_thermo = [m for m in thermo_mags if m.startswith(("22PRr1__", "V60PRr2__"))]
    smoke_thermo = (preferred_thermo + [m for m in thermo_mags if m not in preferred_thermo])[:2]
    smoke_other_arch = other_arch_mags[:2]
    smoke_bac = bac_mags[:2]
    smoke_list = smoke_bac + smoke_thermo + smoke_other_arch

    (in_dir / "smoke_mags.txt").write_text("\n".join(smoke_list) + "\n")
    all_mags_sorted = cohort_df["mag"].tolist()
    (in_dir / "all_5438_mags.txt").write_text("\n".join(all_mags_sorted) + "\n")

    n_chunks = args.n_chunks
    for idx in range(n_chunks):
        chunk_mags = all_mags_sorted[idx::n_chunks]
        (chunks_dir / f"chunk_{idx:02d}.txt").write_text("\n".join(chunk_mags) + "\n")

    summary = {
        "stage": "stage0a_extract_genomes",
        "status": "completed",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - t0, 2),
        "n_canonical_mags_verified": len(cohort_df),
        "n_bacteria": int((cohort_df["canonical_domain"] == "d__Bacteria").sum()),
        "n_archaea": int((cohort_df["canonical_domain"] == "d__Archaea").sum()),
        "n_thermoplasmatota": int((cohort_df["canonical_phylum"] == "p__Thermoplasmatota").sum()),
        "n_has_sub_suffix": int(cohort_df["has_sub_suffix"].sum()),
        "n_chunks": n_chunks,
        "smoke_mags": smoke_list,
        "cohort_manifest_sha256": sha256_file(cohort_out),
    }
    (prov_dir / "stage0a_extract_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (in_dir / "STAGE0A_DONE").touch()
    print("[Stage 0a] Completed:", json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
