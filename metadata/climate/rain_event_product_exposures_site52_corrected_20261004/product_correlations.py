#!/usr/bin/env python3
"""Pairwise agreement of the five Trip 1 four-day rainfall exposures across the 60 sites.

Writes product_correlations.tsv (Pearson r and Spearman rho for each product
pair) and prints the ranges reported in the supplement.
"""
import itertools
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import pearsonr, spearmanr

table = pd.read_csv(sys.argv[1], sep="\t")
output = Path(sys.argv[2])
wide = table.pivot(index="site", columns="product_id", values="precipitation_mm")
assert wide.shape == (60, 5) and not wide.isna().any().any()
rows = []
for a, b in itertools.combinations(sorted(wide.columns), 2):
    rows.append({
        "product_a": a, "product_b": b, "n_sites": len(wide),
        "pearson_r": pearsonr(wide[a], wide[b])[0],
        "spearman_rho": spearmanr(wide[a], wide[b])[0],
    })
frame = pd.DataFrame(rows)
frame.to_csv(output, sep="\t", index=False, lineterminator="\n", float_format="%.6f")
print(f"Pearson r {frame.pearson_r.min():.3f}-{frame.pearson_r.max():.3f}; "
      f"Spearman rho {frame.spearman_rho.min():.3f}-{frame.spearman_rho.max():.3f}")
