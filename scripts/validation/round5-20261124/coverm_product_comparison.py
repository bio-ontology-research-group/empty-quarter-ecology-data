import glob, os, re, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr, pearsonr
R='/home/leechuck/Documents/papers/empty-quarter-data-repo-r5'
os.chdir(os.path.expanduser('~/tmp/r5d/coverm'))
# bowtie2 logs
rows=[]
for f in sorted(glob.glob('mapping_logs/*.log')):
    s=os.path.basename(f)[:-4]; t=open(f).read()
    pairs=int(re.search(r'^(\d+) reads; of these', t, re.M).group(1))
    rate=float(re.search(r'([\d.]+)% overall alignment rate', t).group(1))
    rows.append((s,pairs,rate))
bt=pd.DataFrame(rows,columns=['sample','pairs_processed','bowtie2_overall_pct']).set_index('sample')
# refined coverage
rc={}; cf={}
for f in sorted(glob.glob('coverage/*.tsv')):
    s=os.path.basename(f)[:-4]
    d=pd.read_csv(f,sep='\t',index_col=0)
    d.columns=[c.replace(s+' ','') for c in d.columns]
    rc[s]=d['Read Count']; cf[s]=d['Covered Fraction']
rc=pd.DataFrame(rc); cf=pd.DataFrame(cf)
bt['refined_reads_ge95id']=rc.sum()
bt['refined_recruit_pct']=100*bt.refined_reads_ge95id/(2*bt.pairs_processed)
# coverm 0.7.0
q=pd.read_csv(f'{R}/metadata/cohorts/source/shotgun_mapping_qc_source.tsv',sep='\t').set_index('sample_id')
q=q[q.canonical_study_sample==True]
bt=bt.join(q[['mapped_percent','post_qc_reads','nonzero_representatives','included','core_site','nonzero_mapped']],how='left')
bt['capped']=bt.pairs_processed>=200000000
bt['cm070_minus_bowtie2']=bt.mapped_percent-bt.bowtie2_overall_pct
bt['cm070_minus_refined95']=bt.mapped_percent-bt.refined_recruit_pct
acc=pd.read_csv(f'{R}/metadata/cohorts/shotgun_cohort_accounting.tsv',sep='\t').set_index('sample')
bt=bt.join(acc[['in_546_core_transect','in_545_read_depth_model','trip']])
bt.to_csv('out/per_library_recruitment.tsv',sep='\t')
def med(x): return f"{np.median(x):.1f} (IQR {np.percentile(x,25):.1f}-{np.percentile(x,75):.1f})"
L=[]
for name,sub in [('551',bt),('546 core',bt[bt.in_546_core_transect==1]),('545',bt[bt.in_545_read_depth_model==1]),('550 nonzero',bt[bt.nonzero_mapped==True])]:
    L.append(f"{name}: n={len(sub)} bowtie2 overall {med(sub.bowtie2_overall_pct)}; refined >=95% id {med(sub.refined_recruit_pct)}; CoverM0.7.0 mapped {med(sub.mapped_percent.dropna())}")
# per-genome agreement
lg=pd.read_csv('rel_long.tsv.gz',sep='\t',header=None,names=['sample','genome','rel'])
un=lg[lg.genome=='unmapped'].set_index('sample').rel
chk=(100-un).reindex(bt.index)-bt.mapped_percent
L.append(f"long table vs QC table mapped% max abs diff: {np.nanmax(np.abs(chk)):.4f}")
rel=lg[lg.genome!='unmapped'].pivot(index='genome',columns='sample',values='rel').reindex(rc.index).fillna(0)
stats=[]
for s in rc.columns:
    if s not in rel.columns: continue
    a=rc[s]/rc[s].sum()*100 if rc[s].sum()>0 else rc[s]*0
    b=rel[s]/rel[s].sum()*100 if rel[s].sum()>0 else rel[s]*0
    det_a=cf[s]>=0.10; det_b=rel[s]>0
    both=(det_a&det_b).sum(); union=(det_a|det_b).sum()
    if a.sum()==0 or b.sum()==0: continue
    sp=spearmanr(a[det_a|det_b],b[det_a|det_b]).correlation if union>2 else np.nan
    pr=pearsonr(np.log10(a[det_a&det_b]),np.log10(b[det_a&det_b]))[0] if both>2 else np.nan
    bc=1-np.minimum(a,b).sum()/100
    top_a=a.idxmax(); top_b=b.idxmax()
    stats.append((s,int(det_a.sum()),int(det_b.sum()),int(both),both/union if union else np.nan,sp,pr,bc,top_a==top_b))
st=pd.DataFrame(stats,columns=['sample','detected_refined_cf10','detected_cm070','detected_both','detection_jaccard','spearman_union','pearson_log_both','bray_curtis_mapped_fraction','same_top_genome']).set_index('sample')
st.to_csv('out/per_library_genome_agreement.tsv',sep='\t')
L.append(f"genome agreement over {len(st)} libraries: Spearman (union of detected) median {st.spearman_union.median():.3f} (IQR {st.spearman_union.quantile(.25):.3f}-{st.spearman_union.quantile(.75):.3f}); Pearson log abundance among genomes detected by both median {st.pearson_log_both.median():.3f}; Bray-Curtis of mapped-read composition median {st.bray_curtis_mapped_fraction.median():.3f} (IQR {st.bray_curtis_mapped_fraction.quantile(.25):.3f}-{st.bray_curtis_mapped_fraction.quantile(.75):.3f}); detection Jaccard median {st.detection_jaccard.median():.3f}; same top genome in {st.same_top_genome.sum()} of {len(st)}")
L.append(f"detected genomes per library: refined cf>=0.10 median {st.detected_refined_cf10.median():.0f}; CoverM0.7.0 >0 median {st.detected_cm070.median():.0f}")
# correlation of recruitment
x=bt.dropna(subset=['mapped_percent'])
L.append(f"recruitment: CoverM0.7.0 minus bowtie2 overall: median {x.cm070_minus_bowtie2.median():.2f} pp (IQR {x.cm070_minus_bowtie2.quantile(.25):.2f} to {x.cm070_minus_bowtie2.quantile(.75):.2f}); higher in {(x.cm070_minus_bowtie2>0).sum()} of {len(x)}; Spearman {spearmanr(x.mapped_percent,x.bowtie2_overall_pct).correlation:.3f}")
L.append(f"recruitment: CoverM0.7.0 minus refined>=95%: median {x.cm070_minus_refined95.median():.2f} pp; Spearman {spearmanr(x.mapped_percent,x.refined_recruit_pct).correlation:.3f}")
L.append(f"capped libraries (200M pairs): {int(bt.capped.sum())}; their bowtie2 overall {med(bt[bt.capped].bowtie2_overall_pct)}")
# by platform / trip
lib=pd.read_csv(f'{R}/metadata/cohorts/shotgun_cohort_accounting.tsv',sep='\t').set_index('sample')
x=x.join(lib[['sequencer_platforms']])
for k,g in x.groupby('sequencer_platforms'):
    L.append(f"platform {k}: n={len(g)} diff median {g.cm070_minus_bowtie2.median():.2f} pp; bowtie2 {g.bowtie2_overall_pct.median():.1f}; cm070 {g.mapped_percent.median():.1f}")
open('out/summary.txt','w').write('\n'.join(L)+'\n'); print('\n'.join(L))
