# Ecology claim-rescue results

## Supersession warning

`rain_window_models.tsv` and `rain_leave_one_campaign.tsv` are retained only as historical diagnostics and every row is marked `SUPERSEDED`. They are not canonical evidence for a rainfall claim. The replacement analysis, decision, calibrated null and checksums are under `analysis/v3/rain_response_window/`.

- Input alpha profiles: 1237
- All-site observations: 640 across 64 sites
- Primary observations: 633 across 60 core sites (1–60)
- Campaign-by-compartment Wald p: 0.008306

Sites 61–64 are genuine Trip-1-only sampling sites. They are retained in the release inventory and descriptive observation table, but excluded from primary repeated-campaign inference because their regions were inaccessible for subsequent trips.

The campaign model uses a Gaussian GEE with site clusters. The superseded rainfall diagnostics aggregate technical/field replicates to site × campaign, include campaign and quadratic geographic trends, use site-clustered standard errors, correct six windows by BH-FDR, test leave-one-campaign-out stability and report residual Moran's I. Those diagnostics are retained for provenance, not inference.

The structural season/campaign alias remains unidentifiable regardless of p-values. Interpret the machine-readable claim ledger accordingly.
Advanced verdicts were imported into this ledger from their machine-readable canonical outputs.
