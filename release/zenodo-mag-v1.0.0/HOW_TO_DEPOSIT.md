# How to deposit this folder at Zenodo

The complete upload set is on Shaheen III: `/project/k10018/empty-quarter-zenodo-v1.0.0/`
(31 files to upload, 8.0 GB; the genome archive `refined_mags.tar.gz` is 7.2 GB). This repository folder
holds only the documentation and helper files of that set.

1. On a machine with internet access and the folder (a Shaheen login node works), run
   `ZENODO_TOKEN=<token with deposit:write> bash upload_to_zenodo.sh`.
   It checks every file against `SHA256SUMS`, creates an unpublished draft from
   `zenodo_metadata.json` with a reserved DOI, and uploads the files. Nothing is published.
2. Review the draft at https://zenodo.org/deposit (authors, description, licence CC BY 4.0), then
   publish it there.
3. Record the DOI in `BULK_ARTIFACTS.tsv`, in the manuscript bibliography entry
   `rubalkhali_mags_v1` (placeholder `DATA-BULK-ARCHIVE-DOI`) and on the portal.

`upload_to_zenodo.sh`, `zenodo_metadata.json` and this file are not uploaded.

Checked on 24 November 2026 (Shaheen job 16174114): the nine files of the 4 November staging set
have unchanged checksums, and the worked example run from this folder alone, in a clean Python
environment, reproduces `worked_example_10Dr2.expected.txt`.

Before publishing, decide whether `library_batches.tsv` (laboratory batch, kit, date and run per
library) should be public; removing it needs a new `SHA256SUMS` and one line less in `README.md`.
