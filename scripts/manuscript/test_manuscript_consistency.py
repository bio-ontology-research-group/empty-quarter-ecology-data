#!/usr/bin/env python3
"""Regression checks for high-risk manuscript/resource inconsistencies."""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve()
if SCRIPT.parent.name == "manuscript":
    # Standalone reproducibility repository: manuscript sources live in
    # paper/, while the release candidate is the repository root.
    PROJECT_ROOT = SCRIPT.parents[2]
    ROOT = PROJECT_ROOT / "paper"
    STAGE = PROJECT_ROOT
    MANUSCRIPT_SCRIPTS = PROJECT_ROOT / "scripts" / "manuscript"
else:
    # Historical monorepo layout retained by the upstream working tree.
    ROOT = SCRIPT.parents[1]
    PROJECT_ROOT = ROOT.parent
    STAGE = ROOT / "zenodo"
    MANUSCRIPT_SCRIPTS = ROOT / "scripts"


class ManuscriptConsistencyTest(unittest.TestCase):
    def text(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def prose(self, name: str) -> str:
        """Ignore line wrapping and full-line editorial comments, not scientific text."""
        return " ".join(re.sub(r"(?m)^\s*%.*$", "", self.text(name)).split())

    def test_bibliography_keys_are_unique(self) -> None:
        bib = self.text("sn-bibliography.bib")
        keys = re.findall(r"^@\w+\{([^,]+),", bib, flags=re.MULTILINE)
        lowered = [key.casefold() for key in keys]
        duplicates = sorted({key for key in lowered if lowered.count(key) > 1})
        self.assertEqual([], duplicates)

    def test_confirmed_author_order_and_affiliations(self) -> None:
        source = self.text("sn-article.tex")
        authors = re.findall(
            r"^\\author\*?\[([0-9]+)\]\{\\fnm\{([^{}]+)\} "
            r"\\sur\{([^{}]+)\}\}",
            source,
            re.MULTILINE,
        )
        expected = [
            ("1", "Rund", "Tawfiq"),
            ("1", "Marwa", "Abdelhakim"),
            ("3", "Sulaiman M.", "Alajel"),
            ("1", "Mohammed", "Alarawi"),
            ("8", "Hind", "Aldakhil"),
            ("1", "Abderahmane", "Derouiche"),
            ("4", "Daniela I.", "Drautz-Moses"),
            ("7", "Michel", "Dumontier"),
            ("6", "Raik", r"Gr\"unberg"),
            ("1", "Alejandra", "Lopez-Velazquez"),
            ("2", "Susana", "Martinez Arbas"),
            ("1", "Kexin", "Niu"),
            ("1", "Krishnakumar", "Sivakumar"),
            ("5", "Tiannyu", "Wang"),
            ("4", "Xiang", "Zhao"),
            ("1", "Jood", "Zubair"),
            ("5", "Magnus", "Rueping"),
            ("1", "Robert", "Hoehndorf"),
        ]
        # Affiliation numbers are presentation identifiers. Preserve each
        # author's order and actual institutional association through renumbering.
        self.assertEqual([row[1:] for row in expected], [row[1:] for row in authors])
        affiliations = dict(re.findall(r"(?m)^\\affil\*?\[([0-9]+)\](.*)$", source))
        institution = {
            "1": "Bio-Ontology Research Group", "2": "NIUM",
            "3": "Ministry of Environment, Water and Agriculture",
            "4": "Bioscience Core Lab", "5": "Physical Science and Engineering",
            "6": "Biomedical Sciences Division", "7": "Maastricht University",
            "8": "National Livestock",
        }
        for prior, current in zip(expected, authors):
            self.assertIn(current[0], affiliations)
            self.assertIn(institution[prior[0]], affiliations[current[0]])
        source = " ".join(source.split())
        self.assertIn("Bio-Ontology Research Group (BORG)", source)
        self.assertIn("Physical Science and Engineering (PSE) Division", source)
        self.assertIn("Biomedical Sciences Division (BioMed)", source)
        self.assertIn(
            "National Livestock \\& Fisheries Development Program (NLFDP)",
            source,
        )
        self.assertIn(
            "Institute of Data Science, Department of Advanced Computing",
            source,
        )

    def test_supplement_listings_can_wrap_long_iris(self) -> None:
        supplement = self.text("supplement.tex")
        self.assertIn("columns=fullflexible", supplement)

    def test_staged_amplicon_protocol_matches_corrected_canonical_record(self) -> None:
        relative = Path(
            "metadata/protocols/lib_prep/16S_amplicon_lib_prep.md"
        )
        canonical = PROJECT_ROOT / "data" / relative
        staged = STAGE / relative
        self.assertEqual(canonical.read_bytes(), staged.read_bytes())
        payload = canonical.read_text(encoding="utf-8")
        self.assertIn("Bakt_785R: GACTACHVGGGTATCTAATCC", payload)
        self.assertIn("Klindworth et al. 2013", payload)
        self.assertNotRegex(payload, r"(?m)^\s+reverse:\s+806R\s*$")

    def test_bibliography_custody_matches_the_current_candidate(self) -> None:
        bib = ROOT / "sn-bibliography.bib"
        custody = json.loads(
            (
                ROOT
                / "zenodo/evidence/bibliography/source_custody.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            hashlib.sha256(bib.read_bytes()).hexdigest(),
            custody["bibliography_sha256"],
        )
        cited = set()
        cite_re = re.compile(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]*)\}")
        for name in (
            "sn-article.tex",
            "01_introduction.tex",
            "02_methods.tex",
            "02_methods_taxonomy.tex",
            "03_knowledge_representation.tex",
            "04_data_records.tex",
            "05_validation.tex",
            "06_usage.tex",
            "supplement.tex",
            "kr_supplement.tex",
            "env_table.tex",
            "xrf_table.tex",
        ):
            for match in cite_re.finditer(self.text(name)):
                cited.update(
                    key.strip()
                    for key in match.group(1).split(",")
                    if key.strip()
                )
        self.assertEqual(len(cited), custody["cited_keys"])

    def test_climate_acquisitions_are_described_separately(self) -> None:
        methods = self.text("02_methods.tex")
        frozen = json.loads(
            (
                ROOT
                / "zenodo/metadata/climate/climate_acquisition_frozen.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("two\nseparately configured acquisitions", methods)
        self.assertIn("20~January 2026", methods)
        self.assertIn("1~February 2026", methods)
        self.assertIn("reports temperature, total precipitation and rainfall", self.prose("02_methods.tex"))
        self.assertEqual(
            "2026-01-20",
            frozen["monthly"]["declared_window"]["end_date"],
        )
        self.assertEqual(
            "2026-02-01",
            frozen["daily"]["declared_window"]["end_date"],
        )
        self.assertIn(
            "relative_humidity_2m_mean",
            frozen["monthly"]["declared_window"]["daily_variables"],
        )
        self.assertNotIn(
            "relative_humidity_2m_mean",
            frozen["daily"]["declared_window"]["daily_variables"],
        )

    def test_path_disclosure_allowlist_covers_checksummed_provenance(self) -> None:
        builder = (MANUSCRIPT_SCRIPTS / "build_reviewer_package.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Scan every payload as", builder)
        self.assertIn("scan_for_absolute_paths(path)", builder)
        self.assertIn("(?:home|ibex|scratch|mnt)", builder)
        self.assertIn(
            "evidence/semantic-validation/semantic_validation_20260801.log",
            builder,
        )
        self.assertIn(
            "local generated-module and ontology",
            builder,
        )

    def test_retired_identifier_mistakes_are_absent(self) -> None:
        source = "\n".join(
            self.text(name)
            for name in (
                "02_methods_taxonomy.tex",
                "03_knowledge_representation.tex",
                "05_validation.tex",
            )
        )
        self.assertNotRegex(
            source,
            r"rak:2000021\s+[\?\"](?:count|15)",
            "RAK_2000021 is monthly mean temperature, not absolute abundance",
        )
        self.assertNotRegex(
            source,
            r"a\s+rak:0000064\s*;\s*#\s*(?:FASTQ|Sequencing)",
            "RAK_0000064 denotes a sequence read",
        )

    def test_measurement_relation_directions_are_documented(self) -> None:
        source = self.text("03_knowledge_representation.tex")
        self.assertIn("sio:000215", source)
        self.assertIn("sio:000216", source)
        self.assertIn("value-to-quality", source)
        self.assertIn("its inverse", source)
        self.assertRegex(source, r"rak:4000001[\s\S]*sio:000215 rak:5000001")
        self.assertRegex(source, r"rak:5000001 a[\s\S]*sio:000216 rak:4000001")

    def test_xrf_workflows_are_separated(self) -> None:
        source = (
            self.text("02_methods.tex")
            + self.text("04_data_records.tex")
            + self.text("05_validation.tex")
        )
        self.assertRegex(source, r"field measurements|in-situ measurements")
        self.assertRegex(
            source, r"Archived material from all five campaigns was\s+subsequently measured in the laboratory"
        )
        self.assertRegex(source, r"106 entries across\s+59 sites")
        self.assertRegex(source, r"71 complete sessions at 58 sites")
        self.assertRegex(source, r"725 records in total")
        self.assertRegex(source, r"all 725 are used in the analyses")
        # Retirement counts are verified against the inventory in the next
        # test; the manuscript describes the current field/laboratory cohorts.
        self.assertNotRegex(source, r"incomplete 705-record")
        self.assertNotRegex(source, r"20 omitted")
        self.assertIn("undocumented concentration units", source)
        self.assertIn("within-workflow descriptive comparisons", self.prose("06_usage.tex"))

        audit = json.loads(
            (
                PROJECT_ROOT
                / "analysis/xrf_audit/xrf_audit_summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "field_log_rows": 106,
                "field_log_sites": 59,
                "field_complete_sessions": 71,
                "field_sites": 58,
                "lab_all_canonical": 725,
            },
            {
                key: audit["counts"][key]
                for key in (
                    "field_log_rows",
                    "field_log_sites",
                    "field_complete_sessions",
                    "field_sites",
                    "lab_all_canonical",
                )
            },
        )

    def test_xrf_inventory_marks_725_as_canonical(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MANUSCRIPT_SCRIPTS / "audit_xrf_inventory.py")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        counts = report["derived_counts"]
        self.assertEqual(725, counts["canonical_lab_analytical_records"])
        self.assertEqual(705, counts["legacy_retired_lab_analytical_records"])
        self.assertEqual(158, counts["legacy_retired_trip5_subset_records"])
        self.assertEqual(20, counts["records_restored_in_canonical_release"])

    def test_xrf_values_have_no_unsupported_percent_unit(self) -> None:
        canonical = (
            PROJECT_ROOT
            / "data/processed/semantics/ontology/rubalkhali_xrf.owl"
        )
        staged = ROOT / "zenodo/ontology/rubalkhali_xrf.owl"
        payload = canonical.read_bytes()
        self.assertEqual(payload, staged.read_bytes())
        self.assertNotIn(b"SIO_000221", payload)
        self.assertNotIn(b"UO_0000187", payload)

        result_path = (
            ROOT
            / "zenodo/evidence/competency-query/"
            "field_xrf_site10_results.tsv"
        )
        with result_path.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle, delimiter="\t"))
        self.assertEqual(
            ["processLabel", "siteLabel", "analyte", "concentration"],
            header,
        )

    def test_confirmed_source_reconciliations_are_documented(self) -> None:
        methods = self.text("02_methods.tex")
        records = self.text("04_data_records.tex")
        self.assertIn("identifiers 61--64", methods)
        self.assertIn("correction ledger", methods)
        # The exact NEBNext corrections are tested against the source ledger
        # below, without requiring all three examples to be narrated in prose.
        self.assertRegex(
            records, r"36 genuine Trip-1-only\s+records"
        )

        evidence = json.loads(
            (
                PROJECT_ROOT / "data" / "release" / "release_evidence.json"
            ).read_text(encoding="utf-8")
        )
        counts = evidence["source_counts"]
        generated = evidence["generated_kg_counts"]
        expected_source = {
            "all_source_rows": 2550,
            "master_rows": 2302,
            "master_controls": 34,
            "plant_rows": 248,
            "metadata_complete_rows": 2540,
            "kg_sample_eligible_rows": 2516,
            "confirmed_site_aliases": 4,
            "site_alias_sample_rows": 36,
            "feature_table_profiles": 1271,
            "feature_table_unique_field_ids": 1242,
            "ecology_analysis_profiles": 1237,
            "ecology_unique_field_ids": 1209,
            "ecology_primary_site_profiles": 1227,
            "ecology_numeric_sites": 64,
            "trip1_only_site_rows": 36,
            "trip1_only_site_feature_profiles": 11,
            "trip1_only_site_ecology_profiles": 10,
            "sra_unresolved_rows": 26,
        }
        self.assertEqual(expected_source, {
            key: counts[key] for key in expected_source
        })
        self.assertEqual(
            {
                "samples": 2516,
                "dna_extracts": 1647,
                "amplicon_libraries": 1242,
                "fastq_datasets": 1242,
            },
            generated,
        )

        with (
            PROJECT_ROOT / "data" / "release" / "sample_ledger.tsv"
        ).open(newline="", encoding="utf-8") as handle:
            ledger = list(csv.DictReader(handle, delimiter="\t"))
        trip1_only = [
            row for row in ledger
            if row["campaign_role"] == "trip1_only_nonrevisited"
        ]
        self.assertEqual(36, len(trip1_only))
        self.assertEqual({"61", "62", "63", "64"}, {
            row["site"] for row in trip1_only
        })
        self.assertEqual({"Trip1"}, {row["trip"] for row in trip1_only})
        self.assertTrue(all(
            row["site_alias_applied"] == "True"
            and row["site_resolves_in_kg"] == "True"
            and row["kg_sample_eligible"] == "True"
            and row["kg_exclusion_reason"] == ""
            for row in trip1_only
        ))
        canonical_sites = {
            "61": (
                "Site water well (location 2)",
                "https://rubalkhali.science/kb/RAK_1000067",
            ),
            "62": (
                "Site road (location 1)",
                "https://rubalkhali.science/kb/RAK_1000068",
            ),
            "63": (
                "Site road (location 2)",
                "https://rubalkhali.science/kb/RAK_1000069",
            ),
            "64": (
                "Site camground",
                "https://rubalkhali.science/kb/RAK_1000070",
            ),
        }
        self.assertEqual(canonical_sites, {
            site: (
                next(
                    row["canonical_site_label"] for row in trip1_only
                    if row["site"] == site
                ),
                next(
                    row["canonical_site_iri"] for row in trip1_only
                    if row["site"] == site
                ),
            )
            for site in canonical_sites
        })

        corrected = {
            row["sample_id"]: row
            for row in ledger
            if row["sample_id"] in {"F46Dr2", "S46Dr2", "V46Dr2"}
        }
        self.assertEqual({"F46Dr2", "S46Dr2", "V46Dr2"}, set(corrected))
        self.assertTrue(all(row["site"] == "46" for row in corrected.values()))
        self.assertTrue(
            all(row["site_source_value"] == "NEBNext"
                for row in corrected.values())
        )
        self.assertTrue(
            all(row["wgs_library_kit"] == "NEBNext"
                for row in corrected.values())
        )

    def test_environmental_metadata_curation_is_current(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(MANUSCRIPT_SCRIPTS / "generate_env_table.py"),
                "--project-root",
                str(PROJECT_ROOT),
                "--check",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

        curated_path = (
            PROJECT_ROOT
            / "data/processed/metadata/environmental_measurements_curated.tsv"
        )
        with curated_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(274, len(rows))

        trip2 = [
            row for row in rows if row["source_file"] == "trip2-2023.tsv"
        ]
        self.assertEqual(
            ["34.5", "36.7", "37.0", "38.6", "39.2", "41.2", "41.3", "41.9"],
            [row["temperature_c"] for row in trip2],
        )
        self.assertTrue(all(not row["pressure_mbar"] for row in trip2))
        self.assertTrue(
            all(not row["relative_humidity_pct"] for row in trip2)
        )
        self.assertEqual(
            "trip terminated due to extreme temperature",
            trip2[-1]["notes"],
        )

        trip3 = [
            row for row in rows if row["expedition"] == "Trip 3 (2024)"
        ]
        self.assertEqual(65, len(trip3))
        self.assertEqual(
            {"31.321"},
            {
                row["relative_humidity_pct"]
                for row in trip3
                if row["site"] == "21"
            },
        )
        auxiliary = [
            row
            for row in rows
            if row["record_role"] == "trip1_auxiliary_or_revisit_record"
        ]
        self.assertEqual(15, len(auxiliary))
        self.assertEqual({"2023"}, {row["date"][-4:] for row in auxiliary})

        site40 = next(
            row
            for row in rows
            if row["source_file"] == "trip5-2025.tsv"
            and row["site"] == "40"
        )
        self.assertEqual("", site40["relative_humidity_pct"])
        self.assertEqual("quarantined_out_of_range", site40["qc_status"])

        methods = self.text("02_methods.tex")
        self.assertIn("pressure and humidity remain missing", methods)
        self.assertRegex(
            methods, r"15 records are appended\s+to the legacy Trip~3 worksheet"
        )
        self.assertRegex(methods, r"194\\%[\s\S]*excluded from the curated measurements")

    def test_pressure_unit_conversion_is_staged_and_documented(self) -> None:
        canonical = (
            PROJECT_ROOT
            / "data/processed/ontology/rubalkhali_measurements.owl"
        )
        staged = ROOT / "zenodo/ontology/rubalkhali_measurements.owl"
        self.assertEqual(canonical.read_bytes(), staged.read_bytes())
        self.assertEqual(
            (
                PROJECT_ROOT
                / "scripts/rdf/generate_measurements_abox.groovy"
            ).read_bytes(),
            (
                ROOT
                / "zenodo/scripts/rdf/generate_measurements_abox.groovy"
            ).read_bytes(),
        )
        records = self.text("04_data_records.tex")
        self.assertIn("multiplied by 100 and asserted in pascals", records)
        self.assertIn(r"\texttt{obo:UO\_0000110}", records)
        self.assertIn("hectopascals (millibars)", records)

    def test_control_records_and_screen_scope_are_reported_truthfully(self) -> None:
        methods = self.text("02_methods.tex")
        records = self.text("04_data_records.tex")
        usage = self.text("06_usage.tex")
        release_readme = self.text("zenodo/README.md")
        checklist = self.text("PRE_SUBMISSION_CHECKLIST.md")
        package_builder = (
            MANUSCRIPT_SCRIPTS / "build_reviewer_package.py"
        ).read_text(encoding="utf-8")
        combined = methods + records + usage + release_readme + checklist + package_builder
        self.assertNotIn("no control-sample community records", combined)
        self.assertNotIn("no contamination assessment has been performed", combined)
        self.assertIn("351 ASVs", usage)
        self.assertIn("351,472", methods)
        self.assertIn("canonical feature table retains these ASVs", usage)
        self.assertIn("17 extraction blanks linked to 217 biological profiles", self.prose("06_usage.tex"))
        self.assertRegex(
            records,
            r"rubalkhali\\_controls\.ttl\} & Laboratory-control materials, "
            r"roles, batches and sequence occurrences",
        )
        self.assertIn("Trips~1--2 used", methods)
        self.assertIn(
            "HMW DNA Standard D6322",
            " ".join(methods.split()),
        )
        self.assertIn(
            "D6300 Microbial Community Standard",
            " ".join(methods.split()),
        )
        self.assertIn("EB1--EB18", methods)
        self.assertIn("trip-specific extraction-day batch", self.prose("02_methods.tex"))
        self.assertIn("six no-template PCR controls", methods)
        self.assertIn("28 sites", usage)
        self.assertRegex(
            release_readme,
            r"linked to its batch,\s+never directly to a trip",
        )
        self.assertIn("link EB1–EB17 to extraction batches rather than trips", checklist)
        self.assertNotIn("index-to-expedition", combined)
        self.assertNotIn("index-to-trip", combined)
        self.assertIn("documented_scientific_scope_limits", package_builder)
        self.assertIn("archived-soil pH: 712 of 1,168 source rows", package_builder)
        self.assertIn("incomplete and non-random", package_builder)
        # The archived 25-endpoint report is checked below. Its scope is an
        # archived sensitivity analysis, not a required claim of current stability.

        audit = json.loads(
            (
                ROOT
                / "zenodo/evidence/control-audit/summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(351, audit["primary_candidate_contaminant_features"])
        self.assertEqual(
            217,
            audit["mapped_biological_profiles_in_canonical_table"],
        )
        self.assertEqual(0, audit["positive_controls_in_training"])
        self.assertIn(
            "one extraction blank per extraction day",
            " ".join(audit["limitations"]),
        )
        headlines = json.loads(
            (
                ROOT
                / "zenodo/evidence/control-sensitivity/"
                "headline_result_sensitivity.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(25, headlines["headline_metrics_compared"])
        self.assertTrue(headlines["all_headline_verdicts_stable"])
        ground_truth = ROOT / "zenodo/evidence/controls/control_ground_truth.tsv"
        self.assertTrue(ground_truth.is_file())
        with ground_truth.open(newline="", encoding="utf-8") as handle:
            self.assertEqual(12, len(list(csv.DictReader(handle, delimiter="\t"))))

    def test_review_regressions_are_explicitly_disposed(self) -> None:
        methods = self.text("02_methods.tex")
        records = self.text("04_data_records.tex")
        validation = self.text("05_validation.tex")
        bibliography = self.text("sn-bibliography.bib")
        readme = self.text("zenodo/README.md")

        self.assertIn("Two executions used the Trips~1--4 ampliseq", self.prose("02_methods.tex"))
        self.assertIn("330,830 ASVs", methods)
        self.assertIn("corrected Trip~5 output (330,830 ASVs)", methods)
        self.assertIn("351,472", methods)
        self.assertIn("below the declared 1,000-read ecological", records)
        self.assertIn(r"\texttt{T1Dr1} run with 934 reads", records)
        self.assertNotIn("without an explicit QC reason", records)
        self.assertNotIn("requires explicit QC dispositions", readme)
        self.assertIn("listing validator checks printed Turtle", self.prose("05_validation.tex"))
        self.assertNotIn("all 86 printed triples", validation)
        self.assertNotIn("all 99 printed triples", validation)
        self.assertRegex(validation, r"781,044\s+asserted axioms")
        self.assertIn("800,026 triples", validation)
        self.assertIn("106,833 labelled", validation)
        self.assertIn("40,482 illegal-datarange", validation)
        self.assertIn("40,481 uses", validation)
        self.assertIn("evidence/final-validation-20260909/", validation)
        self.assertIn("evidence/semantic-validation/", validation)
        for stale in (
            "776,486",
            "777,425",
            "104,275",
            "797,103",
            "798,042",
            "104,359",
        ):
            self.assertNotIn(stale, validation)
        self.assertNotIn(
            "compartment and genomic-potential structure",
            bibliography,
        )

        bulk_paths = (
            "metadata/metagenome/eq.emapper.annotations.gz",
            "metadata/taxonomy/feature-table-trips1-5.tsv",
            "ontology/rubalkhali_taxonomy_abox.ttl",
        )
        bulk_manifest = (PROJECT_ROOT / "BULK_ARTIFACTS.tsv").read_text()
        for path in bulk_paths:
            self.assertIn(path, bulk_manifest)
        self.assertIn("PRE_RELEASE_MANIFEST.tsv", records)

        semantic = ROOT / "zenodo/evidence/semantic-validation"
        with (semantic / "SHA256SUMS").open(encoding="utf-8") as handle:
            for line in handle:
                digest, name = line.strip().split("  ", 1)
                self.assertEqual(
                    digest,
                    hashlib.sha256((semantic / name).read_bytes()).hexdigest(),
                    name,
                )
        summary = json.loads(
            (semantic / "semantic_validation_20260801.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("passed", summary["status"])
        self.assertEqual(781293, summary["elk_lite"]["axioms"])
        self.assertEqual(782229, summary["label_gate"]["triples"])
        self.assertEqual(
            104697,
            summary["label_gate"]["labelled_rak_subjects"],
        )
        for name in (
            "validate_labels.groovy",
            "check_iri_registry.py",
            "shexvalidate.sh",
            "ShexValidate.java",
            "fetch_shex_jars.groovy",
        ):
            self.assertEqual(
                (
                    PROJECT_ROOT / "scripts/validation" / name
                ).read_bytes(),
                (
                    ROOT / "zenodo/scripts/validation" / name
                ).read_bytes(),
                name,
            )

    def test_machine_readable_data_dictionary_is_staged_and_cited(self) -> None:
        dictionary = STAGE / "metadata" / "DATA_DICTIONARY.tsv"
        with dictionary.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertGreaterEqual(len(rows), 100)
        self.assertEqual(
            {
                "path",
                "field_or_pattern",
                "data_type",
                "unit",
                "missing_convention",
                "description",
            },
            set(rows[0]),
        )
        covered = {(row["path"], row["field_or_pattern"]) for row in rows}
        for required in (
            ("evidence/release/sample_ledger.tsv", "sample_id"),
            ("metadata/climate/daily_weather.tsv", "Rain_mm"),
            ("metadata/environmental/environmental_measurements_curated.tsv", "temperature_c"),
            ("ontology/rubalkhali_measurements.owl", "RAK_2000004"),
            ("metadata/geochemistry/xrf_field_table.tsv", "<analyte>"),
            ("metadata/taxonomy/feature-table-trips1-5.tsv", "<profile column>"),
            ("PRE_RELEASE_MANIFEST.tsv", "sha256"),
        ):
            self.assertIn(required, covered)
        records = self.text("04_data_records.tex")
        self.assertIn("metadata/DATA_DICTIONARY.tsv", records)

    def test_field_xrf_does_not_claim_a_specimen_link(self) -> None:
        # The XRF pattern lives in the supplement since the knowledge
        # representation was folded into Methods for the venue's section set.
        representation = self.text("03_knowledge_representation.tex") + self.text(
            "kr_supplement.tex"
        )
        validation = self.text("05_validation.tex")
        # Only the field-XRF listing is in scope: later listings legitimately
        # consume a sample (DNA extraction has the specimen as its input).
        start = validation.index("label={lst:sparql_xrf}")
        xrf_listing = validation[start:validation.index(r"\end{lstlisting}", start)]
        self.assertIn(r"\text{hasTarget}.\text{SamplingSite}", representation)
        self.assertIn("sio:000291 ?site", xrf_listing)
        self.assertNotIn("sio:000230 ?sample", xrf_listing)
        self.assertNotIn("?sample", xrf_listing)
        self.assertNotIn(
            "field-XRF process consumes the Trip~5 deep-soil specimen",
            representation,
        )

    def test_reviewed_claims_match_archived_evidence(self) -> None:
        methods = self.text("02_methods.tex")
        representation = self.text("03_knowledge_representation.tex")
        validation = self.text("05_validation.tex")
        usage = self.text("06_usage.tex")

        self.assertIn("shallow-subsurface", methods)
        self.assertIn("Deep Soil Sample", methods)
        self.assertNotRegex(
            methods,
            r"ELK reported no\s+unsatisfiable named classes",
        )
        self.assertRegex(
            methods + validation, r"class-hierarchy\s+precomputation was omitted"
        )
        self.assertIn("46 analyte-value rows", validation)
        self.assertRegex(
            validation,
            r"24 from field process Test~5847 and 22 from Test~5848",
        )
        self.assertIn("expected result tuples", validation)
        self.assertIn("All checks passed on the candidate and public service", self.prose("05_validation.tex"))

        query_path = (
            STAGE / "sparql" / "field_xrf_site10.rq"
        )
        validator_path = (
            PROJECT_ROOT
            / "scripts"
            / "validation"
            / "validate_competency_query.py"
        )
        self.assertTrue(query_path.is_file())
        self.assertTrue(validator_path.is_file())
        query_text = query_path.read_text(encoding="utf-8").strip()
        self.assertEqual(
            "8a9e352277bdd674a1015ea90fdb9abf79bad3acd7ee41bb79cde14e8b7adcce",
            hashlib.sha256(query_path.read_bytes()).hexdigest(),
        )
        listing_start = validation.index("PREFIX rak:")
        listing_end = validation.index(r"\end{lstlisting}", listing_start)
        self.assertEqual(
            query_text,
            validation[listing_start:listing_end].strip(),
        )

        validator = validator_path.read_text(encoding="utf-8")
        for phrase in (
            '"--expected-rows"',
            "default=46",
            "field_xrf_site10_results.tsv",
            "competency_query_validation.json",
            "len(processes) != 2",
            'sites != ["Site 10"]',
        ):
            self.assertIn(phrase, validator)

        staged_validator = (
            ROOT
            / "zenodo"
            / "scripts"
            / "validation"
            / "validate_competency_query.py"
        )
        if staged_validator.exists():
            self.assertEqual(
                validator_path.read_bytes(),
                staged_validator.read_bytes(),
            )

        evidence_dir = (
            STAGE / "evidence" / "competency-query"
        )
        evidence_path = evidence_dir / "competency_query_validation.json"
        if evidence_path.exists():
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual("1.0", evidence["schema_version"])
            self.assertEqual("passed", evidence["status"])
            self.assertEqual(46, evidence["expected_rows"])
            self.assertEqual(46, evidence["observed_rows"])
            self.assertEqual(["Site 10"], evidence["site_labels"])
            self.assertEqual(
                [
                    "Field XRF analysis (Test 5847) for Site 10 (Trip5)",
                    "Field XRF analysis (Test 5848) for Site 10 (Trip5)",
                ],
                evidence["distinct_process_labels"],
            )

            results_path = evidence_dir / "field_xrf_site10_results.tsv"
            self.assertTrue(results_path.is_file())
            with results_path.open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(46, len(rows))
            self.assertEqual(
                {
                    "Field XRF analysis (Test 5847) for Site 10 (Trip5)": 24,
                    "Field XRF analysis (Test 5848) for Site 10 (Trip5)": 22,
                },
                dict(Counter(row["processLabel"] for row in rows)),
            )
            self.assertEqual({"Site 10"}, {
                row["siteLabel"] for row in rows
            })

        module = STAGE / "ontology" / "rubalkhali.owl"
        root = ET.parse(module).getroot()
        owl = "{http://www.w3.org/2002/07/owl#}"
        rdf_about = (
            "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
        )
        rak_prefix = "https://rubalkhali.science/kb/RAK_"

        def declarations(kind: str) -> set[str]:
            return {
                value
                for element in root.iter(f"{owl}{kind}")
                if (value := element.attrib.get(rdf_about))
            }

        expected = {
            "Class": (333, 297),
            "ObjectProperty": (20, 11),
            "DatatypeProperty": (35, 34),
        }
        for kind, (total, local) in expected.items():
            values = declarations(kind)
            self.assertEqual(total, len(values), kind)
            self.assertEqual(
                local,
                sum(value.startswith(rak_prefix) for value in values),
                kind,
            )

        classes = declarations("Class")
        self.assertEqual(
            32,
            sum(
                value.startswith(
                    "http://semanticscience.org/resource/SIO_"
                )
                for value in classes
            ),
        )
        self.assertEqual(
            4,
            sum(
                value.startswith(
                    "http://purl.obolibrary.org/obo/PATO_"
                )
                for value in classes
            ),
        )

        for phrase in (
            "333 classes",
            "297 project classes",
            "36 referenced classes",
            "20 object properties",
            "35 datatype properties",
        ):
            self.assertIn(phrase, " ".join(representation.split()))
        self.assertNotIn("1,290 formal axioms", representation)

        bibliography = self.text("sn-bibliography.bib")
        handbook = bibliography.split("@book{dlhandbook,", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn("address={Cambridge}", handbook)
        self.assertIn("doi={10.1017/CBO9780511711787}", handbook)
        self.assertIn("pages={16952025}", bibliography)

    def test_companion_analysis_scope_is_explicit(self) -> None:
        abstract = self.text("sn-article.tex")
        methods = self.text("02_methods.tex")
        records = self.text("04_data_records.tex")
        usage = self.text("06_usage.tex")
        readme = (
            STAGE / "README.md"
        ).read_text(encoding="utf-8")

        # Scientific Data caps the abstract at 170 words, so the companion-input
        # scope is stated in Data Records and Data Availability rather than in
        # the abstract. The requirement is that it is stated, not where.
        scope_text = records + usage + methods
        for phrase in (
            "nine aliquot pairs, PMA-treated and untreated",
            "150 CoverM profiles",
            "990-genome",
            "measured-function",
        ):
            self.assertIn(phrase, scope_text)
        self.assertNotIn("metagenome-assembled-genome catalogue,", abstract)

        expected_paths = (
            "metadata/relic-dna/PMA_ASV_table.tsv",
            "metadata/metagenome/coverm_profiles.tar.gz",
            "metadata/metagenome/eq.emapper.annotations.gz",
            "metadata/metagenome/measured_function_inputs.tar.gz",
        )
        for path in expected_paths:
            self.assertIn(path, scope_text)
            self.assertIn(f"`{path}`", readme)

        for source in (scope_text, readme):
            self.assertRegex(source, r"\b150\b")
            self.assertRegex(source, r"\b990\b|990-genome")
            self.assertRegex(source, r"\bnine\b|\b9\b")
            self.assertRegex(source, r"\b18\b")

        self.assertIn("six exact source tables", scope_text)
        for source in (methods, records, usage, readme):
            self.assertNotIn("5,438-genome catalogue", source)
        for source in (scope_text, readme):
            self.assertRegex(
                source,
                r"(?is)raw.{0,80}shotgun|underlying shotgun",
            )
            for step in ("assembly", "binning", "dereplication", "annotation"):
                self.assertIn(step, source)
        # Data Records places the PMA table among fixed downstream inputs;
        # Data Availability covers raw-read access for the broader dataset.
        # The README names the underlying shotgun and PMA reads explicitly.
        self.assertRegex(readme, r"underlying shotgun and PMA sequence reads")
        self.assertIn("These are fixed inputs for downstream analyses", self.prose("04_data_records.tex"))
        self.assertIn("additional raw reads", self.prose("04_data_records.tex"))
        self.assertRegex(self.prose("06_usage.tex"),
                         r"broader dataset's archival accession, sequence access and project-data licence remain separate publication requirements")

        pma_path = (
            ROOT
            / "zenodo"
            / "metadata"
            / "relic-dna"
            / "PMA_ASV_table.tsv"
        )
        if pma_path.exists():
            with pma_path.open(encoding="utf-8") as handle:
                header = handle.readline().rstrip("\n").split("\t")
            paired = [
                column for column in header
                if column not in {"ASV_ID", "NEGATIVER", "Positive"}
            ]
            self.assertEqual(18, len(paired))

    def test_zenodo_staging_manifest_is_current_and_unambiguous(self) -> None:
        stage = STAGE
        with (stage / "PRE_RELEASE_MANIFEST.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        by_path = {row["path"]: row for row in rows}
        self.assertEqual(len(rows), len(by_path), "duplicate staged paths")
        licence_counts = Counter(row["license_status"] for row in rows)
        self.assertGreater(licence_counts["AUTHOR_GATE_UNRESOLVED"], 0)
        self.assertGreater(
            licence_counts["THIRD_PARTY_LICENCE_UNRECORDED"], 0
        )
        self.assertEqual(len(rows), sum(licence_counts.values()))
        records = self.text("04_data_records.tex")
        self.assertIn("PRE_RELEASE_MANIFEST.tsv", records)
        self.assertNotRegex(records, r"\b270 candidate files\b")
        self.assertNotRegex(records, r"\b261 files are project-produced\b")

        expected_status = {
            "metadata/taxonomy/feature-table-trips1-5.tsv":
                "canonical-candidate",
            "metadata/taxonomy/taxonomy-trips1-5.tsv":
                "canonical-candidate",
            "metadata/taxonomy/ASV_seqs-trips1-5.fasta":
                "canonical-candidate",
            "metadata/taxonomy/feature-table.tsv": "legacy-excluded",
            "metadata/taxonomy/taxonomy.tsv": "legacy-excluded",
            "metadata/geochemistry/xrf_lab_combined.tsv":
                "legacy-excluded",
        }
        self.assertEqual(
            expected_status,
            {path: by_path[path]["release_status"] for path in expected_status},
        )

        bulk_paths = set()
        bulk_manifest = PROJECT_ROOT / "BULK_ARTIFACTS.tsv"
        if bulk_manifest.is_file():
            with bulk_manifest.open(newline="", encoding="utf-8") as handle:
                bulk_paths = {
                    row["path"]
                    for row in csv.DictReader(handle, delimiter="\t")
                }

        for row in rows:
            artifact = stage / row["path"]
            if not artifact.is_file() and row["path"] in bulk_paths:
                continue
            self.assertTrue(artifact.is_file(), row["path"])
            digest = hashlib.sha256()
            with artifact.open("rb") as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            self.assertEqual(row["sha256"], digest.hexdigest(), row["path"])
            self.assertEqual(int(row["bytes"]), artifact.stat().st_size)

        current_modules = (
            "rubalkhali_samples.owl",
            "rubalkhali_dna.owl",
            "rubalkhali_sra.owl",
            "rubalkhali_xrf.owl",
        )
        for name in current_modules:
            self.assertEqual(
                (PROJECT_ROOT / "data" / "processed" / "ontology" / name)
                .resolve()
                .read_bytes(),
                (stage / "ontology" / name).read_bytes(),
                name,
            )

        readme = (stage / "README.md").read_text(encoding="utf-8")
        for stale_claim in (
            "2,535 soil",
            "2,410 DNA",
            "6,674 XRF",
            "1,401,008 taxon",
            "249 sessions",
        ):
            self.assertNotIn(stale_claim, readme)
        self.assertRegex(readme, r"725\s+laboratory and 71 field")
        self.assertRegex(
            readme,
            r"Primary ecology frame \(sites 1--60\).*1,227",
        )
        self.assertRegex(
            readme,
            r"19,763 measurement-value individuals,\s+each with a "
            r"value-to-quality link",
        )

    def test_submission_text_has_no_internal_release_placeholders(self) -> None:
        names = (
            "sn-article.tex",
            "01_introduction.tex",
            "02_methods.tex",
            "02_methods_taxonomy.tex",
            "03_knowledge_representation.tex",
            "04_data_records.tex",
            "05_validation.tex",
            "06_usage.tex",
        )
        source = "\n".join(self.prose(name) for name in names)
        for phrase in (
            "working draft",
            "not a submission-ready",
            "Before submission",
            "submission gate",
            "to be confirmed",
            "will report",
            "will contain",
            "will list",
            "will cite",
            "will regenerate",
        ):
            self.assertNotIn(phrase, source)

        abstract = self.text("sn-article.tex")
        records = self.text("04_data_records.tex")
        introduction = self.text("01_introduction.tex")
        # The abstract carries the headline denominators within the 170-word
        # cap; the full accounting is in the Introduction and Data Records.
        self.assertIn("2,550", abstract + introduction)
        self.assertIn("2,516 non-control specimen entries", abstract)
        self.assertIn("1,271 profiles", abstract)
        self.assertIn("1,237", abstract)
        self.assertIn("1,227 profiles", records + introduction)

    def test_availability_matches_candidate_contents(self) -> None:
        usage = self.prose("06_usage.tex")
        self.assertNotIn("The staged releaseThe staged release", usage)
        self.assertNotIn(
            "The release candidate contains the\n"
            "\\texttt{main.nf} entry point",
            usage,
        )
        for content in ("manuscript sources", "RDF generators", "metadata", r"\texttt{main.nf}",
                        "execution profiles", "workflow tests", "hash-locked Python environment"):
            self.assertIn(content, usage)
        self.assertIn("undocumented concentration units", usage)

    def test_current_asserted_release_claims_match_published_evidence(self) -> None:
        evidence = STAGE / "evidence/kg-v3.0.0"
        manifest_bytes = (evidence / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        acceptance = json.loads((evidence / "post-deployment-validation.json").read_text())
        self.assertEqual("asserted-only", manifest["release_mode"])
        self.assertEqual({"asserted": "https://rubalkhali.science/graph/asserted/3.0.0"}, manifest["graphs"])
        self.assertEqual({"asserted": 45706977}, manifest["counts"])
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), acceptance["manifest_sha256"])
        self.assertEqual("passed", acceptance["status"])
        self.assertTrue(acceptance["public_acceptance_passed"])
        self.assertEqual({"asserted": 45706977, "inferred": 0, "materialized": 0}, acceptance["live_graph_counts"])
        for key, count in (("query_result_gates", 26), ("protocol_gates", 14),
                           ("isolation_gates", 6), ("browser_gates", 9),
                           ("browser_download_gates", 3), ("download_gates", 3),
                           ("auxiliary_download_gates", 6)):
            rows = acceptance[key]
            self.assertEqual(count, len(rows), key)
            if key == "browser_download_gates":
                self.assertEqual({row["name"]: row["bytes"] for row in manifest["files"]},
                                 {row["name"]: row["bytes"] for row in rows})
                self.assertTrue(all(row["bounded_range_status"] == 206 for row in rows))
            else:
                self.assertTrue(all(row.get("status") == "passed" or row.get("passed") is True
                                    for row in rows), key)
        validation = self.prose("05_validation.tex")
        for phrase in ("The 26 checks", "Six additional checks", "Fourteen protocol checks",
                       "all nine portal examples", "three versioned download links",
                       "All checks passed on the candidate and public service",
                       "post-deployment-validation.json"):
            self.assertIn(phrase, validation)
        records = self.prose("04_data_records.tex").replace(r"\_", "_")
        self.assertIn("45,706,977 asserted triples from 16 manifested modules", records)
        modules = json.loads((evidence / "input-modules-manifest.json").read_text())
        self.assertEqual(16, len(modules["records"]))
        for module in modules["records"]:
            self.assertIn(module["file"], records)
        replay = json.loads((evidence / "source-rebuild-verification.json").read_text())
        self.assertTrue(replay["passed"])
        self.assertEqual({row["file"]: row["sha256"] for row in modules["records"]},
                         {row["file"]: row["sha256"] for row in replay["checks"]})
        self.assertTrue(all(row["passed"] and row["sha256"] == row["expected_sha256"] for row in replay["checks"]))
        self.assertIn("serves the asserted graph", self.prose("06_usage.tex"))
        self.assertNotIn("graph/materialized/3.0.0", self.prose("06_usage.tex"))

    def test_ph_successor_claims_match_confirmed_mapping(self) -> None:
        version = "EQ-PH-SHARED-v1.0.1"
        directory = STAGE / "metadata/samples/ph/versions" / version
        manifest = json.loads((directory / "manifest.json").read_text())
        reconciliation = manifest["specimen_reconciliation"]
        self.assertEqual(version, manifest["dataset_version"])
        self.assertEqual(156, reconciliation["accepted_trip4_measurements"])
        self.assertEqual(155, reconciliation["accepted_specimen_identity_changes"])
        for filename, key in (("trip4_specimen_reconciliation.tsv", "mapping_sha256"),
                              ("confirmation.json", "evidence_sha256")):
            self.assertEqual(reconciliation[key], hashlib.sha256((directory / filename).read_bytes()).hexdigest())
        methods = self.prose("02_methods.tex")
        self.assertIn("155 admitted Trip~4 measurements", methods)
        self.assertIn("620 RDF relations", methods)
        self.assertIn("all 712 admitted measurements, their numeric values", methods)
        for filename in ("02_methods.tex", "04_data_records.tex", "supplement.tex"):
            self.assertIn(version, self.prose(filename))
            self.assertNotIn("EQ-PH-SHARED-v1.0.0", self.prose(filename))
        self.assertIn("archived field replicate~2", methods)

    def test_dated_semantic_validation_claims_match_september_9_sources(self) -> None:
        # These are historical tractable-core checks, distinct from the current
        # 45-million-triple release and its separate unfinished reasoning run.
        directory = STAGE / "evidence/final-validation-20260909"
        summary = json.loads((directory / "asserted_core_profile_summary.json").read_text())
        compressed = directory / "asserted_core_profile.json.gz"
        self.assertEqual(summary["raw_report_gzip_sha256"], hashlib.sha256(compressed.read_bytes()).hexdigest())
        self.assertFalse(summary["full_graph_profile_claim"])
        self.assertEqual(40482, summary["violation_counts"]["UseOfIllegalDataRange"])
        self.assertEqual(40481, summary["datatype_violations"]["http://www.w3.org/2001/XMLSchema#double"])
        log = (directory / "kg_validation/logs/validate_original_details.log").read_text()
        validation = self.prose("05_validation.tex")
        for pattern, expected in ((r"Total axioms loaded: (\d+)", 781044),
                                   (r"Total triples in merged graph: (\d+)", 800026),
                                   (r"(\d+) RAK_ subjects carry rdfs:label", 106833)):
            matches = re.findall(pattern, log)
            self.assertEqual([str(expected)], matches)
            self.assertIn(f"{expected:,}", validation)
        self.assertIn("9 September validation", validation)

    def run_xrf_generator(self, rows: list[dict[str, str]]) -> subprocess.CompletedProcess[str]:
        fieldnames = [
            "analyte",
            "formula",
            "entity_type",
            "chebi",
            "chebi_label",
            "pubchem",
            "pubchem_label",
            "status",
            "evidence_url",
            "reviewed_by",
            "reviewed_date",
            "notes",
        ]
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.tsv"
            output = Path(directory) / "table.tex"
            with ledger.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=fieldnames, delimiter="\t"
                )
                writer.writeheader()
                writer.writerows(rows)
            return subprocess.run(
                [
                    sys.executable,
                    str(MANUSCRIPT_SCRIPTS / "generate_xrf_table.py"),
                    str(ledger),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_xrf_mapping_generator_accepts_reviewed_pseudoanalyte(self) -> None:
        result = self.run_xrf_generator(
            [
                {
                    "analyte": "Al",
                    "formula": "Al",
                    "entity_type": "element",
                    "chebi": "CHEBI:28984",
                    "chebi_label": "aluminium atom",
                    "pubchem": "",
                    "pubchem_label": "",
                    "status": "verified",
                    "evidence_url": "https://www.ebi.ac.uk/chebi/",
                    "reviewed_by": "reviewer",
                    "reviewed_date": "2026-07-23",
                    "notes": "",
                },
                {
                    "analyte": "LE",
                    "formula": "",
                    "entity_type": "instrument_pseudoanalyte",
                    "chebi": "",
                    "chebi_label": "",
                    "pubchem": "",
                    "pubchem_label": "",
                    "status": "verified",
                    "evidence_url": "instrument documentation",
                    "reviewed_by": "reviewer",
                    "reviewed_date": "2026-07-23",
                    "notes": "",
                },
            ]
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_xrf_mapping_generator_rejects_compound_id_for_le(self) -> None:
        result = self.run_xrf_generator(
            [
                {
                    "analyte": "LE",
                    "formula": "",
                    "entity_type": "instrument_pseudoanalyte",
                    "chebi": "CHEBI:24431",
                    "chebi_label": "chemical entity",
                    "pubchem": "",
                    "pubchem_label": "",
                    "status": "verified",
                    "evidence_url": "https://www.ebi.ac.uk/chebi/",
                    "reviewed_by": "reviewer",
                    "reviewed_date": "2026-07-23",
                    "notes": "",
                }
            ]
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("pseudo-analyte must not map to a compound", result.stderr)


if __name__ == "__main__":
    unittest.main()
