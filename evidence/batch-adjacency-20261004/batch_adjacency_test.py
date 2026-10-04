"""Library-order neighbour test for processing-batch cross-contamination.

Question: within a sequencing library series, are profiles that were prepared next
to each other (adjacent library numbers) more similar than profiles the same
geographic distance apart that were not prepared together? Cross-contamination
between co-processed samples would make adjacent pairs more similar (lower
Bray-Curtis), most strongly for low-DNA-yield samples.

Inputs: canonical feature table (TSV or gz TSV, ASV x profile counts), batch_meta.tsv
(profile, trip, site, compartment, depth, lat, lon, lib_series, lib_number,
dna_conc, dna_kit). Outputs in the working directory.
"""
import csv, gzip, json, math, sys, time
import numpy as np
from scipy.spatial.distance import pdist, squareform
from scipy.stats import spearmanr

t0 = time.time()
FT, META, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ADJ = 2          # |rank difference| <= ADJ counts as prepared together
NPERM = 999
rng = np.random.default_rng(20260907)

meta = list(csv.DictReader(open(META), delimiter="\t"))
profiles = [m["profile"] for m in meta]
pidx = {p: i for i, p in enumerate(profiles)}

# ---- read table, keep the 1,237 ecological profiles, relative abundance ----
with (gzip.open(FT, "rt") if FT.endswith(".gz") else open(FT)) as fh:
    header = None
    for line in fh:
        if line.startswith("#OTU ID"):
            header = line.rstrip("\n").split("\t")[1:]
            break
    cols = [i for i, c in enumerate(header) if c in pidx]
    order = [pidx[header[i]] for i in cols]
    n = len(profiles)
    chunks = []
    buf = []
    for line in fh:
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        vals = np.array([parts[i + 1] for i in cols], dtype=np.float32)
        if vals.any():
            buf.append(vals)
        if len(buf) >= 20000:
            chunks.append(np.vstack(buf)); buf = []
    if buf:
        chunks.append(np.vstack(buf))
X = np.vstack(chunks)            # ASVs x selected profiles (column order = cols)
del chunks
Xp = np.zeros((n, X.shape[0]), dtype=np.float32)
Xp[order, :] = X.T
del X
depth = Xp.sum(1)
Xp /= depth[:, None]
print(f"table read: {n} profiles x {Xp.shape[1]} ASVs, {time.time()-t0:.0f}s", flush=True)
D = squareform(pdist(Xp, "braycurtis")).astype(np.float32)
np.save(f"{OUT}/braycurtis_1237.npy", D)
with open(f"{OUT}/braycurtis_profiles.txt", "w") as fh:
    fh.write("\n".join(profiles) + "\n")
print(f"Bray-Curtis done, {time.time()-t0:.0f}s", flush=True)

# ---- helpers ----
def haversine(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))

def fnum(x):
    try:
        return float(x)
    except Exception:
        return float("nan")

def stratified_delta(bc, adj, strata):
    """weighted mean over strata of (mean BC adjacent - mean BC non-adjacent)."""
    num = 0.0; wsum = 0.0
    for s in np.unique(strata):
        m = strata == s
        a = adj & m; b = (~adj) & m
        if a.sum() == 0 or b.sum() == 0:
            continue
        w = a.sum()
        num += w * (bc[a].mean() - bc[b].mean()); wsum += w
    return num / wsum if wsum else float("nan")

results = {}
rows_out = []
groups = {}
for m in meta:
    if m["lib_series"] and m["lib_number"]:
        groups.setdefault((m["trip"], m["lib_series"]), []).append(m)

