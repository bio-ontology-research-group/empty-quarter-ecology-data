#!/usr/bin/env python3
"""Account for the difference between the Pyrodigal representative gene calls (all_rep_proteins.faa,
20,451,986) and the Prodigal v2.6.3 -p meta calls of microTrait (20,379,930) on the 5,438 representatives.
For each genome: re-call genes with Prodigal 2.6.3 meta, Pyrodigal 3.7.1 single (trained on the genome) and
Pyrodigal 3.7.1 meta; compare coordinates with the released Pyrodigal calls."""
import gzip, hashlib, os, subprocess, sys, collections, multiprocessing as mp
import pyrodigal

MAGS = "/project/k10018/empty-quarter/data/catalog/mags/dereplicated"
FAA = "/project/k10018/empty-quarter/data/catalog/proteins/orthogroups/all_rep_proteins.faa"
PRODIGAL = "/project/k10018/sw/envs/mapping/bin/prodigal"
OUT = sys.argv[1]
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
REP = {}

def load_rep():
    with open(FAA, "rb") as fh:
        for line in fh:
            if line[:1] != b">":
                continue
            g, rest = line[1:].split(b"::", 1)
            REP.setdefault(g.decode(), []).append(rest)

def parse_rep(lines):
    s = {}
    for l in lines:
        f = l.decode().split(" # ")
        cid = f[0].rsplit("_", 1)[0]
        part = f[4].split("partial=")[1][:2] if "partial=" in f[4] else "NA"
        s[(cid, int(f[1]), int(f[2]), int(f[3]))] = part
    return s

def stop(k):
    c, b, e, st = k
    return (c, st, e if st == 1 else b)

def classify(A, B):
    """genes of A: exact in B, same stop in B, absent from B"""
    bstop = {stop(k) for k in B}
    ex = sum(1 for k in A if k in B)
    ss = sum(1 for k in A if k not in B and stop(k) in bstop)
    return ex, ss, len(A) - ex - ss

def lenbin(n):
    return "<5kb" if n < 5000 else "5-20kb" if n < 20000 else "20-100kb" if n < 100000 else ">=100kb"

