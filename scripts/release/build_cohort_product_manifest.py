#!/usr/bin/env python3
"""Build and validate the shared machine-readable cohort and product manifest.

This generator derives the cross-paper cohort tables and product provenance
manifest strictly from staged repository source tables, verifying specimen/site/
trip/compartment/dune-field joins, same-count member identities against
independent source lists, MIMAG quality boundaries, sequencing platform/kit
totals, CoverM mapping product versions, and protein-caller product distinctions.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import re
from pathlib import Path


COMPANION_PAPERS = ("data", "ecology", "proteome")

CANONICAL_COMPARTMENT_MAP = {
    "Surface": "Surface",
    "Deep": "Deep",
    "Rhizosphere": "RootAdjacent",
    "PlantRoot": "RootAdjacent",
    "RootAdjacent": "RootAdjacent",
}

AMPLICON_COMPARTMENT_MAP = {
    "surface": "Surface",
    "shallow subsurface": "Deep",
    "root-adjacent": "RootAdjacent",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"required staged input table is missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0].keys()),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def normalize_amplicon_sample_id(library_id: str) -> str:
    return re.sub(r"^e\d+_", "", library_id.strip())


def classify_mimag_strict(
    completeness: float,
    contamination: float,
    has_5s: bool,
    has_16s: bool,
    has_23s: bool,
    n_trna_aa: int,
) -> str:
    """Bowers et al. (2017) strict MIMAG tier (<10% contamination for MQ)."""
    if not (math.isfinite(completeness) and math.isfinite(contamination)):
        raise ValueError("non-finite completeness or contamination")
    if (
        completeness > 90.0
        and contamination < 5.0
        and has_5s
        and has_16s
        and has_23s
        and n_trna_aa >= 18
    ):
        return "high"
    if completeness >= 50.0 and contamination < 10.0:
        return "medium"
    return "below-medium"


def classify_drep_operational(completeness: float, contamination: float) -> str:
    """Operational dRep inclusion boundary (>=50% completeness, <=10% contamination)."""
    if not (math.isfinite(completeness) and math.isfinite(contamination)):
        raise ValueError("non-finite completeness or contamination")
    if completeness >= 50.0 and contamination <= 10.0:
        return "drep_included_le10"
    return "drep_excluded"


def parse_gtdb_ranks(tax_str: str) -> dict[str, str]:
    ranks: dict[str, str] = {}
    for token in tax_str.split(";"):
        token = token.strip()
        if "__" in token:
            prefix, val = token.split("__", 1)
            ranks[prefix] = val
    return ranks


def reconcile_taxonomy_snapshots(
    representatives: list[dict[str, str]],
    legacy_taxonomy_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict]:
    """Reconcile canonical GTDB R232 vs frozen legacy analytical taxonomy 1:1 across 5,438 genomes."""
    if len(representatives) != 5438:
        raise ValueError(f"expected 5438 canonical representatives, got {len(representatives)}")
    if len(legacy_taxonomy_rows) != 5438:
        raise ValueError(
            f"expected 5438 legacy analytical taxonomy rows, got {len(legacy_taxonomy_rows)}"
        )

    can_by_id: dict[str, dict[str, str]] = {}
    for row in representatives:
        gid = row["mag"]
        if gid in can_by_id:
            raise ValueError(f"duplicate canonical representative ID: {gid}")
        can_by_id[gid] = row

    leg_by_id: dict[str, dict[str, str]] = {}
    for row in legacy_taxonomy_rows:
        gid = row["genome"]
        if gid in leg_by_id:
            raise ValueError(f"duplicate legacy analytical genome ID: {gid}")
        leg_by_id[gid] = row

    if set(can_by_id) != set(leg_by_id):
        raise ValueError(
            "genome ID sets do not match 1:1 between canonical representatives and legacy analytical taxonomy"
        )

    reconciliation_rows: list[dict[str, str]] = []
    whole_diff = 0
    rank_diffs = {k: 0 for k in ("d", "p", "c", "o", "f", "g", "s")}
    thermo_can_ids: set[str] = set()
    thermo_leg_ids: set[str] = set()
    thermo_whole_diff = 0
    thermo_can_classes: Counter[str] = Counter()
    thermo_can_orders: Counter[str] = Counter()
    thermo_can_genera: Counter[str] = Counter()
    thermo_leg_orders: Counter[str] = Counter()
    thermo_leg_genera: Counter[str] = Counter()

    for gid in sorted(can_by_id):
        c_row = can_by_id[gid]
        l_row = leg_by_id[gid]
        c_comp = float(c_row["Completeness"])
        l_comp = float(l_row["checkm_completeness"])
        c_cont = float(c_row["Contamination"])
        l_cont = float(l_row["contamination"])
        if round(c_comp, 4) != round(l_comp, 4) or round(c_cont, 4) != round(l_cont, 4):
            raise ValueError(
                f"quality metric mismatch between canonical and legacy taxonomy table for {gid}"
            )

        c_tax = c_row["gtdb_r232_classification"]
        l_tax = l_row["gtdb_classification"]
        c_ranks = parse_gtdb_ranks(c_tax)
        l_ranks = parse_gtdb_ranks(l_tax)

        is_whole_diff = c_tax != l_tax
        if is_whole_diff:
            whole_diff += 1

        row_rank_flags: dict[str, str] = {}
        for rk in ("d", "p", "c", "o", "f", "g", "s"):
            diff_rk = c_ranks.get(rk, "") != l_ranks.get(rk, "")
            if diff_rk:
                rank_diffs[rk] += 1
            row_rank_flags[rk] = "1" if diff_rk else "0"

        if c_ranks.get("p") == "Thermoplasmatota":
            thermo_can_ids.add(gid)
            if is_whole_diff:
                thermo_whole_diff += 1
            thermo_can_classes[c_ranks.get("c", "")] += 1
            thermo_can_orders[c_ranks.get("o", "")] += 1
            thermo_can_genera[c_ranks.get("g", "")] += 1
            thermo_leg_orders[l_ranks.get("o", "")] += 1
            thermo_leg_genera[l_ranks.get("g", "")] += 1
        if l_ranks.get("p") == "Thermoplasmatota":
            thermo_leg_ids.add(gid)

        reconciliation_rows.append(
            {
                "mag": gid,
                "sample": c_row["sample"],
                "completeness": c_row["Completeness"],
                "contamination": c_row["Contamination"],
                "canonical_gtdb_r232": c_tax,
                "legacy_analytical_gtdb": l_tax,
                "whole_string_diff": "1" if is_whole_diff else "0",
                "domain_diff": row_rank_flags["d"],
                "phylum_diff": row_rank_flags["p"],
                "class_diff": row_rank_flags["c"],
                "order_diff": row_rank_flags["o"],
                "family_diff": row_rank_flags["f"],
                "genus_diff": row_rank_flags["g"],
                "species_diff": row_rank_flags["s"],
            }
        )

    if thermo_can_ids != thermo_leg_ids or len(thermo_can_ids) != 237:
        raise ValueError(
            f"Thermoplasmatota 237-genome membership mismatch: canonical={len(thermo_can_ids)}, legacy={len(thermo_leg_ids)}"
        )

    summary = {
        "total_representatives": 5438,
        "identical_genome_ids_and_checkm2_quality": True,
        "whole_taxonomy_strings_differing": whole_diff,
        "rank_differences": {
            "domain": rank_diffs["d"],
            "phylum": rank_diffs["p"],
            "class": rank_diffs["c"],
            "order": rank_diffs["o"],
            "family": rank_diffs["f"],
            "genus": rank_diffs["g"],
            "species": rank_diffs["s"],
        },
        "thermoplasmatota_reconciliation": {
            "count": 237,
            "identical_membership_and_quality": True,
            "whole_taxonomy_strings_differing": thermo_whole_diff,
            "canonical_classes": dict(thermo_can_classes),
            "canonical_named_orders": len([k for k in thermo_can_orders if k]),
            "canonical_unassigned_orders": thermo_can_orders.get("", 0),
            "canonical_named_genera": len([k for k in thermo_can_genera if k]),
            "canonical_unassigned_genera": thermo_can_genera.get("", 0),
            "legacy_named_orders": len([k for k in thermo_leg_orders if k]),
            "legacy_unassigned_orders": thermo_leg_orders.get("", 0),
            "legacy_named_genera": len([k for k in thermo_leg_genera if k]),
            "legacy_unassigned_genera": thermo_leg_genera.get("", 0),
        },
    }
    return reconciliation_rows, summary


def validate_cohort_joins_and_counts(
    libraries: list[dict[str, str]],
    shotgun_cohorts: list[dict[str, str]],
    amplicon_1186: list[dict[str, str]],
    site_dunes: list[dict[str, str]],
    shotgun_qc_source: list[dict[str, str]],
    legacy_150_rows: list[dict[str, str]],
    representatives: list[dict[str, str]],
    ena_genomes: list[dict[str, str]],
    wgs_runs: list[dict[str, str]],
    manifest: dict,
) -> None:
    """Fail-closed validation of joins, member sets, counts, quality boundaries, and product versions."""
    if len(libraries) != 551:
        raise ValueError(f"expected 551 canonical shotgun libraries, got {len(libraries)}")
    if len(shotgun_cohorts) != 551:
        raise ValueError(f"expected 551 shotgun cohort rows, got {len(shotgun_cohorts)}")
    if len(amplicon_1186) != 1186:
        raise ValueError(f"expected 1186 deduplicated amplicon rows, got {len(amplicon_1186)}")
    if len(site_dunes) != 60:
        raise ValueError(f"expected 60 primary site dune rows, got {len(site_dunes)}")
    if len(shotgun_qc_source) != 573:
        raise ValueError(f"expected 573 CoverM matrix QC rows, got {len(shotgun_qc_source)}")
    if len(legacy_150_rows) != 150:
        raise ValueError(f"expected 150 legacy CoverM rows, got {len(legacy_150_rows)}")

    dune_by_site = {r["site"]: r["edgell_dune_type"] for r in site_dunes}
    if set(dune_by_site) != {str(i) for i in range(1, 61)}:
        raise ValueError("site_dune_zones.tsv must cover primary sites 1..60")

    amp_by_sample: dict[str, dict[str, str]] = {}
    for row in amplicon_1186:
        sid = normalize_amplicon_sample_id(row["library_id"])
        if not sid or sid in amp_by_sample:
            raise ValueError(f"duplicate or empty normalized amplicon sample ID: {sid!r}")
        site = row["site"]
        if site not in dune_by_site:
            raise ValueError(f"amplicon sample {sid} has non-primary site {site!r}")
        if row["dune_field"] != dune_by_site[site]:
            raise ValueError(
                f"amplicon sample {sid} dune_field {row['dune_field']!r} disagrees with site table {dune_by_site[site]!r}"
            )
        if row["compartment"] not in AMPLICON_COMPARTMENT_MAP:
            raise ValueError(f"unknown amplicon compartment for {sid}: {row['compartment']!r}")
        amp_by_sample[sid] = row

    qc_by_sample = {}
    for row in shotgun_qc_source:
        sid = row["sample_id"]
        if sid in qc_by_sample:
            raise ValueError(f"duplicate sample_id in shotgun_mapping_qc_source: {sid}")
        qc_by_sample[sid] = row

    legacy_150_ids = {r["sample"] for r in legacy_150_rows}
    if len(legacy_150_ids) != 150:
        raise ValueError("duplicate sample in legacy 150 table")

    lib_by_id = {}
    for row in libraries:
        sid = row["sample"]
        if sid in lib_by_id:
            raise ValueError(f"duplicate library sample: {sid}")
        lib_by_id[sid] = row

    # Independent expected member sets from staged sources
    expected_550 = {
        sid for sid in lib_by_id if qc_by_sample[sid]["nonzero_mapped"] == "True"
    }
    expected_546 = {
        sid
        for sid, lib in lib_by_id.items()
        if qc_by_sample[sid]["nonzero_mapped"] == "True"
        and lib["site"].isdigit()
        and 1 <= int(lib["site"]) <= 60
    }
    expected_545 = {
        sid for sid in expected_546 if bool(qc_by_sample[sid].get("post_qc_reads"))
    }
    expected_442 = expected_546 & set(amp_by_sample)
    expected_441 = expected_442 & expected_545

    cohort_by_id = {}
    for row in shotgun_cohorts:
        sid = row["sample"]
        if sid in cohort_by_id:
            raise ValueError(f"duplicate shotgun cohort sample: {sid}")
        if sid not in lib_by_id:
            raise ValueError(f"shotgun cohort sample absent from library_metadata: {sid}")
        lib = lib_by_id[sid]
        if (row["trip"], row["site"], row["replicate"]) != (
            lib["trip"],
            lib["site"],
            lib["replicate"],
        ):
            raise ValueError(f"specimen metadata mismatch for {sid}")
        expected_comp = CANONICAL_COMPARTMENT_MAP.get(lib["compartment"])
        if row["compartment_canonical"] != expected_comp:
            raise ValueError(
                f"compartment join mismatch for {sid}: {row['compartment_canonical']} vs {expected_comp}"
            )
        expected_dune = dune_by_site.get(lib["site"], "")
        if row["edgell_dune_type"] != expected_dune:
            raise ValueError(
                f"dune_field mismatch for {sid}: {row['edgell_dune_type']!r} vs {expected_dune!r}"
            )
        # Verify exact member identity against independent source tables (catches same-count swaps)
        if (row["in_550_nonzero_mapped"] == "1") != (sid in expected_550):
            raise ValueError(f"member mismatch in 550 nonzero cohort for {sid}")
        if (row["in_546_core_transect"] == "1") != (sid in expected_546):
            raise ValueError(f"member mismatch in 546 core cohort for {sid}")
        if (row["in_545_read_depth_model"] == "1") != (sid in expected_545):
            raise ValueError(f"member mismatch in 545 read-depth cohort for {sid}")
        if (row["in_442_amplicon_matched"] == "1") != (sid in expected_442):
            raise ValueError(f"member mismatch in 442 amplicon-matched cohort for {sid}")
        if (row["in_441_matched_read_depth_model"] == "1") != (sid in expected_441):
            raise ValueError(f"member mismatch in 441 matched model cohort for {sid}")
        if (row["in_150_legacy_coverm"] == "1") != (sid in legacy_150_ids):
            raise ValueError(f"member mismatch in 150 legacy CoverM cohort for {sid}")

        if row["in_442_amplicon_matched"] == "1":
            amp = amp_by_sample[sid]
            amp_comp = AMPLICON_COMPARTMENT_MAP[amp["compartment"]]
            if (
                amp["site"] != row["site"]
                or amp["campaign"] != row["trip"]
                or amp_comp != row["compartment_canonical"]
                or amp["replicate"] != row["replicate"]
            ):
                raise ValueError(
                    f"cross-assay specimen metadata disagreement between shotgun and amplicon for {sid}"
                )
        cohort_by_id[sid] = row

    # Verify cohort counts
    n_550 = sum(r["in_550_nonzero_mapped"] == "1" for r in shotgun_cohorts)
    n_546 = sum(r["in_546_core_transect"] == "1" for r in shotgun_cohorts)
    n_545 = sum(r["in_545_read_depth_model"] == "1" for r in shotgun_cohorts)
    n_442 = sum(r["in_442_amplicon_matched"] == "1" for r in shotgun_cohorts)
    n_441 = sum(r["in_441_matched_read_depth_model"] == "1" for r in shotgun_cohorts)
    n_150 = sum(r["in_150_legacy_coverm"] == "1" for r in shotgun_cohorts)
    n_549 = sum(r["has_primary_assembly"] == "1" for r in shotgun_cohorts)

    if (n_549, n_550, n_546, n_545, n_442, n_441, n_150) != (
        549,
        550,
        546,
        545,
        442,
        441,
        150,
    ):
        raise ValueError(
            f"altered shotgun cohort counts: {(n_549, n_550, n_546, n_545, n_442, n_441, n_150)}"
        )

    # Verify site counts per cohort
    sites_551 = {r["site"] for r in shotgun_cohorts}
    sites_546 = {r["site"] for r in shotgun_cohorts if r["in_546_core_transect"] == "1"}
    sites_442 = {r["site"] for r in shotgun_cohorts if r["in_442_amplicon_matched"] == "1"}
    if (len(sites_551), len(sites_546), len(sites_442)) != (61, 59, 58):
        raise ValueError(
            f"unexpected shotgun site counts: {(len(sites_551), len(sites_546), len(sites_442))}"
        )

    # Verify sequencing run platform and library kit counts
    if len(wgs_runs) != 554:
        raise ValueError(f"expected 554 WGS runs, got {len(wgs_runs)}")
    models = Counter(r["instrument_model"] for r in wgs_runs)
    kits = Counter(r["library_kit"] for r in wgs_runs)
    if models["Illumina NovaSeq 6000"] != 221 or models["Illumina NovaSeq X"] != 333:
        raise ValueError(f"unexpected sequencer run counts: {dict(models)}")
    if (
        kits["NEBNext Ultra II DNA Library Prep Kit (NEB)"] != 81
        or kits["QIAseq FX DNA Library UDI Kit (QIAGEN)"] != 473
    ):
        raise ValueError(f"unexpected library kit run counts: {dict(kits)}")

    # Verify MIMAG quality boundary on 5,438 representatives
    if len(representatives) != 5438:
        raise ValueError(f"expected 5438 representatives, got {len(representatives)}")
    rep_ena = {r["genome"]: r for r in ena_genomes if r["is_representative"] == "1"}
    if len(rep_ena) != 5438:
        raise ValueError(f"expected 5438 representative ENA rows, got {len(rep_ena)}")

    tier_counts = Counter()
    boundary_genomes = []
    for rep in representatives:
        mag = rep["mag"]
        if mag not in rep_ena:
            raise ValueError(f"representative missing from ENA table: {mag}")
        comp = float(rep["Completeness"])
        contam = float(rep["Contamination"])
        if classify_drep_operational(comp, contam) != "drep_included_le10":
            raise ValueError(f"representative outside dRep operational threshold: {mag}")
        tier = rep_ena[mag]["mimag_tier"]
        if contam == 10.0 and tier != "below-medium":
            raise ValueError(f"10.0% contamination genome {mag} misclassified as {tier}")
        if contam < 10.0 and tier == "below-medium":
            raise ValueError(f"<10% contamination genome {mag} misclassified as below-medium")
        tier_counts[tier] += 1
        if tier == "below-medium":
            boundary_genomes.append(mag)

    if (tier_counts["high"], tier_counts["medium"], tier_counts["below-medium"]) != (
        126,
        5311,
        1,
    ):
        raise ValueError(f"unexpected MIMAG tier counts: {dict(tier_counts)}")
    if boundary_genomes != ["48Dr2__self_SemiBin_25"]:
        raise ValueError(f"unexpected boundary genome list: {boundary_genomes}")

    # Verify protein products and CoverM versions are distinct in manifest
    products = manifest.get("products", {})
    bakta = products.get("EQ-PROT-BAKTA-v1.0.0")
    pyrodigal = products.get("EQ-PROT-PYRODIGAL-REP-v1.0.0")
    microtrait = products.get("EQ-MICROTRAIT-REP-v1.0.0")
    if not bakta or not pyrodigal or not microtrait:
        raise ValueError("missing required protein or microTrait product entries in manifest")
    if (
        bakta["protein_count"] != 19186792
        or pyrodigal["protein_count"] != 20451986
        or microtrait["protein_count"] != 20379930
    ):
        raise ValueError("altered protein product counts in manifest")
    if len({bakta["gene_caller"], pyrodigal["gene_caller"], microtrait["gene_caller"]}) != 3:
        raise ValueError("protein products conflate distinct gene callers")
    if (
        bakta.get("sequence_equivalence_with_pyrodigal") != "UNVERIFIED_SEPARATE_PRODUCTS"
        or microtrait.get("sequence_equivalence_with_bakta") != "UNVERIFIED_SEPARATE_PRODUCTS"
        or microtrait.get("sequence_equivalence_with_pyrodigal") != "UNVERIFIED_SEPARATE_PRODUCTS"
    ):
        raise ValueError("unverified protein equivalence must not be marked equivalent or passed")
    mc_ledger = microtrait.get("model_coverage_ledger", {})
    if (
        mc_ledger.get("rule_referenced_hmms_total") != 1831
        or mc_ledger.get("rule_referenced_hmms_assayed") != 1829
        or mc_ledger.get("rule_referenced_hmms_unassayed") != ["aphA", "phoN"]
        or mc_ledger.get("installed_microtrait_hmms") != 1830
        or mc_ledger.get("installed_hmms_not_in_rules") != ["phbB"]
        or mc_ledger.get("phosphatase_confirmed_positive") != 2986
        or mc_ledger.get("phosphatase_unconfirmed_safe_na") != 2452
        or mc_ledger.get("phosphatase_false_zeros") != 0
    ):
        raise ValueError(f"invalid or conflated microTrait model coverage ledger: {mc_ledger}")

    coverm_versions = {
        pid: p["version_id"]
        for pid, p in products.items()
        if p.get("product_family") == "coverm_mapping"
    }
    required_coverm = {
        "EQ-COVERM-REFINED-v1.0.0",
        "EQ-COVERM-REL-ABUND-v1.0.0",
        "EQ-COVERM-ARCHAEA-COMP-v1.0.0",
        "EQ-COVERM-LEGACY-991-v0",
    }
    if set(coverm_versions) != required_coverm or len(set(coverm_versions.values())) != 4:
        raise ValueError(f"missing or duplicate CoverM product versions: {coverm_versions}")

    # Verify frozen legacy analytical taxonomy and KO products are distinct from canonical release
    leg_tax_prod = products.get("EQ-TAX-LEGACY-ANALYTICAL-v0")
    leg_ko_prod = products.get("EQ-KO-LEGACY-ANALYTICAL-v0")
    if not leg_tax_prod or not leg_ko_prod:
        raise ValueError("missing required frozen analytical taxonomy or KO product entries")
    if leg_tax_prod.get("equivalence_with_canonical_gtdb_r232") != "FROZEN_HISTORICAL_SNAPSHOT_NOT_IDENTICAL":
        raise ValueError("legacy analytical taxonomy must not be marked identical to canonical GTDB R232")
    rec_sum = leg_tax_prod.get("reconciliation_with_canonical_gtdb_r232", {})
    expected_ranks = {
        "domain": 0,
        "phylum": 247,
        "class": 34,
        "order": 220,
        "family": 511,
        "genus": 1124,
        "species": 46,
    }
    if (
        rec_sum.get("total_representatives") != 5438
        or rec_sum.get("whole_taxonomy_strings_differing") != 1898
        or rec_sum.get("rank_differences") != expected_ranks
    ):
        raise ValueError(
            f"stale or altered taxonomy reconciliation summary in manifest: {rec_sum}"
        )
    th_sum = rec_sum.get("thermoplasmatota_reconciliation", {})
    if (
        th_sum.get("count") != 237
        or th_sum.get("whole_taxonomy_strings_differing") != 42
        or th_sum.get("canonical_classes") != {"SW-10-69-26": 185, "E2": 51, "Thermoplasmata": 1}
        or th_sum.get("canonical_named_orders") != 4
        or th_sum.get("canonical_unassigned_orders") != 2
        or th_sum.get("canonical_named_genera") != 19
        or th_sum.get("canonical_unassigned_genera") != 135
        or th_sum.get("legacy_named_orders") != 4
        or th_sum.get("legacy_unassigned_orders") != 0
        or th_sum.get("legacy_named_genera") != 14
        or th_sum.get("legacy_unassigned_genera") != 139
    ):
        raise ValueError(
            f"stale or altered Thermoplasmatota taxonomy reconciliation summary: {th_sum}"
        )
    if leg_ko_prod.get("sequence_equivalence_with_bakta") != "UNVERIFIED_SEPARATE_PRODUCTS":
        raise ValueError("legacy analytical KO matrix must not be marked equivalent to Bakta release")


def build_cohorts(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], dict]:
    libraries = read_tsv(root / "metadata/metagenome/canonical/library_metadata.tsv")
    representatives = read_tsv(root / "metadata/metagenome/canonical/refined_representatives.tsv")
    ena_genomes = read_tsv(root / "metadata/metagenome/canonical/ena_genome_accessions.tsv")
    legacy_150_rows = read_tsv(
        root / "evidence/mag-catalogue-20261024/source/metagenome_sample_meta_150.tsv"
    )
    legacy_150 = {r["sample"] for r in legacy_150_rows}
    wgs_runs = read_tsv(
        root / "evidence/mag-catalogue-20261024/source/ena_deposit/wgs_runs.tsv"
    )
    wgs_bins = {
        r["bin"]: r
        for r in read_tsv(
            root / "evidence/mag-catalogue-20261024/source/ena_deposit/wgs_bins.tsv"
        )
    }

    # Staged source inputs required for standalone rebuild (no HOME or output-as-input fallback)
    source_dir = root / "metadata/cohorts/source"
    amplicon_1186_path = source_dir / "included_samples_1186.tsv"
    site_dunes_path = source_dir / "site_dune_zones.tsv"
    shotgun_qc_path = source_dir / "shotgun_mapping_qc_source.tsv"
    arch_comp_path = source_dir / "archaeal_competitive_mapping_summary.tsv"
    legacy_tax_path = source_dir / "legacy_analytical_genome_quality.tsv"

    amplicon_1186 = read_tsv(amplicon_1186_path)
    site_dunes = read_tsv(site_dunes_path)
    shotgun_qc_source = read_tsv(shotgun_qc_path)
    arch_comp_rows = read_tsv(arch_comp_path)
    legacy_taxonomy_rows = read_tsv(legacy_tax_path)
    if not arch_comp_rows:
        raise ValueError("empty archaeal_competitive_mapping_summary.tsv")

    tax_reconcile_rows, tax_reconcile_summary = reconcile_taxonomy_snapshots(
        representatives, legacy_taxonomy_rows
    )

    dune_by_site = {r["site"]: r["edgell_dune_type"] for r in site_dunes}
    amp_by_sample = {
        normalize_amplicon_sample_id(r["library_id"]): r for r in amplicon_1186
    }
    acc_by_id = {r["sample_id"]: r for r in shotgun_qc_source}

    runs_by_sample: dict[str, list[dict[str, str]]] = {}
    for run in wgs_runs:
        runs_by_sample.setdefault(run["sample_id"], []).append(run)

    shotgun_rows = []
    for lib in sorted(libraries, key=lambda r: r["sample"]):
        sid = lib["sample"]
        acc = acc_by_id[sid]
        s_runs = sorted(runs_by_sample[sid], key=lambda r: r["ena_run"])
        platforms = ";".join(
            sorted({r["instrument_model"].replace("Illumina ", "") for r in s_runs})
        )
        kits = ";".join(
            sorted(
                {
                    "NEBNext Ultra II"
                    if "NEBNext" in r["library_kit"]
                    else "QIAseq FX"
                    for r in s_runs
                }
            )
        )
        in_550 = "1" if acc["nonzero_mapped"] == "True" else "0"
        is_primary_site = lib["site"].isdigit() and 1 <= int(lib["site"]) <= 60
        in_546 = "1" if (in_550 == "1" and is_primary_site) else "0"
        post_qc = (
            str(int(float(acc["post_qc_reads"]))) if acc.get("post_qc_reads") else ""
        )
        in_545 = "1" if (in_546 == "1" and bool(post_qc)) else "0"
        in_442 = "1" if (in_546 == "1" and sid in amp_by_sample) else "0"
        in_441 = "1" if (in_442 == "1" and bool(post_qc)) else "0"
        shotgun_rows.append(
            {
                "sample": sid,
                "trip": lib["trip"],
                "site": lib["site"],
                "compartment_raw": lib["compartment"],
                "compartment_canonical": CANONICAL_COMPARTMENT_MAP[lib["compartment"]],
                "replicate": lib["replicate"],
                "edgell_dune_type": dune_by_site.get(lib["site"], ""),
                "run_count": str(len(s_runs)),
                "sequencer_platforms": platforms,
                "library_prep_kits": kits,
                "has_primary_assembly": "1" if lib["assembly_accession"] else "0",
                "in_550_nonzero_mapped": in_550,
                "in_546_core_transect": in_546,
                "core_exclusion_reason": acc["exclusion_reason"],
                "in_545_read_depth_model": in_545,
                "in_442_amplicon_matched": in_442,
                "in_441_matched_read_depth_model": in_441,
                "in_150_legacy_coverm": "1" if sid in legacy_150 else "0",
                "post_qc_reads": post_qc,
            }
        )

    rep_ena = {r["genome"]: r for r in ena_genomes if r["is_representative"] == "1"}
    mimag_rows = []
    for rep in sorted(representatives, key=lambda r: r["mag"]):
        mag = rep["mag"]
        ena = rep_ena[mag]
        b_info = wgs_bins[mag]
        comp = float(rep["Completeness"])
        contam = float(rep["Contamination"])
        strict_tier = classify_mimag_strict(
            comp,
            contam,
            b_info["has_5S"] == "1",
            b_info["has_16S"] == "1",
            b_info["has_23s" if "has_23s" in b_info else "has_23S"] == "1",
            int(b_info["n_trna_aa"]),
        )
        if strict_tier != ena["mimag_tier"]:
            raise ValueError(
                f"MIMAG tier mismatch for {mag}: {strict_tier} vs {ena['mimag_tier']}"
            )
        drep_tier = (
            "HQ"
            if strict_tier == "high"
            else ("MQ_strict_lt10" if strict_tier == "medium" else "MQ_boundary_eq10")
        )
        mimag_rows.append(
            {
                "mag": mag,
                "sample": rep["sample"],
                "completeness": rep["Completeness"],
                "contamination": rep["Contamination"],
                "has_5S": b_info["has_5S"],
                "has_16S": b_info["has_16S"],
                "has_23S": b_info["has_23S"],
                "n_trna_aa": b_info["n_trna_aa"],
                "mimag_strict_tier": strict_tier,
                "drep_operational_class": drep_tier,
                "deposited_as_ena_mag": "1" if ena["gca_accession"] else "0",
                "binned_assembly_accession": ena["binned_assembly_accession"],
                "gca_accession": ena["gca_accession"],
            }
        )

    pkg_receipt = json.loads(
        (root / "metadata/metagenome/canonical/packaging_receipt.json").read_text()
    )
    ana_receipt = json.loads(
        (root / "metadata/metagenome/canonical/analysis_receipt.json").read_text()
    )
    ana_by_name = {a["artifact"]: a for a in ana_receipt["artifacts"]}
    rel_evidence = json.loads((root / "evidence/release/release_evidence.json").read_text())
    kg_manifest = json.loads((root / "evidence/kg-v3.0.1/manifest.json").read_text())
    ph_manifest = json.loads(
        (root / "metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1/manifest.json").read_text()
    )
    xrf_summary = json.loads(
        (root / "analysis/xrf_audit/xrf_audit_summary.json").read_text()
    )

    manifest = {
        "schema_version": "1.1.0",
        "generated_date": "2026-11-08",
        "scope_boundary_note": (
            "This shared foundation manifest covers cross-paper physical specimens, "
            "amplicon and shotgun sequencing libraries, the 5,438-representative genome "
            "catalogue, caller-specific genome protein sets, CoverM read-mapping products, "
            "and environmental/geochemical records. Newly assigned product IDs (e.g., "
            "EQ-PROT-BAKTA-v1.0.0, EQ-PROT-PYRODIGAL-REP-v1.0.0, EQ-COVERM-*) serve as "
            "manuscript and reproducibility snapshot identifiers until formal repository "
            "deposition. Downstream protein-family discovery and structural-model cohorts "
            "(106,042 recurrent dark families, 105,867 all-family ESM models with 19,620 "
            "qualified models, and the 9,644-family AlphaFold2 rescue cohort) are "
            "maintained in the companion proteome package's own analysis-cohort registry."
        ),
        "companion_manuscripts": {
            "data": {
                "role": "foundational_resource",
                "status": "working_manuscript_in_preparation",
                "title": "A linked resource of microbial genomes, community profiles and environmental data from the Rub' al-Khali",
            },
            "ecology": {
                "role": "companion_ecology_study",
                "status": "unpublished_manuscript_in_preparation",
                "citation_key": "ecology_companion",
                "title": "Microbial biogeography and functional differentiation across the Rub' al-Khali",
                "legacy_title": "Landscape-scale bacterial biogeography across the Rub' al-Khali",
            },
            "proteome": {
                "role": "companion_proteome_study",
                "status": "unpublished_manuscript_in_preparation",
                "citation_key": "proteome_companion",
                "title": "Widespread desert archaea harbour an export-enriched unknown protein repertoire",
            },
        },
        "survey_geography_and_campaigns": {
            "campaigns": 5,
            "campaign_years": "2023-2025",
            "transect_distance_km": 1043,
            "straight_line_distance_km": 1015,
            "primary_repeated_sites": 60,
            "named_single_campaign_locations": 10,
            "trip1_numeric_aliases_for_named_locations": ["61", "62", "63", "64"],
            "shotgun_site_codes_total": 61,
            "shotgun_primary_sites_present": 59,
            "shotgun_primary_sites_absent": ["56"],
            "shotgun_named_location_codes_present": ["62", "64"],
            "amplicon_quality_filtered_numeric_site_codes": 64,
        },
        "sequencing_platforms_and_kits": {
            "amplicon_16S_V3_V4": {
                "instrument": "Illumina NovaSeq 6000",
                "flowcell_and_chemistry": "SP flow cell, 500-cycle kit (2x250 bp paired-end)",
                "primers": "Bakt_341F (CCTACGGGNGGCWGCAG) / Bakt_785R (GACTACHVGGGTATCTAATCC)",
                "canonical_profiles": 1271,
            },
            "shotgun_metagenomics": {
                "read_bearing_libraries": 551,
                "paired_end_runs": 554,
                "libraries_sequenced_on_both_instruments": 3,
                "runs_by_instrument": {
                    "Illumina NovaSeq 6000": 221,
                    "Illumina NovaSeq X": 333,
                },
                "runs_by_library_kit": {
                    "NEBNext Ultra II DNA Library Prep Kit (NEB)": 81,
                    "QIAseq FX DNA Library UDI Kit (QIAGEN)": 473,
                },
                "primary_megahit_assemblies": 549,
                "libraries_with_zero_assembled_contigs": ["51Sr1", "F5Dr1"],
                "source_table": "evidence/mag-catalogue-20261024/source/ena_deposit/wgs_runs.tsv",
                "source_sha256": sha256_file(
                    root / "evidence/mag-catalogue-20261024/source/ena_deposit/wgs_runs.tsv"
                ),
                "verification_status": "VERIFIED_LOCAL",
            },
        },
        "mimag_quality_accounting": {
            "authoritative_catalogue_representatives": 5438,
            "refined_bins_passing_checkm2_50_10": 12434,
            "bacteria_representatives": 4847,
            "archaea_representatives": 591,
            "strict_mimag_tiers_lt10_contamination": {
                "high": 126,
                "medium": 5311,
                "below-medium": 1,
                "ena_deposited_gca_mags": 5437,
                "boundary_genome_at_10pct": {
                    "mag": "48Dr2__self_SemiBin_25",
                    "completeness": 64.61,
                    "contamination": 10.0,
                    "binned_assembly_accession": "ERZ29258845",
                    "binned_sample_accession": "ERS32494391",
                    "deposited_as_gca_mag": False,
                },
            },
            "drep_operational_tiers_le10_contamination": {
                "high": 126,
                "non_hq_operational_le10": 5312,
                "total_drep_representatives": 5438,
            },
            "source_tables": {
                "refined_representatives": {
                    "path": "metadata/metagenome/canonical/refined_representatives.tsv",
                    "sha256": sha256_file(
                        root / "metadata/metagenome/canonical/refined_representatives.tsv"
                    ),
                },
                "ena_genome_accessions": {
                    "path": "metadata/metagenome/canonical/ena_genome_accessions.tsv",
                    "sha256": sha256_file(
                        root / "metadata/metagenome/canonical/ena_genome_accessions.tsv"
                    ),
                },
            },
            "verification_status": "VERIFIED_LOCAL",
        },
        "cohorts": {
            "EQ-SPECIMEN-SOURCE-2550": {
                "entity_type": "source_ledger_rows",
                "count": rel_evidence["source_counts"]["all_source_rows"],
                "description": "All source specimen and control rows across Trips 1-5 (2,302 master rows including 34 controls, plus 248 plant rows).",
                "source_path": "evidence/release/sample_ledger.tsv",
                "source_sha256": sha256_file(root / "evidence/release/sample_ledger.tsv"),
                "used_by_papers": ["data"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-SPECIMEN-KG-2516": {
                "entity_type": "non_control_specimens",
                "count": rel_evidence["source_counts"]["kg_sample_eligible_rows"],
                "description": "Non-control specimen entries eligible for the RDF knowledge graph across 60 primary sites and 10 named locations.",
                "source_path": "evidence/release/sample_ledger.tsv",
                "source_sha256": sha256_file(root / "evidence/release/sample_ledger.tsv"),
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-AMP-CANONICAL-1271": {
                "entity_type": "amplicon_profiles",
                "count": 1271,
                "biological_profiles": 1247,
                "control_profiles": 24,
                "unique_field_specimen_ids": 1242,
                "asv_count": 351472,
                "description": "Unfiltered canonical nf-core/ampliseq v2.14.0 DADA2 feature table across Trips 1-5.",
                "source_path": "evidence/release/release_evidence.json",
                "source_sha256": sha256_file(root / "evidence/release/release_evidence.json"),
                "bulk_feature_table_path": "metadata/taxonomy/feature-table-trips1-5.tsv",
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-AMP-QC-1237": {
                "entity_type": "amplicon_profiles",
                "count": 1237,
                "unique_field_specimen_ids": 1209,
                "description": "Quality-filtered biological amplicon profiles after excluding 24 control profiles and 10 biological profiles with <1,000 reads (including one T1Dr1 run with 934 reads).",
                "source_path": "evidence/release/sample_ledger.tsv",
                "source_sha256": sha256_file(root / "evidence/release/sample_ledger.tsv"),
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-AMP-PRIMARY-1227": {
                "entity_type": "amplicon_profiles",
                "count": 1227,
                "sites": 60,
                "description": "Quality-filtered biological amplicon profiles restricted to the 60 primary transect sites (excluding 10 Trip 1 profiles at named sites 61-64).",
                "source_path": "evidence/release/sample_ledger.tsv",
                "source_sha256": sha256_file(root / "evidence/release/sample_ledger.tsv"),
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-AMP-DEDUP-1186": {
                "entity_type": "amplicon_profiles",
                "count": 1186,
                "sites": 60,
                "description": "Deduplicated primary-transect 16S amplicon specimen cohort used in the companion ecology statistical models.",
                "source_path": "metadata/cohorts/source/included_samples_1186.tsv",
                "source_bytes": amplicon_1186_path.stat().st_size,
                "source_sha256": sha256_file(amplicon_1186_path),
                "site_dune_table_path": "metadata/cohorts/source/site_dune_zones.tsv",
                "site_dune_table_sha256": sha256_file(site_dunes_path),
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-WGS-LIBS-551": {
                "entity_type": "shotgun_libraries",
                "count": 551,
                "runs": 554,
                "site_codes": 61,
                "primary_sites": 59,
                "named_sites": 2,
                "per_trip_counts": {"1": 210, "2": 37, "3": 128, "4": 85, "5": 91},
                "description": "Canonical read-bearing shotgun metagenomic libraries registered under ENA study PRJEB125153.",
                "source_path": "metadata/metagenome/canonical/library_metadata.tsv",
                "source_sha256": sha256_file(
                    root / "metadata/metagenome/canonical/library_metadata.tsv"
                ),
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-WGS-NONZERO-550": {
                "entity_type": "shotgun_profiles",
                "count": 550,
                "excluded_zero_mapped": ["F5Dr1"],
                "description": "Read-bearing shotgun study libraries with non-zero mapped read abundance against the 5,438-representative catalogue.",
                "source_path": "metadata/cohorts/source/shotgun_mapping_qc_source.tsv",
                "source_sha256": sha256_file(shotgun_qc_path),
                "derived_table_path": "metadata/cohorts/shotgun_cohort_accounting.tsv",
                "used_by_papers": ["data", "proteome"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-WGS-CORE-546": {
                "entity_type": "shotgun_profiles",
                "count": 546,
                "sites": 59,
                "excluded_samples": {
                    "auxiliary_location": ["62PRr2", "64Dr3", "64PRr2", "64Sr2"],
                    "zero_mapped": ["F5Dr1"],
                },
                "description": "Core-transect non-zero shotgun metagenome cohort (sites 1-60) used for genome-resolved ecological and functional integration.",
                "source_path": "metadata/cohorts/source/shotgun_mapping_qc_source.tsv",
                "source_sha256": sha256_file(shotgun_qc_path),
                "derived_table_path": "metadata/cohorts/shotgun_cohort_accounting.tsv",
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-WGS-CORE-MODEL-545": {
                "entity_type": "shotgun_profiles",
                "count": 545,
                "sites": 59,
                "excluded_missing_post_qc_reads": ["F45PRr3"],
                "description": "Core-transect shotgun cohort with post-QC read-depth metadata used in read-depth-adjusted INLA spatial models.",
                "source_path": "metadata/cohorts/source/shotgun_mapping_qc_source.tsv",
                "source_sha256": sha256_file(shotgun_qc_path),
                "derived_table_path": "metadata/cohorts/shotgun_cohort_accounting.tsv",
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-MATCHED-AMP-WGS-442": {
                "entity_type": "paired_amplicon_shotgun_specimens",
                "count": 442,
                "sites": 58,
                "description": "Exact specimen-matched intersection of the 546 core shotgun metagenomes and the 1,186 deduplicated primary-transect 16S profiles, verified on site, campaign, compartment, replicate, and dune-field classification.",
                "source_paths": [
                    "metadata/cohorts/source/shotgun_mapping_qc_source.tsv",
                    "metadata/cohorts/source/included_samples_1186.tsv",
                    "metadata/cohorts/source/site_dune_zones.tsv",
                ],
                "source_sha256": {
                    "shotgun_mapping_qc_source.tsv": sha256_file(shotgun_qc_path),
                    "included_samples_1186.tsv": sha256_file(amplicon_1186_path),
                    "site_dune_zones.tsv": sha256_file(site_dunes_path),
                },
                "derived_table_path": "metadata/cohorts/shotgun_cohort_accounting.tsv",
                "picrust2_mag_ko_overlap": {
                    "shared_ko_count": 8860,
                    "integration_summary_sha256": "ec8ff4322df2cf8fb8c92ebdd78b2e26802b7b1f19a95cf5e018bc678d025120",
                    "full_ko_matrices_verification_status": "UNVERIFIED_REMOTE",
                },
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-MATCHED-MODEL-441": {
                "entity_type": "paired_amplicon_shotgun_specimens",
                "count": 441,
                "sites": 58,
                "excluded_missing_post_qc_reads": ["F45PRr3"],
                "description": "Exact specimen-matched amplicon-shotgun cohort with post-QC read-depth metadata used in read-depth-adjusted spatial models.",
                "source_paths": [
                    "metadata/cohorts/source/shotgun_mapping_qc_source.tsv",
                    "metadata/cohorts/source/included_samples_1186.tsv",
                ],
                "source_sha256": {
                    "shotgun_mapping_qc_source.tsv": sha256_file(shotgun_qc_path),
                    "included_samples_1186.tsv": sha256_file(amplicon_1186_path),
                },
                "derived_table_path": "metadata/cohorts/shotgun_cohort_accounting.tsv",
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-WGS-ARCHAEA-PAIRED-193": {
                "entity_type": "paired_compartment_shotgun_profiles",
                "count": 193,
                "paired_visits": 68,
                "sites": 36,
                "description": "Paired surface/subsurface/root-adjacent shotgun profiles across 68 site-campaign visits (36 sites) used in competitive archaeal read mapping.",
                "summary_table_path": "metadata/cohorts/source/archaeal_competitive_mapping_summary.tsv",
                "summary_table_sha256": sha256_file(arch_comp_path),
                "per_profile_bam_verification_status": "UNVERIFIED_REMOTE",
                "used_by_papers": ["proteome"],
                "verification_status": "FROZEN_EVIDENCE_SUMMARY_ONLY",
            },
            "EQ-WGS-LEGACY-150": {
                "entity_type": "historical_shotgun_profiles",
                "count": 150,
                "per_trip_counts": {"1": 58, "2": 15, "3": 77},
                "legacy_genome_catalogue_count": 991,
                "legacy_annotated_ko_genomes": 990,
                "description": "Historical Trips 1-3 CoverM relative-abundance subset against the superseded 991-genome pre-release catalogue; retained strictly for provenance.",
                "source_path": "evidence/mag-catalogue-20261024/source/metagenome_sample_meta_150.tsv",
                "source_sha256": sha256_file(
                    root / "evidence/mag-catalogue-20261024/source/metagenome_sample_meta_150.tsv"
                ),
                "used_by_papers": ["data"],
                "verification_status": "VERIFIED_LOCAL",
            },
        },
        "products": {
            "EQ-KG-ASSERTED-v3.0.1": {
                "product_family": "knowledge_graph",
                "version_id": "3.0.1",
                "zenodo_doi": "10.5281/zenodo.23134168",
                "modules": 16,
                "asserted_triples": kg_manifest["counts"]["asserted"],
                "source_path": "evidence/kg-v3.0.1/manifest.json",
                "source_sha256": sha256_file(root / "evidence/kg-v3.0.1/manifest.json"),
                "used_by_papers": ["data"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-MAG-REFINED-v1.0.0": {
                "product_family": "genome_catalogue",
                "version_id": "EQ-MAG-REFINED-v1.0.0",
                "representatives": 5438,
                "total_contigs": pkg_receipt["contigs"],
                "total_bases": pkg_receipt["bases"],
                "archive_path": "metadata/metagenome/canonical/refined_mags.tar.gz",
                "archive_bytes": pkg_receipt["bytes"],
                "archive_sha256": pkg_receipt["sha256"],
                "manifest_path": "metadata/metagenome/canonical/genome_manifest.tsv",
                "manifest_sha256": sha256_file(
                    root / "metadata/metagenome/canonical/genome_manifest.tsv"
                ),
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-PROT-BAKTA-v1.0.0": {
                "product_family": "protein_annotations",
                "version_id": "EQ-PROT-BAKTA-v1.0.0",
                "source_genomes": 5438,
                "gene_caller": "Bakta v1.12.0 (database v6.0, 2025-02-24)",
                "functional_annotator": "eggNOG-mapper v2.1.13 (eggNOG v5.0.2, DIAMOND v2.0.15)",
                "protein_count": 19186792,
                "eggnog_annotated_proteins": 16119759,
                "proteins_with_ko": 8516493,
                "distinct_kos": 11386,
                "distinct_pfams": 9703,
                "distinct_cazy": 141,
                "archive_path": "metadata/metagenome/canonical/refined_functional_tables.tar.gz",
                "archive_bytes": ana_by_name["refined_functional_tables.tar.gz"]["bytes"],
                "archive_sha256": ana_by_name["refined_functional_tables.tar.gz"]["sha256"],
                "sequence_equivalence_with_pyrodigal": "UNVERIFIED_SEPARATE_PRODUCTS",
                "provenance_note": "Predicted by Bakta v1.12.0 on the 5,438 refined representative FASTAs (refined_mags.tar.gz). Distinct from the 20,451,986 Pyrodigal representative protein set associated with the same 5,438 representative genome identifiers; matching genome identifiers do not establish identical underlying FASTA sequence contents or retained contig coordinates, and sequence equivalence must not be asserted without per-locus reconciliation.",
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-PROT-PYRODIGAL-REP-v1.0.0": {
                "product_family": "protein_sequences",
                "version_id": "EQ-PROT-PYRODIGAL-REP-v1.0.0",
                "source_genomes": 5438,
                "gene_caller": "Pyrodigal (single-genome mode with meta fallback on fragmented bins)",
                "protein_count": 20451986,
                "concatenated_faa_logical_uri": "ibex://c2014/rob/metagenomics/06_darkmatter/orthogroups/all_rep_proteins.faa",
                "concatenated_faa_bytes": 9269718729,
                "concatenated_faa_sha256": "32f776acca82e1e4c48a0f3f8f2d950cbd2d75e48518d754655baba3520e6cf2",
                "reconciliation_with_assembly_catalogue": {
                    "assembly_catalogue_total_proteins": 753305533,
                    "assembly_catalogue_bin_mapped_proteins": 20379930,
                    "identical_locus_and_sequence": 18831742,
                    "locus_variants": 1236920,
                    "exact_sequence_elsewhere": 147640,
                    "unmapped_to_assembly_catalogue": 235684,
                    "dark_fraction_primary": 0.071022,
                    "dark_fraction_strict": 0.069264,
                },
                "sequence_equivalence_with_bakta": "UNVERIFIED_SEPARATE_PRODUCTS",
                "provenance_note": "Per-representative Pyrodigal protein calls associated with the same 5,438 representative genome identifiers, used for MMseqs2 50/80 orthogroups, the 106-profile microTrait HMM functional screen, and protein-family discovery screens. Matching genome identifiers do not establish identical underlying FASTA sequence contents or retained contig coordinates, and this product is maintained separately from EQ-PROT-BAKTA-v1.0.0.",
                "used_by_papers": ["ecology", "proteome"],
                "verification_status": "UNVERIFIED_REMOTE",
            },
            "EQ-COVERM-REFINED-v1.0.0": {
                "product_family": "coverm_mapping",
                "version_id": "EQ-COVERM-REFINED-v1.0.0",
                "libraries": 551,
                "reference_genomes": 5438,
                "reference_contigs": pkg_receipt["contigs"],
                "aligner": "Bowtie2 v2.5.1 (--very-sensitive, first 200M read pairs cap); SAMtools v1.16.1",
                "quantifier": "CoverM v0.6.1 (--min-read-percent-identity 95, --min-covered-fraction 0)",
                "metrics_reported": [
                    "Mean",
                    "Covered Fraction",
                    "Trimmed Mean",
                    "Read Count",
                    "Length",
                ],
                "archive_path": "metadata/metagenome/canonical/refined_coverm_profiles.tar.gz",
                "archive_bytes": ana_by_name["refined_coverm_profiles.tar.gz"]["bytes"],
                "archive_sha256": ana_by_name["refined_coverm_profiles.tar.gz"]["sha256"],
                "used_by_papers": ["data"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-COVERM-REL-ABUND-v1.0.0": {
                "product_family": "coverm_mapping",
                "version_id": "EQ-COVERM-REL-ABUND-v1.0.0",
                "matrix_profiles": 573,
                "canonical_study_libraries": 551,
                "nonzero_study_libraries": 550,
                "core_transect_profiles": 546,
                "core_read_depth_model_profiles": 545,
                "matched_amplicon_profiles": 442,
                "matched_read_depth_model_profiles": 441,
                "reference_genomes": 5438,
                "quantifier": "CoverM v0.7.0 genome relative abundance with unmapped fraction",
                "staged_qc_table_path": "metadata/cohorts/source/shotgun_mapping_qc_source.tsv",
                "staged_qc_table_sha256": sha256_file(shotgun_qc_path),
                "matrix_logical_uri": "shaheen://k10018/eq-ecology-mag-20261105/rebuild_20260729/picrust2_current_20260803/mag_ko/sample_by_mag_coverm_relative_abundance.npz",
                "matrix_bytes": 4097175,
                "matrix_sha256": "7878362692a1fc008077e605cb1cc6ea191b85efb1d1cf590a191dd435336110",
                "sample_index_sha256": "7d8e6e3e29dca5640f345f1fd8e8770d3536694551062e6089a27b6286265f60",
                "full_matrix_verification_status": "UNVERIFIED_REMOTE",
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "VERIFIED_LOCAL_TABLE_REMOTE_MATRIX",
            },
            "EQ-COVERM-ARCHAEA-COMP-v1.0.0": {
                "product_family": "coverm_mapping",
                "version_id": "EQ-COVERM-ARCHAEA-COMP-v1.0.0",
                "paired_profiles": 193,
                "paired_visits": 68,
                "sites": 36,
                "reference_genomes": 5739,
                "reference_composition": "5,438 Rub' al-Khali representatives + 301 external Thermoplasmatota reference genomes",
                "primary_quantifier": "Competitive read mapping (>=95% identity, >=75% aligned length) evaluated across primary covered-fraction breadth gates (0%, 10%, 20%, and 50%)",
                "mapq20_sensitivity_mode": "Separate sensitivity analysis restricting alignments to MAPQ >= 20 (evaluated at 0% and 10% breadth); not applied as a filter to every primary breadth-gated result",
                "summary_table_path": "metadata/cohorts/source/archaeal_competitive_mapping_summary.tsv",
                "summary_table_sha256": sha256_file(arch_comp_path),
                "per_profile_bam_verification_status": "UNVERIFIED_REMOTE",
                "used_by_papers": ["proteome"],
                "verification_status": "FROZEN_EVIDENCE_SUMMARY_ONLY",
            },
            "EQ-COVERM-LEGACY-991-v0": {
                "product_family": "coverm_mapping",
                "version_id": "EQ-COVERM-LEGACY-991-v0",
                "libraries": 150,
                "reference_genomes": 991,
                "annotated_ko_genomes": 990,
                "archive_path": "metadata/metagenome/coverm_profiles.tar.gz",
                "archive_sha256": sha256_file(root / "metadata/metagenome/coverm_profiles.tar.gz"),
                "annotations_path": "metadata/metagenome/eq.emapper.annotations.gz",
                "annotations_sha256": sha256_file(
                    root / "metadata/metagenome/eq.emapper.annotations.gz"
                ),
                "measured_function_inputs_path": "metadata/metagenome/measured_function_inputs.tar.gz",
                "measured_function_inputs_sha256": sha256_file(
                    root / "metadata/metagenome/measured_function_inputs.tar.gz"
                ),
                "provenance_note": "Historical Trips 1-3 subset against the superseded 991-genome pre-release catalogue; never combine with the 5,438-representative catalogue.",
                "used_by_papers": ["data"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-PH-SHARED-v1.0.1": {
                "product_family": "soil_chemistry",
                "version_id": "EQ-PH-SHARED-v1.0.1",
                "admitted_measurements": 712,
                "recorded_measurements": 767,
                "quarantined_date_provenance": 36,
                "quarantined_qc": 19,
                "trip4_replicate2_reconciled": 156,
                "source_path": "metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1/manifest.json",
                "source_sha256": sha256_file(
                    root / "metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1/manifest.json"
                ),
                "workbook_sha256": ph_manifest["source"]["sha256"],
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-XRF-CANONICAL-v1.0.0": {
                "product_family": "soil_geochemistry",
                "version_id": "EQ-XRF-CANONICAL-v1.0.0",
                "field_log_rows": xrf_summary["counts"]["field_log_rows"],
                "field_log_sites": xrf_summary["counts"]["field_log_sites"],
                "field_complete_sessions": xrf_summary["counts"]["field_complete_sessions"],
                "field_sites": xrf_summary["counts"]["field_sites"],
                "lab_canonical_records": xrf_summary["counts"]["lab_all_canonical"],
                "reporting_channels": 93,
                "chebi_mapped_channels": 79,
                "pubchem_mapped_channels": 91,
                "source_path": "analysis/xrf_audit/xrf_audit_summary.json",
                "source_sha256": sha256_file(root / "analysis/xrf_audit/xrf_audit_summary.json"),
                "used_by_papers": ["data", "ecology"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-TAX-LEGACY-ANALYTICAL-v0": {
                "product_family": "genome_taxonomy_snapshot",
                "version_id": "EQ-TAX-LEGACY-ANALYTICAL-v0",
                "source_genomes": 5438,
                "staged_source_path": "metadata/cohorts/source/legacy_analytical_genome_quality.tsv",
                "staged_source_sha256": sha256_file(legacy_tax_path),
                "reconciliation_table_path": "metadata/cohorts/taxonomy_snapshot_reconciliation.tsv",
                "equivalence_with_canonical_gtdb_r232": "FROZEN_HISTORICAL_SNAPSHOT_NOT_IDENTICAL",
                "reconciliation_with_canonical_gtdb_r232": tax_reconcile_summary,
                "provenance_note": "Frozen analytical taxonomy snapshot used in the historical genome-resolved genus/order turnover and proteome scripts across the same 5,438 representative genome identifiers and identical CheckM2 quality metrics. Differs from canonical GTDB-Tk v2.7.2 / GTDB R232 strings on 1,898 of 5,438 genomes (0 domain, 247 phylum, 34 class, 220 order, 511 family, 1,124 genus, 46 species); maintained strictly as an analytical provenance record and never substituted for canonical gtdb_r232_classification.",
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "VERIFIED_LOCAL",
            },
            "EQ-KO-LEGACY-ANALYTICAL-v0": {
                "product_family": "functional_ko_matrix",
                "version_id": "EQ-KO-LEGACY-ANALYTICAL-v0",
                "source_genomes": 5438,
                "distinct_kos": 11386,
                "shared_kos_with_picrust2": 8860,
                "upstream_logical_uri": "ibex://c2014/rob/metagenomics/04_functional/repko_clean/results/rep_ko_v2.tsv",
                "sparse_matrix_logical_uri": "shaheen://k10018/eq-ecology-mag-20261105/rebuild_20260729/picrust2_current_20260803/mag_ko/mag_by_ko_presence_or_copy.npz",
                "sequence_equivalence_with_bakta": "UNVERIFIED_SEPARATE_PRODUCTS",
                "provenance_note": "Frozen analytical KO matrix (rep_ko_v2.tsv) used for genome-resolved KO richness/Shannon and PICRUSt2 concordance projections in the companion ecology and proteome studies. Upstream caller and database versions are not asserted equivalent to the canonical 19,186,792-protein Bakta v1.12.0 / eggNOG-mapper v2.1.13 release product (EQ-PROT-BAKTA-v1.0.0) without byte- and locus-level reconciliation.",
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "UNVERIFIED_REMOTE",
            },
            "EQ-MICROTRAIT-REP-v1.0.0": {
                "product_family": "trait_matrices_and_predictors",
                "version_id": "EQ-MICROTRAIT-REP-v1.0.0",
                "source_genomes": 5438,
                "gene_caller": "Prodigal v2.6.3 (-p meta, fresh upstream extract.traits invocation)",
                "protein_count": 20379930,
                "total_bases": 20490828267,
                "package_dir": "analysis/microtrait_20261110",
                "granularity1_matrix_path": "analysis/microtrait_20261110/results/trait_matrixatgranularity1.tsv.gz",
                "granularity1_matrix_sha256": sha256_file(
                    root / "analysis/microtrait_20261110/results/trait_matrixatgranularity1.tsv.gz"
                ),
                "granularity2_matrix_path": "analysis/microtrait_20261110/results/trait_matrixatgranularity2.tsv.gz",
                "granularity2_matrix_sha256": sha256_file(
                    root / "analysis/microtrait_20261110/results/trait_matrixatgranularity2.tsv.gz"
                ),
                "granularity3_matrix_path": "analysis/microtrait_20261110/results/trait_matrixatgranularity3.tsv.gz",
                "granularity3_matrix_sha256": sha256_file(
                    root / "analysis/microtrait_20261110/results/trait_matrixatgranularity3.tsv.gz"
                ),
                "rule_matrix_path": "analysis/microtrait_20261110/results/rule_matrix.tsv.gz",
                "rule_matrix_sha256": sha256_file(
                    root / "analysis/microtrait_20261110/results/rule_matrix.tsv.gz"
                ),
                "hmm_matrix_path": "analysis/microtrait_20261110/results/hmm_matrix.tsv.gz",
                "hmm_matrix_sha256": sha256_file(
                    root / "analysis/microtrait_20261110/results/hmm_matrix.tsv.gz"
                ),
                "growth_and_ogt_predictions_path": "analysis/microtrait_20261110/results/growth_and_ogt_predictions_5438.tsv",
                "growth_and_ogt_predictions_sha256": sha256_file(
                    root / "analysis/microtrait_20261110/results/growth_and_ogt_predictions_5438.tsv"
                ),
                "phosphatase_coverage_path": "analysis/microtrait_20261110/results/phosphatase_and_model_coverage_5438.tsv",
                "phosphatase_coverage_sha256": sha256_file(
                    root / "analysis/microtrait_20261110/results/phosphatase_and_model_coverage_5438.tsv"
                ),
                "model_coverage_ledger": {
                    "rule_referenced_hmms_total": 1831,
                    "rule_referenced_hmms_assayed": 1829,
                    "rule_referenced_hmms_unassayed": ["aphA", "phoN"],
                    "installed_microtrait_hmms": 1830,
                    "microtrait_db_models": 1789,
                    "dbcan_v14_gh_models": 41,
                    "installed_hmms_not_in_rules": ["phbB"],
                    "hmmer_version": "3.3.2",
                    "dbcan_version": "V14",
                    "dbcan_sha256": "396c791fb13defab152864d8046687ef03b492937ec6f9bbab008bc77cbaa7a5",
                    "dbcan_pressed_sha256": "0bcd0ab0c06baebc2b3960e38e1b2f4c5a2c8357780a094be79d641ecf720070",
                    "phosphatase_confirmed_positive": 2986,
                    "phosphatase_unconfirmed_safe_na": 2452,
                    "phosphatase_false_zeros": 0,
                },
                "sequence_equivalence_with_bakta": "UNVERIFIED_SEPARATE_PRODUCTS",
                "sequence_equivalence_with_pyrodigal": "UNVERIFIED_SEPARATE_PRODUCTS",
                "provenance_note": "Full-catalogue microTrait v1.0.0 trait/rule/HMM matrices and gRodon/optimalT continuous predictors across all 5,438 canonical representatives, computed on Shaheen III using dbCAN-HMMdb-V14. Upstream microtrait::extract.traits invokes fresh Prodigal v2.6.3 (-p meta) yielding 20,379,930 predicted ORFs, which is distinct from both the 19,186,792 Bakta v1.12.0 CDS product (EQ-PROT-BAKTA-v1.0.0) and the 20,451,986 Pyrodigal representative protein product (EQ-PROT-PYRODIGAL-REP-v1.0.0). Because aphA and phoN HMMs are absent from the upstream Zenodo microTrait HMM archive, 2,986 MAGs with phoA/phoD/phoX hits are recorded as confirmed phosphatase-positive (1) and 2,452 MAGs without phoA/phoD/phoX hits are recorded as safe NA (never coerced to 0).",
                "used_by_papers": ["data", "ecology", "proteome"],
                "verification_status": "VERIFIED_LOCAL",
            },
        },
        "unresolved_and_pending_items": [
            {
                "id": "UNRESOLVED-PROT-CALLER-RECONCILIATION",
                "status": "UNVERIFIED_SEPARATE_PRODUCTS",
                "description": "Direct locus-by-locus sequence reconciliation between the 19,186,792 Bakta v1.12.0 proteins (EQ-PROT-BAKTA-v1.0.0) and the 20,451,986 Pyrodigal per-representative proteins (EQ-PROT-PYRODIGAL-REP-v1.0.0) associated with the same 5,438 representative genome identifiers has not been executed; matching genome identifiers do not establish identical underlying FASTA sequence contents or retained contig coordinates, and both products remain strictly separate.",
            },
            {
                "id": "TAXONOMY-SNAPSHOT-SENSITIVITY",
                "status": "PENDING_CANONICAL_REPLAY",
                "description": "Canonical GTDB-Tk v2.7.2 / GTDB R232 taxonomy (refined_representatives.tsv) and the frozen analytical taxonomy snapshot (EQ-TAX-LEGACY-ANALYTICAL-v0) share the same 5,438 genome identifiers, identical CheckM2 quality metrics, and the exact same 237 Thermoplasmatota genomes, but differ on 1,898 whole strings (1,124 genus, 220 order). Re-running genus/order turnover decompositions and lineage summaries under canonical gtdb_r232_classification is tracked as a pending sensitivity audit.",
            },
            {
                "id": "UNVERIFIED-REMOTE-FULL-NPZ-AND-COMPETITIVE-BAMS",
                "status": "UNVERIFIED_REMOTE",
                "description": "The 9.27 GB concatenated Pyrodigal representative FASTA, the sparse .npz relative-abundance/KO matrices on Shaheen, and the per-profile competitive archaeal BAMs reside on remote HPC storage and are represented locally by their recorded SHA-256 digests and staged summary tables.",
            },
            {
                "id": "PENDING-ENA-STUDY-PUBLIC-RELEASE",
                "status": "PENDING_PUBLIC_RELEASE",
                "description": "ENA shotgun study PRJEB125153 (551 libraries, 554 runs, 549 primary assemblies, 12,434 binned metagenomes, 5,437 GCA MAGs) is accessioned and scheduled for public release on 2026-11-25.",
            },
            {
                "id": "PENDING-BULK-ZENODO-DOI-MINTING",
                "status": "PENDING_PUBLIC_RELEASE",
                "description": "Private-staging bulk archives (refined_mags.tar.gz, refined_functional_tables.tar.gz, refined_coverm_profiles.tar.gz) are checksum-verified and staged for Zenodo deposition prior to publication.",
            },
        ],
    }

    validate_cohort_joins_and_counts(
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        manifest,
    )
    manifest["_taxonomy_reconciliation_rows"] = tax_reconcile_rows
    return shotgun_rows, mimag_rows, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--sync-submission-evidence",
        type=Path,
        default=None,
        help="Optional manuscript submission-evidence directory to synchronize",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    shotgun_rows, mimag_rows, manifest = build_cohorts(root)
    tax_reconcile_rows = manifest.pop("_taxonomy_reconciliation_rows")
    cohorts_dir = root / "metadata/cohorts"
    cohorts_dir.mkdir(parents=True, exist_ok=True)

    shotgun_path = cohorts_dir / "shotgun_cohort_accounting.tsv"
    mimag_path = cohorts_dir / "mimag_quality_boundary.tsv"
    tax_rec_path = cohorts_dir / "taxonomy_snapshot_reconciliation.tsv"
    manifest_path = cohorts_dir / "cohort_product_manifest.json"

    write_tsv(shotgun_path, shotgun_rows)
    write_tsv(mimag_path, mimag_rows)
    write_tsv(tax_rec_path, tax_reconcile_rows)
    manifest["products"]["EQ-TAX-LEGACY-ANALYTICAL-v0"]["reconciliation_table_sha256"] = (
        sha256_file(tax_rec_path)
    )
    manifest["cohort_tables_sha256"] = {
        "metadata/cohorts/shotgun_cohort_accounting.tsv": sha256_file(shotgun_path),
        "metadata/cohorts/mimag_quality_boundary.tsv": sha256_file(mimag_path),
        "metadata/cohorts/taxonomy_snapshot_reconciliation.tsv": sha256_file(tax_rec_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if args.sync_submission_evidence is not None:
        sub_dir = args.sync_submission_evidence.resolve()
        sub_dir.mkdir(parents=True, exist_ok=True)
        for src in (shotgun_path, mimag_path, tax_rec_path, manifest_path):
            (sub_dir / src.name).write_bytes(src.read_bytes())

    print(
        json.dumps(
            {
                "status": "PASS",
                "shotgun_libraries": len(shotgun_rows),
                "core_546": sum(r["in_546_core_transect"] == "1" for r in shotgun_rows),
                "model_545": sum(r["in_545_read_depth_model"] == "1" for r in shotgun_rows),
                "matched_442": sum(r["in_442_amplicon_matched"] == "1" for r in shotgun_rows),
                "matched_model_441": sum(
                    r["in_441_matched_read_depth_model"] == "1" for r in shotgun_rows
                ),
                "mimag_representatives": len(mimag_rows),
                "taxonomy_reconciled_genomes": len(tax_reconcile_rows),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