for (trip, series), members in sorted(groups.items()):
    if len(members) < 50:
        continue
    members = sorted(members, key=lambda m: int(m["lib_number"]))
    ids = np.array([pidx[m["profile"]] for m in members])
    rank = np.arange(len(members))
    site = np.array([m["site"] for m in members])
    comp = np.array([m["compartment"] for m in members])
    lat = np.array([fnum(m["lat"]) for m in members]); lon = np.array([fnum(m["lon"]) for m in members])
    conc = np.array([fnum(m["dna_conc"]) for m in members])
    k = len(members)
    iu, ju = np.triu_indices(k, 1)
    bc = D[ids[iu], ids[ju]]
    same_site = site[iu] == site[ju]
    same_comp = comp[iu] == comp[ju]
    geod = np.array([haversine(lat[i], lon[i], lat[j], lon[j]) for i, j in zip(iu, ju)])
    gap = np.abs(rank[iu] - rank[ju])
    keep = (~same_site) & np.isfinite(geod)
    bc_k, sc_k, geod_k, gap_k = bc[keep], same_comp[keep], geod[keep], gap[keep]
    iu_k, ju_k = iu[keep], ju[keep]
    # strata: geo-distance decile x same compartment
    dec = np.digitize(geod_k, np.quantile(geod_k, np.linspace(0.1, 0.9, 9)))
    strata = dec * 2 + sc_k.astype(int)
    adj = gap_k <= ADJ
    delta_obs = stratified_delta(bc_k, adj, strata)
    # permutation: shuffle library ranks among profiles of the group
    null = np.empty(NPERM)
    for p in range(NPERM):
        prank = rng.permutation(k)
        pgap = np.abs(prank[iu_k] - prank[ju_k])
        null[p] = stratified_delta(bc_k, pgap <= ADJ, strata)
    p_one = (np.sum(null <= delta_obs) + 1) / (NPERM + 1)      # adjacent more similar
    # OLS: bc ~ log1p(geod) + same_comp + adjacent
    Xd = np.column_stack([np.ones(len(bc_k)), np.log1p(geod_k), sc_k.astype(float), adj.astype(float)])
    beta = np.linalg.lstsq(Xd, bc_k, rcond=None)[0]
    # per-profile neighbour excess similarity vs DNA yield
    excess = np.full(k, np.nan)
    for i in range(k):
        sel = (iu_k == i) | (ju_k == i)
        a = sel & adj; b = sel & (~adj)
        if a.sum() >= 1 and b.sum() >= 5:
            # match non-neighbours on the strata of this profile's neighbour pairs
            st = np.unique(strata[a])
            bm = b & np.isin(strata, st)
            if bm.sum() >= 3:
                excess[i] = bc_k[bm].mean() - bc_k[a].mean()
    ok = np.isfinite(excess) & np.isfinite(conc)
    if ok.sum() >= 20:
        rho, prho = spearmanr(np.log10(conc[ok] + 1e-3), excess[ok])
    else:
        rho, prho = float("nan"), float("nan")
    res = dict(trip=trip, series=series, n_profiles=k, n_pairs_diff_site=int(keep.sum()),
               n_adjacent_pairs=int(adj.sum()), adjacent_definition=f"|rank diff| <= {ADJ}",
               mean_bc_adjacent=float(bc_k[adj].mean()), mean_bc_nonadjacent=float(bc_k[~adj].mean()),
               delta_stratified=float(delta_obs), null_mean=float(null.mean()), null_sd=float(null.std()),
               p_adjacent_more_similar=float(p_one),
               ols_coef_adjacent=float(beta[3]), ols_coef_log_geodist=float(beta[1]), ols_coef_same_compartment=float(beta[2]),
               n_profiles_with_yield=int(ok.sum()), spearman_logconc_vs_neighbour_excess=float(rho), spearman_p=float(prho),
               mean_excess_low_yield_tertile=float(np.nanmean(excess[ok][conc[ok] <= np.quantile(conc[ok], 1/3)])) if ok.sum() >= 20 else float("nan"),
               mean_excess_high_yield_tertile=float(np.nanmean(excess[ok][conc[ok] >= np.quantile(conc[ok], 2/3)])) if ok.sum() >= 20 else float("nan"))
    results[f"trip{trip}_{series}"] = res
    print(json.dumps(res), flush=True)
    for i, m in enumerate(members):
        rows_out.append([m["profile"], trip, series, int(m["lib_number"]), i, m["site"], m["compartment"], m["dna_conc"], f"{excess[i]:.4f}" if np.isfinite(excess[i]) else ""])

# 46Dr1 check (Trip 1): BC to library neighbours vs matched others
if "e0917_46Dr1" in pidx:
    g = groups.get(("1", "JUL_M25"), [])
    g = sorted(g, key=lambda m: int(m["lib_number"]))
    names = [m["profile"] for m in g]
    i = names.index("e0917_46Dr1")
    nb = [names[j] for j in range(max(0, i - ADJ), min(len(names), i + ADJ + 1)) if j != i]
    results["e0917_46Dr1_neighbours"] = {nm: float(D[pidx["e0917_46Dr1"], pidx[nm]]) for nm in nb}
    others = [float(D[pidx["e0917_46Dr1"], pidx[nm]]) for nm in names if nm not in nb and nm != "e0917_46Dr1" and not nm.endswith("_46Dr1")]
    results["e0917_46Dr1_others_median"] = float(np.median(others))

json.dump(results, open(f"{OUT}/batch_adjacency_results.json", "w"), indent=2)
with open(f"{OUT}/batch_adjacency_profiles.tsv", "w") as fh:
    fh.write("profile\ttrip\tseries\tlib_number\tlib_rank\tsite\tcompartment\tdna_conc\tneighbour_excess_similarity\n")
    for r in rows_out:
        fh.write("\t".join(map(str, r)) + "\n")
print(f"done, {time.time()-t0:.0f}s")
