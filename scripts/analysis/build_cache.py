"""
One-pass cache builder for the corrected re-analysis.

Streams the 1.8 GB feature table and writes small cached artifacts so every
downstream fix runs in seconds:

  cache/alpha.tsv         per-sample depth, raw richness, EXACT Hurlbert expected
                          rarefied richness at depth D, full-depth Shannon, Pielou
  cache/genus_counts.tsv  genus x samples count table
  cache/phylum_counts.tsv phylum x samples count table
  cache/meta.json         rarefaction depth D, retention, sample counts

Rarefied richness uses Hurlbert's exact expectation
  E[S_rare] = sum_i ( 1 - C(N-c_i, D)/C(N, D) )
computed via log-gamma (no random subsampling), so it is deterministic and
removes the depth dependence of observed richness.
"""
import os
import sys
import json
import time
import numpy as np
import pandas as pd
from scipy.special import gammaln

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common          # noqa: E402
import corrected as C  # noqa: E402

CHUNK = 10000
FT = common.FT_PATH
t0 = time.time()

# ---- taxonomy maps ------------------------------------------------------
print("Loading taxonomy ranks...", flush=True)
tax = common.load_taxonomy()
ranks = common.parse_taxonomy_ranks(tax)
genus_map = ranks["Genus"]
phylum_map = ranks["Phylum"]

# ---- PASS 1: depths + Shannon accumulators ------------------------------
print("PASS 1: per-sample depth and Shannon accumulators...", flush=True)
cols = None
depth = None
sum_clnc = None      # sum c*ln(c)
rich_raw = None
for chunk in pd.read_csv(FT, sep="\t", index_col=0, skiprows=[0], chunksize=CHUNK):
    if "Taxon" in chunk.columns:
        chunk = chunk.drop(columns=["Taxon"])
    v = chunk.to_numpy(dtype=np.float64)
    if cols is None:
        cols = list(chunk.columns)
        depth = np.zeros(len(cols))
        sum_clnc = np.zeros(len(cols))
        rich_raw = np.zeros(len(cols))
    depth += v.sum(axis=0)
    nz = v > 0
    rich_raw += nz.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        clnc = np.where(nz, v * np.log(np.where(nz, v, 1.0)), 0.0)
    sum_clnc += clnc.sum(axis=0)
cols = np.array(cols)
print(f"  {len(cols)} columns, depth median={np.median(depth):.0f}", flush=True)

# keep non-control, depth >= 1000 (matches cleaning), choose D
is_sample = np.array([not (c.startswith("EB") or c.startswith("Negative")) for c in cols])
keep = is_sample & (depth >= 1000)
D = C.choose_rarefaction_depth(depth[keep])
n_below_D = int((depth[keep] < D).sum())
print(f"  rarefaction depth D = {D} "
      f"(retains {keep.sum() - n_below_D}/{keep.sum()} kept samples)", flush=True)

shannon = np.where(depth > 0, np.log(np.where(depth > 0, depth, 1.0)) - sum_clnc / np.where(depth > 0, depth, 1.0), 0.0)

# ---- PASS 2: Hurlbert rarefied richness + genus/phylum aggregation ------
print("PASS 2: Hurlbert rarefied richness + genus/phylum tables...", flush=True)
N = depth
valid = depth >= D
es_rare = np.zeros(len(cols))
genus_acc, phylum_acc = {}, {}
done = 0
for chunk in pd.read_csv(FT, sep="\t", index_col=0, skiprows=[0], chunksize=CHUNK):
    if "Taxon" in chunk.columns:
        chunk = chunk.drop(columns=["Taxon"])
    M = chunk.to_numpy(dtype=np.float64)            # ASV x sample
    # --- Hurlbert (only nonzero entries contribute) ---
    rows, scol = np.nonzero(M)
    if rows.size:
        cval = M[rows, scol]
        Nval = N[scol]
        NC = Nval - cval
        pnot = np.zeros(cval.shape)
        m = NC >= D                                  # otherwise certainly observed -> pnot 0
        a = gammaln(NC[m] + 1) - gammaln(NC[m] - D + 1)
        b = gammaln(Nval[m] + 1) - gammaln(Nval[m] - D + 1)
        pnot[m] = np.exp(a - b)
        np.add.at(es_rare, scol, 1.0 - pnot)
    # --- genus / phylum sums ---
    for acc, mp in ((genus_acc, genus_map), (phylum_acc, phylum_map)):
        lab = mp.reindex(chunk.index).values
        ok = pd.notna(lab)
        if not ok.any():
            continue
        sub = pd.DataFrame(M[ok], index=lab[ok], columns=chunk.columns).groupby(level=0).sum()
        for name, row in sub.iterrows():
            if name in acc:
                acc[name] += row.values
            else:
                acc[name] = row.values.astype(float)
    done += chunk.shape[0]
es_rare[~valid] = np.nan

# ---- assemble + write ---------------------------------------------------
sample_cols = cols[keep]
meta = common.parse_metadata(list(sample_cols), common.load_climate_data())
alpha = pd.DataFrame({
    "depth": depth[keep],
    "richness_raw": rich_raw[keep].astype(int),
    "richness_rare": es_rare[keep],
    "shannon": shannon[keep],
}, index=sample_cols)
alpha["pielou"] = alpha["shannon"] / np.log(alpha["richness_rare"].where(alpha["richness_rare"] > 1))
alpha = alpha.join(meta[["Trip", "Site", "Type", "Season"]])
alpha.to_csv(os.path.join(C.CACHE, "alpha.tsv"), sep="\t")

genus_df = pd.DataFrame(genus_acc, index=cols).T[sample_cols]
genus_df.to_csv(os.path.join(C.CACHE, "genus_counts.tsv"), sep="\t")
phylum_df = pd.DataFrame(phylum_acc, index=cols).T[sample_cols]
phylum_df.to_csv(os.path.join(C.CACHE, "phylum_counts.tsv"), sep="\t")

with open(os.path.join(C.CACHE, "meta.json"), "w") as fh:
    json.dump({"rarefaction_depth": int(D), "retain_frac": C.RETAIN_FRAC,
               "n_samples_kept": int(keep.sum()),
               "n_samples_rarefiable": int(valid[keep].sum()),
               "n_genera": int(genus_df.shape[0]),
               "n_phyla": int(phylum_df.shape[0])}, fh, indent=2)

print("\nWrote cache:")
print(f"  alpha.tsv         {alpha.shape}")
print(f"  genus_counts.tsv  {genus_df.shape}")
print(f"  phylum_counts.tsv {phylum_df.shape}")
print(f"  D={D}, rarefiable samples={int(valid[keep].sum())}/{int(keep.sum())}")
# sanity: does rarefied richness still track depth?
sub = alpha.dropna(subset=["richness_rare"])
from scipy.stats import spearmanr
print(f"  raw richness  ~ depth: rho={spearmanr(sub['depth'], sub['richness_raw'])[0]:.3f}")
print(f"  rarefied rich ~ depth: rho={spearmanr(sub['depth'], sub['richness_rare'])[0]:.3f}")
