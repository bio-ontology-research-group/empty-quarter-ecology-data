"""Concatenate the 5,438 canonical representatives into one reference with a scaffold-to-bin file.
Usage: python build_reference.py membership.tsv dereplicated_dir out_prefix
Contig names are kept as in the catalogue (<sample>_<contig#>). Genome membership comes from the fasta file a contig
is in (not from its sample prefix). Representatives from the same sample but different binning strategies can share
assembly contigs; a contig name seen again in a later genome is dropped there (first genome, in membership order,
keeps it), so every contig belongs to exactly one genome. Dropped contigs are listed in <out>.dropped_dup_contigs.tsv."""
import sys, gzip, os, csv
memf, ddir, out = sys.argv[1:4]
mags = [r['mag'] for r in csv.DictReader(open(memf), delimiter='\t')]
seen = {}; n_drop = 0; bp = 0
with open(out + '.fa', 'w') as fa, open(out + '.stb', 'w') as stb, open(out + '.dropped_dup_contigs.tsv', 'w') as dr, \
     open(out + '.genome_sizes.tsv', 'w') as gs:
    dr.write('contig\tdropped_from\tkept_in\n'); gs.write('genome\tn_contigs\tbp\tn_dropped_dup\n')
    for m in mags:
        f = os.path.join(ddir, m + '.fa.gz'); keep = False; nc = nb = nd = 0
        if not os.path.exists(f): f = os.path.join(ddir, m + '.fa')   # 44 48PRr1 reps are plain .fa
        with (gzip.open(f, 'rt') if f.endswith('.gz') else open(f)) as fh:
            for line in fh:
                if line.startswith('>'):
                    c = line[1:].split()[0]
                    if c in seen:
                        keep = False; nd += 1; dr.write(f'{c}\t{m}\t{seen[c]}\n'); continue
                    seen[c] = m; keep = True; nc += 1
                    fa.write(f'>{c}\n'); stb.write(f'{c}\t{m}\n')
                elif keep:
                    fa.write(line); nb += len(line.strip())
        gs.write(f'{m}\t{nc}\t{nb}\t{nd}\n'); n_drop += nd; bp += nb
print(f'genomes {len(mags)}  contigs {len(seen)}  bp {bp}  duplicate contigs dropped {n_drop}')
