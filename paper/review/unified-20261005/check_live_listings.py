import importlib.util,json,urllib.request,urllib.parse,concurrent.futures
from pathlib import Path
R=Path(__file__).resolve().parents[3];spec=importlib.util.spec_from_file_location('v',R/'scripts/validation/verify_manuscript_listings.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
s='\n'.join((R/'paper'/n).read_text() for n in ['03_knowledge_representation.tex','knowledge_examples.tex']);prefix=v.read_prefixes(s)
def check(item):
 label,body=item;g=v.parse_listing(body,prefix);triples=g.serialize(format='nt');q='ASK { GRAPH <https://rubalkhali.science/graph/asserted/3.0.1> { '+triples+' } }';url='https://rubalkhali.science/sparql?'+urllib.parse.urlencode({'query':q,'format':'application/sparql-results+json'})
 try:
  with urllib.request.urlopen(url,timeout=25) as f:r=json.load(f)
  return {'label':label,'triples':len(g),'passed':r.get('boolean',False)}
 except Exception as e:return {'label':label,'triples':len(g),'error':str(e),'passed':False}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:rows=list(ex.map(check,[(a,b) for a,b in v.read_listings(s) if a.startswith('lst:ttl_')]))
r={'graph':'https://rubalkhali.science/graph/asserted/3.0.1','checks':rows,'passed':all(x['passed'] for x in rows)};Path(__file__).with_name('live-listing-check.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
