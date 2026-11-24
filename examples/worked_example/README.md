# Worked example: specimen 10Dr2 from tube to annotated gene

`worked_example_10Dr2.py` follows one physical specimen through the released tables:
specimen (sample ledger) → 16S profile and shotgun library → genome abundance profile of the
library → the most abundant genome (quality, chimerism screen, ENA accession) → one of its genes →
the gene's Bakta/eggNOG annotation, and finally the soil pH of the same tube. It also checks three
cases a join has to handle: a specimen with two amplicon profiles (F15PRr1), a laboratory control
that belongs to no cohort (EB1) and a missing measurement (pH of 10Dr1 and 10Dr3, which is not
borrowed from replicate 10Dr2).

The script uses the Python standard library only (Python 3.6 or later).

## Inputs

Put these files in one directory (`release/` by default):

| file | released with |
|---|---|
| `sample_ledger.tsv` | this repository, `evidence/release/` |
| `combined_samplesheet_accessions.tsv` | this repository, `metadata/amplicon/` |
| `alpha.tsv` | this repository, `evidence/ecology-canonical/cache/` |
| `shotgun_cohort_accounting.tsv` | this repository, `metadata/cohorts/` |
| `shotgun_mapping_qc_source.tsv` | this repository, `metadata/cohorts/source/` |
| `gunc_progenomes3.tsv` | this repository, `metadata/metagenome/canonical/` |
| `ph_accepted_measurements.tsv` | this repository, `metadata/ph/` |
| `library_metadata.tsv`, `refined_representatives.tsv`, `ena_genome_accessions.tsv`, `refined_coverm_profiles.tar.gz`, `refined_functional_tables.tar.gz` | refined MAG catalogue deposit v1.0.0 (check against its `SHA256SUMS`) |
| `crosswalk/10Dr2.tsv.gz` | gene crosswalk `EQ-PROT-CROSSWALK-v1.0.0` (one file per source library) |

## Run

```bash
python3 -m venv --without-pip venv
env -i PATH=/usr/bin:/bin venv/bin/python -I worked_example_10Dr2.py release > output.txt
diff worked_example_10Dr2.expected.txt output.txt
```

## Test record

Run on 24 November 2026 on a Shaheen III compute node (Slurm job 16173814) in a fresh virtual
environment without packages (system Python 3.6.15, `python -I`, empty working directory), with the
deposit files verified against the deposit's `SHA256SUMS`. The output matched
`worked_example_10Dr2.expected.txt`.
