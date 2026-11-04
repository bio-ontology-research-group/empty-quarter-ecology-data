# Canonical MAG catalogue: Tier 1 staging

Status: **sequence archive, functional annotations and recruitment verified;
ENA deposit private until 25 November 2026**. These tables describe the 5,438
actual refined dRep representatives and the 551 read-bearing libraries.

- `library_metadata.tsv`: campaign, source site code, compartment and replicate
  for each library, with its ENA BioSample, experiment, run and primary-assembly
  accessions in study PRJEB125153 (secondary ERP204894). Three libraries carry two
  runs; 51Sr1 and F5Dr1 yielded no contigs and have no assembly accession.
- `ena_genome_accessions.tsv`: the 12,434 refined bins deposited as binned
  metagenomes, their MIMAG tier, and for 5,437 representatives the MAG BioSample,
  analysis, GCA and sequence accessions. `48Dr2__self_SemiBin_25` (contamination
  exactly 10%) is deposited as a binned metagenome only. Sources and the GCA
  cross-check are described in
  `evidence/mag-catalogue-20261024/source/ena_deposit/README.md`.
- `refined_representatives.tsv`: representative-to-library/bin provenance and
  CheckM2 estimates and GTDB R232 lineages for the **actual refined dRep representatives**. The FASTA
  basename refers to `05_refine/_drep/out/dereplicated_genomes/` on IBEX.
  `legacy_link_target` records how the pickup catalogue links that identifier.
  It must not be used to assign refined-bin quality to a parent-bin FASTA.
  Taxonomy comes from the checksummed native GTDB-Tk v2.7.2 / R232 summaries;
  both their identifier sets and the upstream file checksums are checked.
- `release_status.json`: source checksums, reconciled counts and open gates.
  `sequence_release`, `annotation_release` and `recruitment_release` denote
  verified staging candidates; `public_release` remains false.
- `genome_manifest.tsv`: per-FASTA size, SHA-256, contig count and base count.
- `packaging_receipt.json`: verified archive checksum, size and integrity checks.
- `analysis_receipt.json`: completion receipt of the annotation and recruitment
  rebuild, with the size and SHA-256 of `refined_functional_tables.tar.gz` and
  `refined_coverm_profiles.tar.gz`.

The private archive is on IBEX at
`/ibex/project/c2014/rob/data-paper-mag-tier1-20261024/release/refined_mags.tar.gz`.
It contains 2,485,945 contigs and 20,490,828,267 bases; its compressed size is
7,215,750,013 bytes and SHA-256 is
`e7f46a9faee01ad7a723fe2fc4ad2310d19e0d2f1dbc832a787d8749a1303d6c`.
Authorized IBEX users can retrieve this file with `scp`; verify its checksum
against the receipt before use. `BULK_ARTIFACTS.tsv` records this private staging
location explicitly.

The public copy is the Zenodo deposit "Metagenome-assembled genome catalogue of
Rub' al-Khali (Empty Quarter) desert soils", v1.0.0, linked from
https://rubalkhali.science/. `scripts/release/stage_mag_zenodo.py --out DIR` writes
its metadata tables, scoped data dictionary, README, Zenodo record metadata and
upload helper; `DIR/finish_on_ibex.sh` then hard-links the three archives from the
IBEX `release/` directory, checks them against the receipts and writes
`SHA256SUMS`. The staged upload set is
`/ibex/project/c2014/rob/data-paper-mag-tier1-20261024/zenodo-v1.0.0/`;
`upload_to_zenodo.sh` creates an unpublished draft with a reserved DOI and
uploads every file in `SHA256SUMS`. Record the DOI in `BULK_ARTIFACTS.tsv`, the
manuscript bibliography (`rubalkhali_mags_v1`) and the portal after publication.

The two analysis archives sit next to the sequence archive in the same IBEX
`release/` directory and are recorded in `BULK_ARTIFACTS.tsv`. Bakta v1.12.0
(database v6.0 full) and eggNOG-mapper v2.1.13 (eggNOG v5.0.2) annotated the exact
refined sequences; Bowtie2 v2.5.1, SAMtools v1.16.1 and CoverM v0.6.1 mapped all
551 libraries against a reference containing every refined contig. Jobs, resources
and the completion receipt are recorded in
`evidence/mag-catalogue-20261024/analysis_run.json`; all jobs completed on
30 October 2026. Parent-bin annotations and coverage are excluded.

Rebuild from the checked-in evidence snapshot with:

```bash
python3 scripts/release/prepare_mag_metadata.py
python3 -m pytest -q tests/test_mag_metadata.py
```

The original source paths and unresolved issues are documented in
`evidence/mag-catalogue-20261024/README.md`. MAGs remain tabular/bulk data at
Tier 1; graph entities and ShEx validation belong to Tier 2.
