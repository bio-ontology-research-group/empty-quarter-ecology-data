# ENA deposit snapshot for PRJEB125153

Alejandra Lopez Velazquez deposited the shotgun reads, primary assemblies,
binned metagenomes and MAGs under ENA study PRJEB125153 (secondary ERP204894).
All objects are private until the scheduled release on 25 November 2026.

- `wgs_runs.tsv`, `wgs_assemblies.tsv`, `wgs_bins.tsv`: copied unchanged from
  `code/ena_deposit/` of
  https://github.com/bio-ontology-research-group/empty-quarter-proteome at
  commit c4b5f1da295b746515482d509c872ae3dcf23d08 (28 October 2026). The
  deposit decisions are documented in `notes/ENA_DEPOSIT.md` of that commit.
- `ena_mag_accession_emails.tsv`: the PRJEB125153 rows of ENA's "your genome
  assembly has been accessioned" notifications (Webin-65194, 26 to 29 October
  2026), one row per MAG. The 29 October notification supplies the GCA
  accessions of the 49 MAGs that are blank in the c4b5f1d bin table.

`scripts/release/prepare_mag_metadata.py` checks that the two GCA sources agree
wherever both are present and that every MAG has exactly one GCA accession.
