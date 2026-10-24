# Canonical MAG catalogue: Tier 1 staging

Status: **sequence archive verified; annotation and recruitment rebuild queued**.
These tables describe the 5,438 actual refined dRep representatives and the 551
read-bearing libraries. Public deposition and accession mapping remain open.

- `library_metadata.tsv`: campaign, source site code, compartment and replicate
  for each library. ENA study PRJEB125153 (secondary ERP204894) was confirmed by
  Robert Hoehndorf on 24 October 2026 as not yet public. Blank run accessions mean
  the run-to-library crosswalk has not been provided.
- `refined_representatives.tsv`: representative-to-library/bin provenance and
  CheckM2 estimates and GTDB R232 lineages for the **actual refined dRep representatives**. The FASTA
  basename refers to `05_refine/_drep/out/dereplicated_genomes/` on IBEX.
  `legacy_link_target` records how the pickup catalogue links that identifier.
  It must not be used to assign refined-bin quality to a parent-bin FASTA.
  Taxonomy comes from the checksummed native GTDB-Tk v2.7.2 / R232 summaries;
  both their identifier sets and the upstream file checksums are checked.
- `release_status.json`: source checksums, reconciled counts and open gates.
  `sequence_release` denotes a verified staging candidate; `public_release`,
  `annotation_release` and `recruitment_release` remain false.
- `genome_manifest.tsv`: per-FASTA size, SHA-256, contig count and base count.
- `packaging_receipt.json`: verified archive checksum, size and integrity checks.

The private archive is on IBEX at
`/ibex/project/c2014/rob/data-paper-mag-tier1-20261024/release/refined_mags.tar.gz`.
It contains 2,485,945 contigs and 20,490,828,267 bases; its compressed size is
7,215,750,013 bytes and SHA-256 is
`e7f46a9faee01ad7a723fe2fc4ad2310d19e0d2f1dbc832a787d8749a1303d6c`.
Authorized IBEX users can retrieve this file with `scp`; verify its checksum
against the receipt before use. No public archive locator has been assigned.
`BULK_ARTIFACTS.tsv` records this private staging location explicitly.

Fresh Bakta/eggNOG annotations and CoverM recruitment use these exact refined
sequences. Current jobs and dependencies are recorded in
`evidence/mag-catalogue-20261024/analysis_run.json`. Shared Bakta 6.0 database
access is restored and the annotation pilot has been released. Completion requires
validated outputs for all 5,438 genomes and all 551 libraries; parent-bin
annotations and coverage are excluded from this candidate.

Rebuild from the checked-in evidence snapshot with:

```bash
python3 scripts/release/prepare_mag_metadata.py
python3 -m pytest -q tests/test_mag_metadata.py
```

The original source paths and unresolved issues are documented in
`evidence/mag-catalogue-20261024/README.md`. MAGs remain tabular/bulk data at
Tier 1; graph entities and ShEx validation belong to Tier 2.
