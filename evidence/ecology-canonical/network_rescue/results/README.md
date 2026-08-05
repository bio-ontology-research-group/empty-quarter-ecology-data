# Network-claim rescue

## Verdict

**Original claim: RETIRE.** Stable null-calibrated conditional associations were recoverable within each compartment, but comparative network density ordering was not robust.

Campaign-specific networks were not estimated, and campaigns were not collapsed into wet/dry labels. Conditional associations are descriptive and do not establish a biological mechanism.

## Cohort and method

- Input: `analysis/v2/review/cache/genus_counts.tsv` (SHA-256 `324d19da3669d489a42b60e0bdd6ca7f3238308bbadc72b8a28ae6098ddc8481`).
- Core sites: 1--60; sequencing replicates summed within campaign × site × compartment.
- Read-depth QC: aggregate library size ≥2000; unnamed genus rows excluded: 1.
- Exact matched cohort: 170 observations in each compartment across 60 sites.
- Campaign counts: {'1': 42, '2': 2, '3': 53, '4': 56, '5': 17}.
- Common prevalence threshold: 0.2; primary taxa: 80.
- Transform: CLR with a fixed pseudocount, followed by within-campaign centering and taxon standardization.
- Model: a common-alpha GraphicalLasso conditional-dependence network.
- Numerical nonzero threshold: absolute partial correlation >0.001; solver tolerance 0.0002.
- Alpha: 0.2; combined permuted-null/raw edge ratio: 0.054.
- Stability: 200 site-cluster bootstraps; edge threshold ≥0.80, sign consistency ≥0.90, null selection frequency ≤0.05.

## Primary compartment results

| Compartment | Raw edges | Null mean | Stable edges | Stable density | Positive stable fraction | Expected false fraction |
|---|---:|---:|---:|---:|---:|---:|
| Surface | 560 | 31.9 | 180 | 0.0570 | 0.6277777778 | 0.009611111111 |
| Deep | 579 | 28.9 | 221 | 0.0699 | 0.5746606335 | 0.008687782805 |
| Rhizosphere | 614 | 32.0 | 237 | 0.0750 | 0.5864978903 | 0.01037974684 |

## Matched compartment contrasts

| A | B | Raw density Δ | Bootstrap 95% interval | Sensitivity direction | Pass |
|---|---|---:|---:|---:|---|
| Surface | Deep | -0.0060 | [-0.0142, 0.0089] | 0.78 | false |
| Surface | Rhizosphere | -0.0171 | [-0.0161, 0.0070] | 0.67 | false |
| Deep | Rhizosphere | -0.0111 | [-0.0155, 0.0104] | 0.67 | false |

## Interpretation boundary

Edge signs and selection frequencies describe regularized conditional associations under this dataset and model. Node-degree labels, resilience claims, mutual-dependence claims, and environmental mechanisms are outside the evidence.
Permuted-null selection probabilities are stability diagnostics, not a formal false-discovery-rate estimate.

## Reproduction

```bash
uv run --with 'numpy==2.1.3' \
  --with 'pandas==2.2.3' \
  --with 'scikit-learn==1.5.2' \
  python analysis/v3/network_rescue/run_network_rescue.py \
  --project-root . \
  --output-dir analysis/v3/network_rescue/results
```

All seeds, thresholds, and counts are recorded in `parameters.json`. Outputs contain no run timestamp and are byte-deterministic for fixed inputs and dependency versions.
