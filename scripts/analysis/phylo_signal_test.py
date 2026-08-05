#!/usr/bin/env python3
"""Pressure-test the phylogenetic-signal assumption required by betaNTI/betaMNTD.

Standard Stegen-framework check (Stegen et al. 2012): Mantel correlogram of niche
difference vs phylogenetic distance; signal must be POSITIVE at the shortest classes.
The tested niche summary is each ASV's abundance-weighted mean on the canonical
all-trip laboratory-XRF elemental PC1. It is not an independently measured salinity
axis and supports no salinity physiology inference.
Uses the SAME top-800 abundant ASV set that produced the 68% dispersal-limitation result.

Run: python phylo_signal_test.py --elemental-axis laboratory_xrf_axis.tsv
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from skbio import TreeNode
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
# --- relocated under RQ26: locate shared helpers in the review/ package ---
import os as _os, sys as _sys
_V2 = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..')   # analysis/v2 (common.py)
_sys.path.insert(0, _V2)
_sys.path.insert(0, _os.path.join(_V2, 'review'))                              # analysis/v2/review (corrected.py + cache)
import corrected as C
import common

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--elemental-axis",
    type=Path,
    required=True,
    help=(
        "Canonical laboratory_xrf_axis.tsv produced by "
        "analysis/v3/xrf_community_rescue.py"
    ),
)
parser.add_argument(
    "--output-dir",
    type=Path,
    required=True,
    help="Directory for the structured diagnostic and provenance outputs.",
)
parser.add_argument("--permutations", type=int, default=999)
parser.add_argument("--seed", type=int, default=20260723)
args = parser.parse_args()
output_dir = args.output_dir.resolve()
output_dir.mkdir(parents=True, exist_ok=True)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

counts_path = os.path.join(C.CACHE, "asv_filt_counts.tsv")
tree_path = os.path.join(C.CACHE, "asv_filt_tree_rooted.nwk")
filt = pd.read_csv(counts_path, sep="\t", index_col=0)
tree = TreeNode.read(tree_path)
meta = common.parse_metadata(list(filt.columns), common.load_climate_data())
lab = meta.apply(lambda r: f"{r.Trip}|{r.Site}|{r.Type}", axis=1)

# communities x ASV (same construction as assembly_partitioning.py)
comm = filt.T.groupby(lab.values).sum()
comm = comm[comm.sum(axis=1) >= 5000]
mean_ra = (filt.div(filt.sum(axis=0), axis=1)).mean(axis=1)
abundant = mean_ra.sort_values(ascending=False).head(800).index.tolist()

# Canonical all-trip laboratory-XRF axis per community (cid = Trip|Site|Type).
geo = pd.read_csv(args.elemental_axis, sep="\t")
required = {"Trip", "Site", "Type", "elemental_pc1"}
missing = required - set(geo.columns)
if missing:
    raise ValueError(
        f"{args.elemental_axis} lacks required columns: {sorted(missing)}"
    )
geo["cid"] = (
    geo["Trip"].astype(int).astype(str)
    + "|"
    + geo["Site"].astype(int).astype(str)
    + "|"
    + geo["Type"].astype(str)
)
elemental_by_community = dict(zip(geo["cid"], geo["elemental_pc1"]))
community_axis = comm.index.to_series().map(elemental_by_community)
keep = community_axis.notna()
print(
    f"{keep.sum()} of {len(comm)} communities have the canonical "
    f"laboratory-XRF elemental axis; {len(abundant)} abundant ASVs"
)
A = comm.loc[keep, abundant].astype(float)
s = community_axis[keep].to_numpy()

# Niche summary per ASV = abundance-weighted mean elemental PC1.
W = A.to_numpy()
wsum = W.sum(axis=0)
present = wsum > 0
niche = (W * s[:, None]).sum(axis=0)[present] / wsum[present]
asv_ids = [a for a, p in zip(abundant, present) if p]
print(
    f"{len(asv_ids)} abundant ASVs present with an elemental-axis-weighted "
    "niche summary"
)

# patristic distance among those ASVs
intree = [a for a in asv_ids if tree.find(a) is not None] if False else asv_ids
sub = tree.shear([a for a in asv_ids])
D = sub.tip_tip_distances()
order = D.ids
Dm = D.data
nopt = pd.Series(niche, index=asv_ids).reindex(order).to_numpy()
N = np.abs(nopt[:, None] - nopt[None, :])              # pairwise niche difference

iu = np.triu_indices_from(Dm, 1)
d, n = Dm[iu], N[iu]

def mantel(a, b, perms, seed):
    r = np.corrcoef(a, b)[0, 1]
    rng = np.random.default_rng(seed); ge = 1; m = len(order)
    Nm = N.copy()
    for _ in range(perms):
        p = rng.permutation(m)
        rp = np.corrcoef(Dm[iu], Nm[p][:, p][iu])[0, 1]
        if abs(rp) >= abs(r): ge += 1
    return r, ge / (perms + 1)

r_all, p_all = mantel(
    d,
    n,
    perms=args.permutations,
    seed=args.seed,
)
print(f"\nOVERALL Mantel (phylo distance vs niche difference): r={r_all:+.3f}, p={p_all:.3f}")

# Mantel correlogram across phylogenetic distance classes (Pearson r of niche-diff vs phylo-dist within class)
print("\nCorrelogram (niche difference by phylogenetic distance class):")
qs = np.quantile(d, np.linspace(0, 1, 11))
print(f"{'class':>5} {'phylo-dist range':>22} {'n pairs':>8} {'mean niche diff':>16}")
prev = None
means = []
class_rows = []
for i in range(10):
    lo, hi = qs[i], qs[i + 1]
    m = (d >= lo) & (d <= hi) if i == 9 else (d >= lo) & (d < hi)
    means.append(n[m].mean())
    class_rows.append(
        {
            "distance_class": i + 1,
            "phylogenetic_distance_low": lo,
            "phylogenetic_distance_high": hi,
            "pair_count": int(m.sum()),
            "mean_elemental_axis_niche_difference": n[m].mean(),
        }
    )
    print(f"{i+1:>5} {lo:>9.3f}-{hi:<11.3f} {m.sum():>8d} {n[m].mean():>16.4f}")
# signal at short distances: correlation over the closest 30% of pairs
short = d <= np.quantile(d, 0.30)
rs = np.corrcoef(d[short], n[short])[0, 1]
print(f"\nShort-distance (closest 30% of pairs) Pearson r(phylo, niche) = {rs:+.3f}")
print(f"Closest-class mean niche diff {means[0]:.4f} vs farthest-class {means[-1]:.4f}")
positive_signal = bool(
    r_all > 0 and p_all < 0.05 and means[0] < means[-1]
)
verdict = (
    "POSITIVE FOR THIS ELEMENTAL-AXIS NICHE SUMMARY"
    if positive_signal
    else "WEAK/ABSENT -> betaNTI process labels are not reliable"
)
print(f"\nPHYLOGENETIC SIGNAL: {verdict}")

pd.DataFrame(class_rows).to_csv(
    output_dir / "phylo_signal_distance_classes.tsv",
    sep="\t",
    index=False,
)
summary = {
    "schema_version": "1.0",
    "status": (
        "positive_for_tested_elemental_axis"
        if positive_signal
        else "weak_or_absent_positive_signal"
    ),
    "betaNTI_process_percentages_permitted": False,
    "permitted_wording": (
        "The tested elemental-axis niche summary showed positive short-range "
        "phylogenetic signal, but this single diagnostic alone does not "
        "validate betaNTI process labels."
        if positive_signal
        else "The tested elemental-axis niche summary lacked the positive "
        "short-range phylogenetic signal required for interpreting betaNTI "
        "process labels; the earlier assembly percentages are retired."
    ),
    "prohibited_wording": (
        "Do not infer dispersal limitation, homogeneous selection, variable "
        "selection, drift, or homogenizing dispersal percentages from the "
        "retired betaNTI/RC-Bray analysis."
    ),
    "counts": {
        "communities_total": int(len(comm)),
        "communities_with_elemental_axis": int(keep.sum()),
        "abundant_asvs_requested": int(len(abundant)),
        "asvs_with_niche_summary": int(len(order)),
        "phylogenetic_pairs": int(len(d)),
    },
    "diagnostics": {
        "overall_mantel_r": float(r_all),
        "overall_mantel_p": float(p_all),
        "short_distance_pearson_r": float(rs),
        "closest_class_mean_niche_difference": float(means[0]),
        "farthest_class_mean_niche_difference": float(means[-1]),
    },
    "parameters": {
        "permutations": int(args.permutations),
        "seed": int(args.seed),
        "short_distance_fraction": 0.30,
        "distance_classes": 10,
    },
    "inputs": {
        "elemental_axis": {
            "file": args.elemental_axis.name,
            "sha256": file_sha256(args.elemental_axis),
        },
        "asv_counts": {
            "file": os.path.basename(counts_path),
            "sha256": file_sha256(counts_path),
        },
        "tree": {
            "file": os.path.basename(tree_path),
            "sha256": file_sha256(tree_path),
        },
    },
}
(output_dir / "phylo_signal_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n"
)
(output_dir / "README.md").write_text(
    "# Phylogenetic-signal diagnostic\n\n"
    "The tested niche summary is the abundance-weighted mean of the canonical "
    "all-trip laboratory-XRF elemental PC1. It is not measured salinity. "
    "The diagnostic evaluates one prerequisite for interpreting betaNTI; it "
    "does not validate an ecological process classifier by itself.\n\n"
    f"Status: `{summary['status']}`. "
    f"Overall Mantel r={r_all:+.4f}, p={p_all:.4g}; closest-30% "
    f"r={rs:+.4f}; closest versus farthest class mean niche difference "
    f"{means[0]:.4f} versus {means[-1]:.4f}.\n\n"
    f"{summary['permitted_wording']}\n"
)
print(f"\nwrote structured outputs to {output_dir}")
