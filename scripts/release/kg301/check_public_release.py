#!/usr/bin/env python3
"""Read-only checks of the immutable KG 3.0.1 publication and live graph."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, SKOS
BASE = 'https://bio2vec.net/data/empty-quarter/kg/3.0.1/'

def fetch(url, mime=None):
    with urlopen(Request(url, headers={'Accept': mime} if mime else {}), timeout=90) as response:
        return response.read()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = fetch(BASE + 'manifest.json')
    manifest = json.loads(raw)
    assert manifest['counts']['asserted'] == 45707660
    assert manifest['default_graph'] == 'https://rubalkhali.science/graph/asserted/3.0.1'
    assert manifest['release_mode'] == 'asserted-only'
    inputs = fetch(BASE + 'input-modules-manifest.json')
    assert hashlib.sha256(inputs).hexdigest() == manifest['input_manifest_sha256']
    assert len(json.loads(inputs)['records']) == 16
    canonical = None
    checks = ['release manifest and checksum-pinned sixteen-module inventory']
    for mime, fmt in [('application/rdf+xml','xml'),('text/turtle','turtle'),('application/ld+json','json-ld'),('application/n-triples','nt')]:
        g = Graph().parse(data=fetch('https://rubalkhali.science/kb/v3.0.1/', mime), format=fmt)
        root = URIRef('https://rubalkhali.science/kb/')
        assert (root, OWL.versionInfo, Literal('3.0.1')) in g
        terms = {s for t in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty) for s in g.subjects(RDF.type,t) if str(s).startswith(str(root)+'RAK_')}
        assert len(terms) == 342
        assert all(len(list(g.objects(t, SKOS.definition))) == 1 for t in terms)
        if canonical is not None: assert isomorphic(canonical, g)
        canonical = g
        checks.append('immutable ontology route ' + mime)
    for target in canonical.objects(root, OWL.imports):
        with urlopen(Request(str(target), method='HEAD'), timeout=90) as response:
            assert response.status == 200
        checks.append('reference import resolves: ' + str(target))
    query = 'SELECT (COUNT(*) AS ?n) FROM <https://rubalkhali.science/graph/asserted/3.0.1> WHERE { ?s ?p ?o }'
    result = json.loads(fetch('https://rubalkhali.science/sparql?' + urlencode({'query':query,'format':'application/sparql-results+json'}), 'application/sparql-results+json'))
    count = int(result['results']['bindings'][0]['n']['value'])
    assert count == manifest['counts']['asserted']
    checks.append('live named asserted graph count')
    record = json.loads(fetch('https://zenodo.org/api/records/23134168'))
    names = {f['key']:f for f in record['files']}
    assert record['doi'] == '10.5281/zenodo.23134168'
    for item in manifest['files']: assert names[item['name']]['size'] == item['bytes']
    checks.append('Zenodo DOI and manifested artifact sizes')
    report = {'passed':True,'checked_utc':datetime.now(timezone.utc).isoformat(),'manifest_sha256':hashlib.sha256(raw).hexdigest(),'live_asserted_triples':count,'checks':checks,
              'scope':'Immutable version route and release; the unversioned ontology route may serve a later metadata revision.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS:',len(checks),'public release checks')
if __name__ == '__main__': main()
