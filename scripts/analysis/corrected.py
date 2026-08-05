"""
Shared toolkit for the corrected re-analysis.

Centralises the methodological fixes so every RQ recompute inherits them:
  - rarefaction depth selection
  - exact Hurlbert expected rarefied richness (computed in build_cache.py)
  - CLR transform and guild-vs-rest log-ratio (compositional-safe)
  - site / site x compartment aggregation (kills replicate pseudoreplication)
  - one standardised XRF -> 16S join (site x compartment means)
  - Benjamini-Hochberg FDR and Bonferroni adjustment
  - permutation Mantel test
  - Cliff's delta effect size

Caches written by build_cache.py live in analysis/v2/review/cache/.
"""
import os
import sys
import json
import warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")   # deterministic, keeps showboat output stable

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
RESULTS = os.path.join(HERE, "corrected_results")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(RESULTS, exist_ok=True)

PSEUDO = 0.5          # count pseudocount for log-ratios
RETAIN_FRAC = 0.95    # rarefaction depth keeps >= this fraction of samples


# --------------------------------------------------------------------------
# rarefaction depth
# --------------------------------------------------------------------------
def choose_rarefaction_depth(depths, retain=RETAIN_FRAC, round_to=1000):
    """Largest round depth that retains >= `retain` of samples."""
    depths = np.asarray(depths, dtype=float)
    q = np.quantile(depths, 1.0 - retain)
    d = int(np.floor(q / round_to) * round_to)
    return max(d, round_to)


# --------------------------------------------------------------------------
# cache access
# --------------------------------------------------------------------------
def load_alpha():
    return pd.read_csv(os.path.join(CACHE, "alpha.tsv"), sep="\t", index_col=0)


def load_genus():
    return pd.read_csv(os.path.join(CACHE, "genus_counts.tsv"), sep="\t", index_col=0)


def load_phylum():
    return pd.read_csv(os.path.join(CACHE, "phylum_counts.tsv"), sep="\t", index_col=0)


def cache_meta():
    with open(os.path.join(CACHE, "meta.json")) as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# compositional transforms (input: features x samples counts)
# --------------------------------------------------------------------------
def clr(counts_fs):
    """CLR per sample. Input features x samples -> returns samples x features."""
    x = counts_fs.T.astype(float) + PSEUDO          # samples x features
    logx = np.log(x)
    return logx.sub(logx.mean(axis=1), axis=0)       # subtract per-sample gmean(log)


def guild_logratio(counts_fs, guild_features):
    """ln(sum(guild)+p) - ln(sum(rest)+p) per sample. Compositional, additive-safe.
    Input features x samples; returns Series indexed by sample."""
    present = [g for g in guild_features if g in counts_fs.index]
    guild = counts_fs.loc[present].sum(axis=0) if present else pd.Series(0.0, index=counts_fs.columns)
    rest = counts_fs.sum(axis=0) - guild
    return np.log(guild + PSEUDO) - np.log(rest + PSEUDO)


# --------------------------------------------------------------------------
# aggregation (pseudoreplication fix)
# --------------------------------------------------------------------------
def add_meta(series_or_df, name=None):
    """Attach Trip/Site/Type/Season/Precip/Temp to a per-sample series/frame."""
    if isinstance(series_or_df, pd.Series):
        df = series_or_df.to_frame(name or "value")
    else:
        df = series_or_df.copy()
    clim = common.load_climate_data()
    meta = common.parse_metadata(list(df.index), clim)
    return df.join(meta)


def aggregate_site_type(df, value_cols, how="mean"):
    """Collapse replicates: mean per (Trip, Site, Type)."""
    g = df.groupby(["Trip", "Site", "Type"])[value_cols].agg(how)
    return g.reset_index()


# --------------------------------------------------------------------------
# standardised XRF <-> 16S join (site x compartment means, Trip 5)
# --------------------------------------------------------------------------
def xrf_site_type():
    """XRF averaged to (Site, Type) for Trip 5. Returns DataFrame indexed (Site,Type)."""
    xrf = common.load_xrf_data(aggregate_by="site_type")
    return xrf


def standard_join(metric_per_sample, elements=None):
    """Join a per-sample microbiome metric to XRF at (Site, Type) level.

    metric_per_sample: Series indexed by 16S sample id.
    Returns DataFrame with the site x compartment mean metric + XRF elements.
    """
    df = add_meta(metric_per_sample, "metric")
    df = df[df["Trip"] == 5]
    agg = df.groupby(["Site", "Type"])["metric"].mean().rename("metric")
    xrf = xrf_site_type()
    out = agg.to_frame().join(xrf, how="inner")
    if elements:
        keep = ["metric"] + [e for e in elements if e in out.columns]
        out = out[keep]
    return out


# --------------------------------------------------------------------------
# multiple-testing adjustment
# --------------------------------------------------------------------------
def bh_fdr(pvals):
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(ranked, 0, 1)
    return out


def bonferroni(pvals):
    p = np.asarray(pvals, dtype=float)
    return np.clip(p * len(p), 0, 1)


def adjust_table(df, pcol="p", family=None):
    """Add BH and Bonferroni columns. If `family` given, correct within each group."""
    df = df.copy()
    df["p_BH"] = np.nan
    df["p_Bonf"] = np.nan
    groups = [(None, df.index)] if family is None else [(k, idx) for k, idx in df.groupby(family).groups.items()]
    for _, idx in groups:
        df.loc[idx, "p_BH"] = bh_fdr(df.loc[idx, pcol].values)
        df.loc[idx, "p_Bonf"] = bonferroni(df.loc[idx, pcol].values)
    return df


# --------------------------------------------------------------------------
# stats helpers
# --------------------------------------------------------------------------
def cliffs_delta(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return np.nan
    gt = sum((a[:, None] > b[None, :]).sum(axis=1))
    lt = sum((a[:, None] < b[None, :]).sum(axis=1))
    return (gt - lt) / (len(a) * len(b))


def mantel(d1, d2, perms=9999, seed=0):
    """Permutation Mantel on two square distance matrices (numpy arrays)."""
    iu = np.triu_indices_from(d1, k=1)
    v1, v2 = d1[iu], d2[iu]
    r_obs = stats.pearsonr(v1, v2)[0]
    n = d1.shape[0]
    rng = np.random.default_rng(seed)
    count = 0
    for _ in range(perms):
        perm = rng.permutation(n)
        v2p = d2[perm][:, perm][iu]
        if stats.pearsonr(v1, v2p)[0] >= r_obs:
            count += 1
    p = (count + 1) / (perms + 1)
    return r_obs, p


def spearman(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return np.nan, np.nan, int(ok.sum())
    rho, p = stats.spearmanr(x[ok], y[ok])
    return rho, p, int(ok.sum())
