# Post-hoc evenness decomposition

**Status:** `post_hoc_evenness_decomposition_supported`

The lower campaign-averaged Shannon entropy in root-adjacent soil is accompanied by a much clearer lower-evenness signal. Hurlbert expected richness at 25,000 reads shows no root-adjacent versus surface difference and mixed evidence for root-adjacent versus shallow subsurface (the bootstrap interval for the mean excludes zero, but the paired Wilcoxon q is 0.0878). The evenness direction persists in a campaign- and log-depth-adjusted GEE.

## Primary paired results

- **Deep-Surface**: expected-richness difference 141.409 (q=0.06745); evenness-sensitivity difference 0.0125 (95% bootstrap CI 0.0008 to 0.0251; q=0.01206).
- **Rhizosphere-Surface**: expected-richness difference -10.492 (q=0.8138); evenness-sensitivity difference -0.0315 (95% bootstrap CI -0.0448 to -0.0186; q=2.759e-06).
- **Rhizosphere-Deep**: expected-richness difference -151.901 (q=0.08775); evenness-sensitivity difference -0.0440 (95% bootstrap CI -0.0572 to -0.0313; q=2.129e-07).

## Interpretation boundary

The source column named pielou is exactly Shannon divided by log Hurlbert expected richness. Because expected standardized richness replaces observed richness in the denominator, the analysis calls it an evenness sensitivity rather than conventional Pielou evenness.

Limitation: Hurlbert expected richness is unavailable for 55 core-frame profiles below the 25,000-read standard, and normalized evenness is additionally undefined for one single-ASV profile. The corresponding GEE therefore uses 617 of 633 site-campaign-position blocks. All 60 sites contribute to the campaign-averaged paired contrasts, but some site means are based on fewer profiles or campaigns. The decomposition is post hoc.

Permitted wording: In a post-hoc decomposition, the lower paired Shannon distribution in root-adjacent samples was accompanied by a clearer lower normalized-evenness signal than expected-richness signal: expected richness did not differ from surface, and its root-adjacent--shallow evidence was mixed across summaries. This describes the diversity profile and does not identify a root-mediated mechanism.

Prohibited wording: Do not call H/log(E[S_25k]) conventional Pielou evenness, do not describe a causal rhizosphere filter, and do not treat post-hoc decomposition as a preregistered primary endpoint.

## Reproduction

```bash
uv run --python .venv/bin/python analysis/v3/evenness_decomposition_analysis.py
```
