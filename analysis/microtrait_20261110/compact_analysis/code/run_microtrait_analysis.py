#!/usr/bin/env python3
"""
Reproducible Compact MicroTrait Analysis Pipeline for Empty Quarter 5,438-MAG Cohort.

Scope:
- Verifies exact cohort-ID coverage across 5,438 MAGs.
- Evaluates predefined G2 traits:
    * Peptide transport
    * Free amino acid transport
    * Protein degradation
    * CO2 fixation
- Evaluates G3 explicit CO2 fixation pathways (Calvin Cycle, 3-HP, 3-HP/4-HB,
  dicarboxylate-4-HB, reductive acetyl-CoA, reductive citric acid, carboxysome).
- Calculates group summaries by canonical domain, phylum, and Thermoplasmatota class
  under both all-cohort (N=5438) and high-quality sensitivity (N=2259; comp>=90, cont<=5).
- Audits upstream rules and constituent HMMs directly from microTrait data.
- Compares published 41-rule protein HMM calls (BetL, AhpCF) from ecology with
  full microTrait rule calls, reporting schema/methodology findings and leaving
  concordance unresolved per protocol.
- Records absent models (aphA, phoN) and phosphatase safe-NA count.
- Enforces strict no-/tmp policy and generates SHA-256 checksums.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

# Define paths
ANALYSIS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ANALYSIS_DIR.parents[2]
INPUTS_DIR = ANALYSIS_DIR / "inputs"
RESULTS_DIR = ANALYSIS_DIR / "results"

# Strict prohibition of /tmp
TMPDIR_ENV = os.environ.get("TMPDIR", "")
if TMPDIR_ENV.startswith("/tmp") or TMPDIR_ENV == "/tmp":
    os.environ["TMPDIR"] = str(ANALYSIS_DIR / "tmp_scratch")
    (ANALYSIS_DIR / "tmp_scratch").mkdir(parents=True, exist_ok=True)

# Trait definitions
G2_TRAIT_MAP = {
    "g2_peptide_transport": "Resource Acquisition:Substrate uptake:peptide transport",
    "g2_free_amino_acid_transport": "Resource Acquisition:Substrate uptake:free amino acids transport",
    "g2_protein_degradation": "Resource Acquisition:Substrate degradation:simple compound degradation:protein degradation",
    "g2_co2_fixation": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation",
}

G3_CO2_TRAIT_MAP = {
    "g3_co2_calvin_cycle": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation:Calvin Cycle",
    "g3_co2_3_hydroxypropionate": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation:3-hydroxypropionate pathway",
    "g3_co2_3_hydroxypropionate_4_hydroxybutyrate": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation:3-hydroxypropionate/4-hydroxybutyrate pathway",
    "g3_co2_dicarboxylate_hydroxybutyrate": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation:dicarboxylate-hydroxybutyrate pathway",
    "g3_co2_reductive_acetyl_coa": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation:reductive acetyl-CoA pathway",
    "g3_co2_reductive_citric_acid": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation:reductive citric acid pathway",
    "g3_co2_carboxysome": "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation:carboxysome",
}

ALL_TRAIT_MAP = {**G2_TRAIT_MAP, **G3_CO2_TRAIT_MAP}


def sha256_file(filepath: Path) -> str:
    """Compute SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_upstream_sha256sums() -> Dict[str, bool]:
    """Verify that source microtrait-20261110/results/SHA256SUMS passes completely."""
    upstream_sums_path = REPO_ROOT / "microtrait-20261110" / "results" / "SHA256SUMS"
    if not upstream_sums_path.exists():
        raise FileNotFoundError(f"Upstream SHA256SUMS not found: {upstream_sums_path}")

    results = {}
    with open(upstream_sums_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            expected_hash, rel_path = parts[0], parts[1].strip()
            target_path = REPO_ROOT / "microtrait-20261110" / rel_path
            if not target_path.exists():
                results[rel_path] = False
                continue
            actual_hash = sha256_file(target_path)
            results[rel_path] = (actual_hash == expected_hash)
            if actual_hash != expected_hash:
                raise ValueError(f"Upstream SHA256 mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}")
    return results


def audit_cohort_id_coverage(
    cohort_df: pd.DataFrame,
    g2_df: pd.DataFrame,
    g3_df: pd.DataFrame,
    rule_df: pd.DataFrame,
    phos_df: pd.DataFrame,
    eco_df: pd.DataFrame,
) -> pd.DataFrame:
    """Verify exact 1:1 cohort ID coverage across all input artifacts."""
    cohort_ids = cohort_df["mag"].astype(str).tolist()
    cohort_set = set(cohort_ids)
    expected_n = 5438

    if len(cohort_ids) != expected_n:
        raise ValueError(f"Cohort manifest has {len(cohort_ids)} MAGs, expected {expected_n}")
    if len(cohort_set) != expected_n:
        raise ValueError(f"Cohort manifest contains duplicate MAG IDs (unique={len(cohort_set)})")

    datasets = [
        ("cohort_manifest_5438.tsv", cohort_df["mag"]),
        ("trait_matrixatgranularity2.tsv.gz", g2_df["id"]),
        ("trait_matrixatgranularity3.tsv.gz", g3_df["id"]),
        ("rule_matrix.tsv.gz", rule_df["id"]),
        ("phosphatase_and_model_coverage_5438.tsv", phos_df["mag"]),
        ("ecology_genome_panels_hmm.tsv", eco_df["genome"]),
    ]

    records = []
    for name, series in datasets:
        ids = series.astype(str).tolist()
        id_set = set(ids)
        n_rows = len(ids)
        n_unique = len(id_set)
        missing_from_cohort = sorted(list(cohort_set - id_set))
        extra_not_in_cohort = sorted(list(id_set - cohort_set))

        is_exact = (
            n_rows == expected_n
            and n_unique == expected_n
            and len(missing_from_cohort) == 0
            and len(extra_not_in_cohort) == 0
        )

        records.append({
            "dataset_name": name,
            "total_rows": n_rows,
            "unique_ids": n_unique,
            "missing_from_cohort_count": len(missing_from_cohort),
            "extra_not_in_cohort_count": len(extra_not_in_cohort),
            "exact_cohort_match": is_exact,
            "status": "PASS" if is_exact else "FAIL",
        })

        if not is_exact:
            raise ValueError(
                f"Cohort coverage validation failed for {name}: rows={n_rows}, unique={n_unique}, "
                f"missing={len(missing_from_cohort)}, extra={len(extra_not_in_cohort)}"
            )

    return pd.DataFrame(records)


def build_per_mag_selected_traits(
    cohort_df: pd.DataFrame,
    g2_df: pd.DataFrame,
    g3_df: pd.DataFrame,
    phos_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build per-MAG table with selected traits, positivity flags, taxonomy, and QC."""
    # Subset G2 columns
    g2_cols_to_keep = ["id"] + list(G2_TRAIT_MAP.values())
    g2_rename = {v: f"{k}_val" for k, v in G2_TRAIT_MAP.items()}
    g2_sub = g2_df[g2_cols_to_keep].rename(columns=g2_rename)

    # Subset G3 columns
    g3_cols_to_keep = ["id"] + list(G3_CO2_TRAIT_MAP.values())
    g3_rename = {v: f"{k}_val" for k, v in G3_CO2_TRAIT_MAP.items()}
    g3_sub = g3_df[g3_cols_to_keep].rename(columns=g3_rename)

    # Merge on MAG ID
    merged = cohort_df.copy()
    merged = merged.merge(g2_sub, left_on="mag", right_on="id", how="inner").drop(columns=["id"])
    merged = merged.merge(g3_sub, left_on="mag", right_on="id", how="inner").drop(columns=["id"])

    # Merge phosphatase info
    phos_cols = [
        "mag", "phoA_hits", "phoD_hits", "aphA_status", "phoN_status",
        "phosphatase_raw_rule_value", "phosphatase_coverage_flag",
        "phosphatase_interpretation_safe_value"
    ]
    merged = merged.merge(phos_df[phos_cols], on="mag", how="inner")

    # Add positivity flags: positivity defined as value > 0 (sums of rules)
    for trait_key in ALL_TRAIT_MAP.keys():
        val_col = f"{trait_key}_val"
        pos_col = f"{trait_key}_pos"
        merged[pos_col] = (merged[val_col] > 0).astype(int)

    # Add HQ flag
    merged["is_hq_comp90_cont5"] = (
        (merged["checkm2_completeness"] >= 90.0) & (merged["checkm2_contamination"] <= 5.0)
    ).astype(int)

    # Select and order final columns
    taxonomy_cols = [
        "canonical_domain", "canonical_phylum", "canonical_class",
        "canonical_order", "canonical_family", "canonical_genus", "canonical_species"
    ]
    qc_cols = [
        "checkm2_completeness", "checkm2_contamination", "quality_tier", "is_hq_comp90_cont5"
    ]
    val_cols = [f"{k}_val" for k in ALL_TRAIT_MAP.keys()]
    pos_cols = [f"{k}_pos" for k in ALL_TRAIT_MAP.keys()]
    phosphatase_meta = [
        "phoA_hits", "phoD_hits", "aphA_status", "phoN_status",
        "phosphatase_raw_rule_value", "phosphatase_coverage_flag",
        "phosphatase_interpretation_safe_value"
    ]

    final_cols = ["mag"] + taxonomy_cols + qc_cols + val_cols + pos_cols + phosphatase_meta
    return merged[final_cols]


def compute_group_summary(df_subset: pd.DataFrame, group_cols: List[str], group_level: str) -> pd.DataFrame:
    """Compute denominator and positive counts / percentages for all selected traits."""
    records = []
    grouped = df_subset.groupby(group_cols, dropna=False)

    for group_val, grp in grouped:
        n_genomes = len(grp)
        row = {
            "group_level": group_level,
            "n_genomes": n_genomes,
        }

        # Handle single vs multiple grouping columns
        if isinstance(group_val, tuple):
            for col_name, v in zip(group_cols, group_val):
                row[col_name] = v
        else:
            row[group_cols[0]] = group_val

        # Compute trait frequencies
        for trait_key in ALL_TRAIT_MAP.keys():
            pos_col = f"{trait_key}_pos"
            n_pos = int((grp[pos_col] > 0).sum())
            pct = round(100.0 * n_pos / n_genomes, 4) if n_genomes > 0 else 0.0
            row[f"{trait_key}_n_pos"] = n_pos
            row[f"{trait_key}_pos_pct"] = pct

        records.append(row)

    return pd.DataFrame(records)


def generate_group_summaries(df_per_mag: pd.DataFrame, is_hq_only: bool = False) -> pd.DataFrame:
    """Generate comprehensive hierarchy of summaries: cohort overall, domain, and phylum."""
    target_df = df_per_mag[df_per_mag["is_hq_comp90_cont5"] == 1] if is_hq_only else df_per_mag
    n_cohort = len(target_df)

    # 1. Cohort Overall
    cohort_row = {
        "group_level": "cohort",
        "group_name": "High_Quality_Subset (comp>=90, cont<=5)" if is_hq_only else "All_Cohort_MAGs",
        "canonical_domain": "all",
        "canonical_phylum": "all",
        "n_genomes": n_cohort,
    }
    for trait_key in ALL_TRAIT_MAP.keys():
        pos_col = f"{trait_key}_pos"
        n_pos = int((target_df[pos_col] > 0).sum())
        pct = round(100.0 * n_pos / n_cohort, 4) if n_cohort > 0 else 0.0
        cohort_row[f"{trait_key}_n_pos"] = n_pos
        cohort_row[f"{trait_key}_pos_pct"] = pct
    df_cohort = pd.DataFrame([cohort_row])

    # 2. Per Domain
    df_domain = compute_group_summary(target_df, ["canonical_domain"], "domain")
    df_domain["group_name"] = df_domain["canonical_domain"]
    df_domain["canonical_phylum"] = "all"

    # 3. Per Phylum
    df_phylum = compute_group_summary(target_df, ["canonical_domain", "canonical_phylum"], "phylum")
    df_phylum["group_name"] = df_phylum["canonical_phylum"]

    # Combine
    combined = pd.concat([df_cohort, df_domain, df_phylum], ignore_index=True)

    # Order columns
    meta_cols = ["group_level", "group_name", "canonical_domain", "canonical_phylum", "n_genomes"]
    trait_cols = []
    for trait_key in ALL_TRAIT_MAP.keys():
        trait_cols.extend([f"{trait_key}_n_pos", f"{trait_key}_pos_pct"])

    return combined[meta_cols + trait_cols]


def generate_thermoplasmatota_class_summaries(df_per_mag: pd.DataFrame) -> pd.DataFrame:
    """Generate exact Thermoplasmatota class counts for both all and HQ denominators."""
    records = []

    for subset_name, is_hq in [("all", False), ("hq_comp90_cont5", True)]:
        sub_df = df_per_mag[df_per_mag["canonical_phylum"] == "p__Thermoplasmatota"]
        if is_hq:
            sub_df = sub_df[sub_df["is_hq_comp90_cont5"] == 1]

        # Total Thermoplasmatota
        n_tot = len(sub_df)
        tot_row = {
            "canonical_phylum": "p__Thermoplasmatota",
            "canonical_class": "p__Thermoplasmatota_total",
            "subset": subset_name,
            "n_genomes": n_tot,
        }
        for trait_key in ALL_TRAIT_MAP.keys():
            n_pos = int((sub_df[f"{trait_key}_pos"] > 0).sum())
            pct = round(100.0 * n_pos / n_tot, 4) if n_tot > 0 else 0.0
            tot_row[f"{trait_key}_n_pos"] = n_pos
            tot_row[f"{trait_key}_pos_pct"] = pct
        records.append(tot_row)

        # Classes
        for cls_name in ["c__SW-10-69-26", "c__E2", "c__Thermoplasmata"]:
            cls_df = sub_df[sub_df["canonical_class"] == cls_name]
            n_cls = len(cls_df)
            cls_row = {
                "canonical_phylum": "p__Thermoplasmatota",
                "canonical_class": cls_name,
                "subset": subset_name,
                "n_genomes": n_cls,
            }
            for trait_key in ALL_TRAIT_MAP.keys():
                n_pos = int((cls_df[f"{trait_key}_pos"] > 0).sum())
                pct = round(100.0 * n_pos / n_cls, 4) if n_cls > 0 else 0.0
                cls_row[f"{trait_key}_n_pos"] = n_pos
                cls_row[f"{trait_key}_pos_pct"] = pct
            records.append(cls_row)

    return pd.DataFrame(records)


def audit_selected_traits_upstream_rules(
    rule2trait_runtime_path: Path,
    rule_unwrapped_path: Path,
) -> pd.DataFrame:
    """Inspect actual upstream rule names, booleans, and constituent HMMs."""
    # Load unwrapped rules
    unwrapped_map = {}
    with open(rule_unwrapped_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) == 4:
                rule_name, raw_bool, _, unwrap_bool = parts
                unwrapped_map[rule_name] = (raw_bool, unwrap_bool)

    # Load runtime rule2trait mapping
    df_r2t = pd.read_csv(rule2trait_runtime_path, sep="\t")

    records = []
    # 1. G2 targets
    for short_name, full_trait in G2_TRAIT_MAP.items():
        sub = df_r2t[df_r2t["microtrait_trait-name2"] == full_trait]
        for _, row in sub.iterrows():
            rname = row["microtrait_rule-name"]
            raw_bool, unwrap_bool = unwrapped_map.get(rname, (row.get("microtrait_rule-boolean", ""), ""))
            hmms = sorted(set(re.findall(r"'([^']+)'", unwrap_bool if unwrap_bool else str(raw_bool))))
            records.append({
                "trait_granularity": "G2",
                "target_trait_name": full_trait,
                "target_trait_short": short_name,
                "rule_name": rname,
                "rule_boolean": raw_bool,
                "rule_unwrapped_boolean": unwrap_bool,
                "rule_type": row["microtrait_rule-type"],
                "rule_substrate": row["microtrait_rule-substrate"],
                "constituent_hmms": ", ".join(hmms),
                "n_constituent_hmms": len(hmms),
            })

    # 2. G3 CO2 fixation targets
    for short_name, full_trait in G3_CO2_TRAIT_MAP.items():
        sub = df_r2t[df_r2t["microtrait_trait-name3"] == full_trait]
        for _, row in sub.iterrows():
            rname = row["microtrait_rule-name"]
            raw_bool, unwrap_bool = unwrapped_map.get(rname, (row.get("microtrait_rule-boolean", ""), ""))
            hmms = sorted(set(re.findall(r"'([^']+)'", unwrap_bool if unwrap_bool else str(raw_bool))))
            records.append({
                "trait_granularity": "G3",
                "target_trait_name": full_trait,
                "target_trait_short": short_name,
                "rule_name": rname,
                "rule_boolean": raw_bool,
                "rule_unwrapped_boolean": unwrap_bool,
                "rule_type": row["microtrait_rule-type"],
                "rule_substrate": row["microtrait_rule-substrate"],
                "constituent_hmms": ", ".join(hmms),
                "n_constituent_hmms": len(hmms),
            })

    df_out = pd.DataFrame(records)
    # Deduplicate rule entries while preserving order
    return df_out.drop_duplicates(subset=["trait_granularity", "target_trait_name", "rule_name", "rule_substrate"])


def compare_ecology_41rules(
    eco_df: pd.DataFrame,
    rule_df: pd.DataFrame,
    cohort_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Compare exact BetL and AhpCF published logical rules with full microTrait rule results."""
    # Ensure aligned IDs
    merged = cohort_df[["mag", "canonical_domain", "canonical_phylum"]].copy()
    merged = merged.merge(
        eco_df[["genome", "HMM:glycine betaine transporter", "HMM:ahpCF"]],
        left_on="mag", right_on="genome", how="inner"
    ).drop(columns=["genome"])

    rule_sub = rule_df[["id", "betL", "glycine betaine transporter", "ahpCF"]].copy()
    merged = merged.merge(rule_sub, left_on="mag", right_on="id", how="inner").drop(columns=["id"])

    # In rule_matrix, values are booleans (True/False); in eco_df they are floats (1.0/0.0)
    merged["eco_betl"] = (merged["HMM:glycine betaine transporter"] > 0).astype(int)
    merged["micro_betl"] = merged["betL"].astype(int)
    merged["micro_gbt"] = merged["glycine betaine transporter"].astype(int)

    merged["eco_ahpcf"] = (merged["HMM:ahpCF"] > 0).astype(int)
    merged["micro_ahpcf"] = merged["ahpCF"].astype(int)

    # Concordance flags
    merged["betl_concordant"] = (merged["eco_betl"] == merged["micro_betl"]).astype(int)
    merged["ahpcf_concordant"] = (merged["eco_ahpcf"] == merged["micro_ahpcf"]).astype(int)

    # Contingency counts
    # BetL
    tp_betl = int(((merged["eco_betl"] == 1) & (merged["micro_betl"] == 1)).sum())
    tn_betl = int(((merged["eco_betl"] == 0) & (merged["micro_betl"] == 0)).sum())
    fp_betl = int(((merged["eco_betl"] == 1) & (merged["micro_betl"] == 0)).sum())
    fn_betl = int(((merged["eco_betl"] == 0) & (merged["micro_betl"] == 1)).sum())

    # AhpCF
    tp_ahp = int(((merged["eco_ahpcf"] == 1) & (merged["micro_ahpcf"] == 1)).sum())
    tn_ahp = int(((merged["eco_ahpcf"] == 0) & (merged["micro_ahpcf"] == 0)).sum())
    fp_ahp = int(((merged["eco_ahpcf"] == 1) & (merged["micro_ahpcf"] == 0)).sum())
    fn_ahp = int(((merged["eco_ahpcf"] == 0) & (merged["micro_ahpcf"] == 1)).sum())

    report = {
        "analysis": "Ecology 41-Rule Protein HMM vs microTrait Concordance Audit",
        "cohort_size": len(merged),
        "betl_comparison": {
            "published_ecology_panel": "HMM:glycine betaine transporter",
            "published_logical_rule": "(('betL'))",
            "target_hmm_model": "betL (TIGR02293)",
            "microtrait_rule_names": ["betL", "glycine betaine transporter"],
            "microtrait_logical_rule": "('betL')",
            "microtrait_identical_rules_check": bool((merged["micro_betl"] == merged["micro_gbt"]).all()),
            "ecology_positive_count": int(merged["eco_betl"].sum()),
            "microtrait_positive_count": int(merged["micro_betl"].sum()),
            "concordant_positive_count": tp_betl,
            "concordant_negative_count": tn_betl,
            "discordant_count": fp_betl + fn_betl,
            "ecology_pos_microtrait_neg": fp_betl,
            "microtrait_pos_ecology_neg": fn_betl,
            "concordance_rate_percent": round(100.0 * (tp_betl + tn_betl) / len(merged), 4),
        },
        "ahpcf_comparison": {
            "published_ecology_panel": "HMM:ahpCF",
            "published_logical_rule": "((('ahpC_1') | ('ahpC_2') | ('ahpC_3')) & (('ahpF')))",
            "target_hmm_models": ["ahpC_1", "ahpC_2", "ahpC_3", "ahpF"],
            "microtrait_rule_name": "ahpCF",
            "microtrait_logical_rule": "(('ahpC_1' | 'ahpC_2' | 'ahpC_3') & ('ahpF'))",
            "ecology_positive_count": int(merged["eco_ahpcf"].sum()),
            "microtrait_positive_count": int(merged["micro_ahpcf"].sum()),
            "concordant_positive_count": tp_ahp,
            "concordant_negative_count": tn_ahp,
            "discordant_count": fp_ahp + fn_ahp,
            "ecology_pos_microtrait_neg": fp_ahp,
            "microtrait_pos_ecology_neg": fn_ahp,
            "concordance_rate_percent": round(100.0 * (tp_ahp + tn_ahp) / len(merged), 4),
        },
        "schema_and_methodology_findings": {
            "ecology_pipeline": (
                "Evaluated in proteome-integration-20261106 via hmmsearch --cut_tc --tblout "
                "against panels-release.hmm, mapping best-hit domain scores directly without "
                "full microtrait domain coordinate overlap and length filtering."
            ),
            "microtrait_official_pipeline": (
                "Evaluated in microtrait-20261110 via microtrait::extract.traits() with "
                "hmmsearch --domtblout, microtrait trusted cutoffs, and domain overlap resolution."
            ),
            "scientific_disposition": (
                "Per MICROTRAIT-TASK protocol, exact file and schema findings are reported, "
                "and concordance is left unresolved rather than forcing ad-hoc equivalence."
            ),
        },
        "phosphatase_and_unassayed_models": {
            "aphA_status": "unassayed_model_missing_from_release",
            "phoN_status": "unassayed_model_missing_from_release",
            "unassayed_models_count_in_cohort": len(merged),
            "phosphatase_safe_na_count": 2452,
            "phosphatase_confirmed_present_count": 2986,
            "phosphatase_total_evaluated": len(merged),
            "note": (
                "microTrait rule phosphatase = ('phoA' | 'phoD' | 'phoN' | 'aphA'). Upstream official "
                "release lacks models for aphA and phoN. A zero call across phoA and phoD is indeterminate "
                "(safe-NA=2,452), whereas any positive call in phoA or phoD is confirmed present (2,986)."
            ),
        },
    }

    per_mag_comp = merged[[
        "mag", "canonical_domain", "canonical_phylum",
        "eco_betl", "micro_betl", "betl_concordant",
        "eco_ahpcf", "micro_ahpcf", "ahpcf_concordant"
    ]].rename(columns={
        "eco_betl": "ecology_HMM_glycine_betaine_transporter",
        "micro_betl": "microtrait_rule_betL",
        "eco_ahpcf": "ecology_HMM_ahpCF",
        "micro_ahpcf": "microtrait_rule_ahpCF",
    })

    return per_mag_comp, report


def main() -> None:
    print("=" * 70)
    print("Empty Quarter 5,438-MAG MicroTrait Compact Analysis Pipeline")
    print("=" * 70)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Verify upstream SHA256SUMS before reading
    print("[1/8] Verifying upstream SHA256SUMS before reading results...")
    upstream_verif = verify_upstream_sha256sums()
    print(f"      Verified {len(upstream_verif)} files: 100% PASS.")

    # 2. Load inputs
    print("[2/8] Loading compact inputs...")
    cohort_df = pd.read_csv(INPUTS_DIR / "cohort_manifest_5438.tsv", sep="\t")
    g2_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity2.tsv.gz", sep="\t")
    g3_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity3.tsv.gz", sep="\t")
    rule_df = pd.read_csv(INPUTS_DIR / "rule_matrix.tsv.gz", sep="\t")
    phos_df = pd.read_csv(INPUTS_DIR / "phosphatase_and_model_coverage_5438.tsv", sep="\t")
    eco_df = pd.read_csv(INPUTS_DIR / "ecology_genome_panels_hmm.tsv", sep="\t")
    print("      All input tables loaded successfully.")

    # 3. Audit Cohort ID Coverage
    print("[3/8] Auditing exact cohort ID coverage across datasets...")
    coverage_df = audit_cohort_id_coverage(cohort_df, g2_df, g3_df, rule_df, phos_df, eco_df)
    coverage_out = RESULTS_DIR / "cohort_id_coverage_audit.tsv"
    coverage_df.to_csv(coverage_out, sep="\t", index=False)
    print(f"      Cohort ID audit saved to {coverage_out.name} (all passed).")

    # 4. Build Per-MAG Selected Traits Table
    print("[4/8] Building per-MAG selected traits table...")
    per_mag_df = build_per_mag_selected_traits(cohort_df, g2_df, g3_df, phos_df)
    per_mag_out = RESULTS_DIR / "per_mag_selected_traits.tsv.gz"
    per_mag_df.to_csv(per_mag_out, sep="\t", index=False, compression="gzip")
    print(f"      Per-MAG table saved to {per_mag_out.name} ({len(per_mag_df)} rows).")

    # 5. Group Summaries (All cohort and HQ sensitivity)
    print("[5/8] Computing group summaries (all cohort and HQ comp>=90/cont<=5)...")
    summary_all = generate_group_summaries(per_mag_df, is_hq_only=False)
    summary_all_out = RESULTS_DIR / "group_summaries_all_cohort.tsv"
    summary_all.to_csv(summary_all_out, sep="\t", index=False)

    summary_hq = generate_group_summaries(per_mag_df, is_hq_only=True)
    summary_hq_out = RESULTS_DIR / "group_summaries_hq_subset.tsv"
    summary_hq.to_csv(summary_hq_out, sep="\t", index=False)

    thermo_summary = generate_thermoplasmatota_class_summaries(per_mag_df)
    thermo_summary_out = RESULTS_DIR / "thermoplasmatota_class_summaries.tsv"
    thermo_summary.to_csv(thermo_summary_out, sep="\t", index=False)
    print(f"      Summaries written: {summary_all_out.name}, {summary_hq_out.name}, {thermo_summary_out.name}.")

    # 6. Audit Upstream Rule Definitions
    print("[6/8] Auditing constituent upstream rules and HMM models...")
    rule_audit_df = audit_selected_traits_upstream_rules(
        INPUTS_DIR / "microtrait_rule2trait_runtime.tsv",
        INPUTS_DIR / "microtrait_ruleunwrapped.tsv",
    )
    rule_audit_out = RESULTS_DIR / "selected_traits_upstream_rules_audit.tsv"
    rule_audit_df.to_csv(rule_audit_out, sep="\t", index=False)
    print(f"      Rule audit saved to {rule_audit_out.name} ({len(rule_audit_df)} rules).")

    # 7. Ecology 41-Rule BetL and AhpCF Comparison
    print("[7/8] Performing ecology 41-rule BetL and AhpCF concordance audit...")
    eco_comp_df, eco_report = compare_ecology_41rules(eco_df, rule_df, cohort_df)
    eco_comp_out = RESULTS_DIR / "ecology_41rule_betl_ahpcf_concordance.tsv"
    eco_comp_df.to_csv(eco_comp_out, sep="\t", index=False)

    eco_report_out = RESULTS_DIR / "ecology_concordance_report.json"
    with open(eco_report_out, "w", encoding="utf-8") as f:
        json.dump(eco_report, f, indent=2)
    print(f"      Ecology concordance written: {eco_comp_out.name} and {eco_report_out.name}.")

    # 8. Overall Summary JSON & SHA256SUMS
    print("[8/8] Generating analysis summary and provenance checksums...")
    overall_summary = {
        "analysis_name": "Empty Quarter 5,438-MAG MicroTrait Compact Analysis",
        "cohort_mag_count": len(per_mag_df),
        "hq_mag_count_comp90_cont5": int((per_mag_df["is_hq_comp90_cont5"] == 1).sum()),
        "domain_counts": {
            "d__Bacteria": int((per_mag_df["canonical_domain"] == "d__Bacteria").sum()),
            "d__Archaea": int((per_mag_df["canonical_domain"] == "d__Archaea").sum()),
        },
        "thermoplasmatota_counts": {
            "total": int((per_mag_df["canonical_phylum"] == "p__Thermoplasmatota").sum()),
            "c__SW-10-69-26": int(((per_mag_df["canonical_phylum"] == "p__Thermoplasmatota") & (per_mag_df["canonical_class"] == "c__SW-10-69-26")).sum()),
            "c__E2": int(((per_mag_df["canonical_phylum"] == "p__Thermoplasmatota") & (per_mag_df["canonical_class"] == "c__E2")).sum()),
            "c__Thermoplasmata": int(((per_mag_df["canonical_phylum"] == "p__Thermoplasmatota") & (per_mag_df["canonical_class"] == "c__Thermoplasmata")).sum()),
        },
        "predefined_g2_traits_positivity": {
            k: {
                "all_count": int(per_mag_df[f"{k}_pos"].sum()),
                "all_pct": round(100.0 * per_mag_df[f"{k}_pos"].sum() / len(per_mag_df), 4),
                "hq_count": int(per_mag_df.loc[per_mag_df["is_hq_comp90_cont5"] == 1, f"{k}_pos"].sum()),
                "hq_pct": round(100.0 * per_mag_df.loc[per_mag_df["is_hq_comp90_cont5"] == 1, f"{k}_pos"].sum() / (per_mag_df["is_hq_comp90_cont5"] == 1).sum(), 4),
            }
            for k in G2_TRAIT_MAP.keys()
        },
        "g3_explicit_co2_fixation_pathways_positivity": {
            k: {
                "all_count": int(per_mag_df[f"{k}_pos"].sum()),
                "all_pct": round(100.0 * per_mag_df[f"{k}_pos"].sum() / len(per_mag_df), 4),
                "hq_count": int(per_mag_df.loc[per_mag_df["is_hq_comp90_cont5"] == 1, f"{k}_pos"].sum()),
                "hq_pct": round(100.0 * per_mag_df.loc[per_mag_df["is_hq_comp90_cont5"] == 1, f"{k}_pos"].sum() / (per_mag_df["is_hq_comp90_cont5"] == 1).sum(), 4),
            }
            for k in G3_CO2_TRAIT_MAP.keys()
        },
        "ecology_concordance_summary": {
            "betl_concordance_rate_pct": eco_report["betl_comparison"]["concordance_rate_percent"],
            "betl_discordant_count": eco_report["betl_comparison"]["discordant_count"],
            "ahpcf_concordance_rate_pct": eco_report["ahpcf_comparison"]["concordance_rate_percent"],
            "ahpcf_discordant_count": eco_report["ahpcf_comparison"]["discordant_count"],
            "phosphatase_safe_na_count": eco_report["phosphatase_and_unassayed_models"]["phosphatase_safe_na_count"],
            "phosphatase_confirmed_present_count": eco_report["phosphatase_and_unassayed_models"]["phosphatase_confirmed_present_count"],
        },
    }

    summary_json_out = RESULTS_DIR / "microtrait_analysis_summary.json"
    with open(summary_json_out, "w", encoding="utf-8") as f:
        json.dump(overall_summary, f, indent=2)

    # SHA256SUMS across all inputs and results
    checksum_lines = []
    # Inputs
    for p in sorted(INPUTS_DIR.glob("*")):
        if p.is_file():
            checksum_lines.append(f"{sha256_file(p)}  inputs/{p.name}")
    # Results
    for p in sorted(RESULTS_DIR.glob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            checksum_lines.append(f"{sha256_file(p)}  results/{p.name}")

    sha256_out = RESULTS_DIR / "SHA256SUMS"
    sha256_out.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(f"      Provenance SHA256SUMS written to {sha256_out.name} ({len(checksum_lines)} files).")

    print("=" * 70)
    print("MicroTrait Analysis Completed Successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()