def work(g):
    fn = f"{MAGS}/{g}.fa.gz"
    raw = gzip.open(fn).read() if os.path.exists(fn) else open(f"{MAGS}/{g}.fa", "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    seqs, name = {}, None
    for l in raw.decode().splitlines():
        if l.startswith(">"):
            name = l[1:].split()[0]; seqs[name] = []
        elif name:
            seqs[name].append(l.strip())
    seqs = {k: "".join(v) for k, v in seqs.items()}
    if g.endswith("_sub"):
        # the catalogue FASTA of a DAS Tool sub-bin is its parent bin; restrict it to the contigs of the
        # representative (every contig of the refined genome carries at least one released gene)
        keep = {l.split(b" # ")[0].decode().rsplit("_", 1)[0] for l in REP.get(g, [])}
        seqs = {k: v for k, v in seqs.items() if k in keep}
        raw = "".join(f">{k}\n{v}\n" for k, v in seqs.items()).encode()
    clen = {k: len(v) for k, v in seqs.items()}
    R = parse_rep(REP.get(g, []))
    # prodigal 2.6.3 meta
    p = subprocess.run([PRODIGAL, "-p", "meta", "-f", "gff", "-q"], input=raw, capture_output=True, check=True)
    M = {}
    for l in p.stdout.decode().splitlines():
        if l.startswith("#") or not l.strip():
            continue
        f = l.split("\t")
        M[(f[0], int(f[3]), int(f[4]), 1 if f[6] == "+" else -1)] = f[8].split("partial=")[1][:2]
    # pyrodigal single (trained on whole genome) and meta
    S, single_ok = {}, True
    try:
        gf = pyrodigal.GeneFinder(meta=False)
        gf.train(*[s.encode() for s in seqs.values()])
        for c, s in seqs.items():
            for x in gf.find_genes(s.encode()):
                S[(c, x.begin, x.end, x.strand)] = f"{int(x.partial_begin)}{int(x.partial_end)}"
    except Exception as e:
        single_ok = False
    gm = pyrodigal.GeneFinder(meta=True)
    PM = {}
    for c, s in seqs.items():
        for x in gm.find_genes(s.encode()):
            PM[(c, x.begin, x.end, x.strand)] = f"{int(x.partial_begin)}{int(x.partial_end)}"
    rM = classify(R, M); mR = classify(M, R)
    rS = classify(R, S) if single_ok else (0, 0, 0); rPM = classify(R, PM)
    # breakdown of R-only and M-only (no same-stop partner) by partial status and contig length
    mstop = {stop(k) for k in M}; rstop = {stop(k) for k in R}
    brk = collections.Counter()
    for k, part in R.items():
        if stop(k) not in mstop:
            brk[("rep_only", "complete" if part == "00" else "partial", lenbin(clen.get(k[0], 0)))] += 1
    for k, part in M.items():
        if stop(k) not in rstop:
            brk[("prodigal_only", "complete" if part == "00" else "partial", lenbin(clen.get(k[0], 0)))] += 1
    # per contig-length bin counts of all genes
    for k in R: brk[("rep_all", "-", lenbin(clen.get(k[0], 0)))] += 1
    for k in M: brk[("prodigal_all", "-", lenbin(clen.get(k[0], 0)))] += 1
    rep_contigs = {k[0] for k in R}
    row = [g, sha, len(seqs), sum(clen.values()), len(R), len(M), len(S) if single_ok else -1, len(PM),
           *rM, *mR, *rS, *rPM, int(single_ok), len(rep_contigs - set(seqs))]
    return row, brk

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    genomes = sorted(f[:-6] if f.endswith(".fa.gz") else f[:-3] for f in os.listdir(MAGS) if f.endswith((".fa.gz", ".fa")))
    if os.environ.get("SUBSET"):
        genomes = [g for g in genomes if g.endswith("_sub") or not os.path.exists(f"{MAGS}/{g}.fa.gz")]
    if LIMIT:
        genomes = genomes[:LIMIT]
    load_rep()
    print("rep genomes", len(REP), "rep genes", sum(len(v) for v in REP.values()), flush=True)
    cols = ["genome", "fasta_sha256", "contigs", "bases", "n_rep_pyrodigal", "n_prodigal263_meta", "n_pyrodigal371_single",
            "n_pyrodigal371_meta", "rep_exact_in_prodigal", "rep_samestop_in_prodigal", "rep_absent_from_prodigal",
            "prodigal_exact_in_rep", "prodigal_samestop_in_rep", "prodigal_absent_from_rep",
            "rep_exact_in_pyro_single", "rep_samestop_in_pyro_single", "rep_absent_from_pyro_single",
            "rep_exact_in_pyro_meta", "rep_samestop_in_pyro_meta", "rep_absent_from_pyro_meta",
            "single_training_ok", "rep_contigs_not_in_fasta"]
    tot = collections.Counter()
    with mp.Pool(int(os.environ.get("SLURM_CPUS_ON_NODE", "8"))) as pool, open(f"{OUT}/per_genome.tsv", "w") as fo:
        fo.write("\t".join(cols) + "\n")
        for i, (row, brk) in enumerate(pool.imap_unordered(work, genomes, chunksize=4)):
            fo.write("\t".join(map(str, row)) + "\n"); tot.update(brk)
            if i % 500 == 0:
                print(i, flush=True)
    with open(f"{OUT}/breakdown.tsv", "w") as fo:
        fo.write("set\tstatus\tcontig_length\tgenes\n")
        for k, v in sorted(tot.items()):
            fo.write("\t".join(k) + f"\t{v}\n")
    print("done", flush=True)
