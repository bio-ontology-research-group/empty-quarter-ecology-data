# Round-5 checks of the data descriptor (24 November 2026)

- `pyrodigal_vs_prodigal_per_genome.tsv`: per genome, the released Pyrodigal calls (`EQ-PROT-PYRODIGAL-REP-v1.0.0`)
  against a fresh Prodigal v2.6.3 metagenomic-mode run and Pyrodigal v3.7.1 single-genome and metagenomic runs on
  the same contigs (`scripts/validation/round5-20261124/genecall_compare.py`, Shaheen jobs 16173769 and 16173881).
  Explains the 72,056-gene difference to the microTrait Prodigal product (`norfs`).
- `per_library_recruitment.tsv`, `per_library_genome_agreement.tsv`, `coverm_comparison_summary.txt`: same-library
  comparison of `EQ-COVERM-REFINED-v1.0.0` (Bowtie2 logs and CoverM 0.6.1 tables) and `EQ-COVERM-REL-ABUND-v1.0.0`
  (CoverM 0.7.0) (`coverm_product_comparison.py`).
- `shotgun_control_mapping.txt`, `shotgun_control_top_catalogue_genomes.txt`: two million read pairs of each
  shotgun control (SPositive, SNTC, P34, Trip 5 positive control of run 20260402_LL00134_0018_A23J2Y7LT4) aligned
  to the ZymoBIOMICS D6300 genomes and to the 5,438 representatives (job 16173788).
- The worked example and its clean-environment test are in `examples/worked_example/`.
