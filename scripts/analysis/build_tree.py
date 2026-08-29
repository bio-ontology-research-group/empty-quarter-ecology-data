"""Build the prevalence-filtered ASV inputs for phylogenetic diagnostics.

ASVs present in at least 5% of non-control profiles are retained. This is an
operational dimension-reduction threshold, not a contaminant or relic-DNA
classification. The script writes the filtered ASV count table and selected
sequences; the workflow then runs MAFFT, FastTree and deterministic midpoint
rooting as separately recorded commands.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import corrected as C
import common

MINPREV_FRAC = 0.05
CHUNK = 10000

# ---- pass 1: prevalence over non-control samples ------------------------
print("pass 1: per-ASV prevalence...", flush=True)
prev, idx_parts = [], []
cols = None
for ch in pd.read_csv(common.FT_PATH, sep="\t", index_col=0, skiprows=[0], chunksize=CHUNK):
    if "Taxon" in ch.columns:
        ch = ch.drop(columns=["Taxon"])
    if cols is None:
        cols = [c for c in ch.columns if not (c.startswith("EB") or c.startswith("Negative"))]
    prev.append((ch[cols].to_numpy() > 0).sum(axis=1).astype(np.int32))
    idx_parts.append(np.asarray(ch.index))
prevalence = pd.Series(np.concatenate(prev), index=np.concatenate(idx_parts))
thr = int(len(cols) * MINPREV_FRAC)
keep_asv = prevalence[prevalence >= thr].index
print(f"  {len(prevalence)} ASVs; keep prevalence>={thr} samples -> {len(keep_asv)} ASVs", flush=True)
keep_set = set(keep_asv)

# ---- pass 2: extract filtered count table -------------------------------
print("pass 2: extracting filtered count table...", flush=True)
parts = []
for ch in pd.read_csv(common.FT_PATH, sep="\t", index_col=0, skiprows=[0], chunksize=CHUNK):
    if "Taxon" in ch.columns:
        ch = ch.drop(columns=["Taxon"])
    sub = ch.loc[ch.index.isin(keep_set), cols]
    if len(sub):
        parts.append(sub)
filt = pd.concat(parts)
filt.to_csv(os.path.join(C.CACHE, "asv_filt_counts.tsv"), sep="\t")
print(f"  filtered table {filt.shape} -> cache/asv_filt_counts.tsv", flush=True)

# ---- extract sequences --------------------------------------------------
print("extracting sequences...", flush=True)
from Bio import SeqIO
fasta_in = os.path.join(common.DATA_DIR, "processed/taxonomy/taxon-tables/ASV_seqs-trips1-5.fasta")
out = os.path.join(C.CACHE, "asv_filt.fasta")
n = 0
with open(out, "w") as fh:
    for rec in SeqIO.parse(fasta_in, "fasta"):
        if rec.id in keep_set:
            fh.write(f">{rec.id}\n{str(rec.seq)}\n")
            n += 1
print(f"  wrote {n} sequences -> cache/asv_filt.fasta")
print(f"  (matched {n}/{len(keep_asv)} kept ASVs to sequences)")
