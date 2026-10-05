"""Bind the data descriptor to the immutable KG and corrected ecology inputs."""
import hashlib
import json
from pathlib import Path
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence/kg-v3.0.1'

def test_release_metadata_and_paper_counts_agree():
    raw = (EVIDENCE/'manifest.json').read_bytes()
    manifest = json.loads(raw)
    public = json.loads((EVIDENCE/'publication-check.json').read_text())
    parsed = json.loads((EVIDENCE/'parsed-export.json').read_text())
    assert manifest['version'] == '3.0.1'
    assert manifest['counts']['asserted'] == parsed['quads'] == public['live_asserted_triples'] == 45707660
    assert parsed['passed'] and public['passed']
    assert public['manifest_sha256'] == hashlib.sha256(raw).hexdigest()
    assert manifest['input_manifest_sha256'] == hashlib.sha256((EVIDENCE/'input-modules-manifest.json').read_bytes()).hexdigest()
    records = ' '.join((ROOT/'paper/04_data_records.tex').read_text().split())
    assert '45,707,660 asserted triples from 16 manifested modules' in records
    usage = (ROOT/'paper/06_usage.tex').read_text()
    assert '10.5281/zenodo.23134168' in usage
    assert 'graph/asserted/3.0.1' in usage
    assert 'CC BY 4.0' in usage
    assert 'licence\nremain separate publication requirements' not in usage

def test_fifteen_observation_reference_modules_preserve_release_hashes():
    old = json.loads((ROOT/'evidence/kg-v3.0.0/input-modules-manifest.json').read_text())
    new = json.loads((EVIDENCE/'input-modules-manifest.json').read_text())
    before = {r['file']:r['sha256'] for r in old['records']}
    after = {r['file']:r['sha256'] for r in new['records']}
    checked = json.loads((EVIDENCE/'module-archive-validation.json').read_text())
    assert len(after) == checked['modules'] == 16
    assert checked['passed'] and checked['hashes'] == after
    assert {n for n in after if after[n] != before[n]} == {'rubalkhali.owl'}
    root = EVIDENCE/'rubalkhali.owl'
    assert hashlib.sha256(root.read_bytes()).hexdigest() == after[root.name]
    graph = Graph().parse(root)
    iri = URIRef('https://rubalkhali.science/kb/')
    assert (iri, OWL.versionInfo, Literal('3.0.1')) in graph
    terms = {s for t in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty) for s in graph.subjects(RDF.type,t) if str(s).startswith(str(iri)+'RAK_')}
    assert len(terms) == 342
    assert all(len(list(graph.objects(t, SKOS.definition))) == 1 for t in terms)

def test_corrected_companion_climate_files_are_selected_by_digest():
    selected = json.loads((ROOT/'metadata/climate/current_analysis_inputs.json').read_text())
    assert selected['site52'] == {'latitude':20.82784,'longitude':53.57835}
    for item in selected['inputs'].values():
        assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest() == item['sha256']
    assert 'climate inventory' in (ROOT/'paper/04_data_records.tex').read_text()
    # Published ecology inputs, independently pinned in the shared selector.
    assert selected['inputs']['daily_open_meteo']['sha256'] == '494acfb4b01728d00bdaea3cafc481dab2f4730386f5cd3e6c2734edfd5ac3de'

def test_paper_describes_nominal_depth_and_confirmed_funding():
    methods = ' '.join((ROOT/'paper/02_methods.tex').read_text().split())
    assert 'nominal 5--10 cm' in methods
    assert 'individual bulk subsurface depths' in methods
    assert 'No specific funding was received for this project.' in (ROOT/'paper/sn-article.tex').read_text()

def test_batch_claims_match_corrected_coordinate_replay():
    result = json.loads((ROOT/'evidence/batch-adjacency-20261004/outputs/batch_adjacency_results.json').read_text())
    t3 = result['trip3_JUL_M23']
    text = (ROOT/'paper/05_validation.tex').read_text()
    assert f"$+{t3['delta_stratified']:.3f}$" in text
    assert f"$p={t3['p_adjacent_more_similar']:.2f}$" in text
    provenance = json.loads((EVIDENCE/'definition-provenance.json').read_text())
    assert provenance['requested_generator'] == 'Claude Code --model sonnet'
    methods = (ROOT/'paper/03_knowledge_representation.tex').read_text()
    assert 'Claude Sonnet' in methods and 'automated review' in methods

def test_submission_prose_describes_final_data_and_confines_paths_to_data_records():
    import re
    names = ['sn-article.tex', '01_introduction.tex', '02_methods.tex', '04_data_records.tex',
             '02_methods_taxonomy.tex', '03_knowledge_representation.tex',
             '05_validation.tex', '06_usage.tex', 'knowledge_examples.tex',
             'env_table.tex']
    for name in names:
        text = (ROOT/'paper'/name).read_text()
        text = re.sub(r'(?<!\\)%[^\n]*', '', text)
        assert not re.search(r'workbook|worksheet|spreadsheet|correction ledger|Site[~ ]+52', text, re.I), name
        assert r'\path{' not in text, name
        assert not re.search(r'\\texttt\{[^}]*\.(?:tsv|csv|json|owl|ttl|nf|rq|md)\}', text), name
    records = (ROOT/'paper/04_data_records.tex').read_text()
    assert not re.search(r'\\(?:href|url|path)\{', records)
    assert 'https://' not in records and 'http://' not in records
    main = (ROOT/'paper/sn-article.tex').read_text()
    title = re.search(r'\\title\[[^]]*\]\{([^}]+)\}', main).group(1)
    abstract = re.search(r'\\abstract\{(.*?)\}\n', main, re.S).group(1)
    assert len(title) <= 110 and len(abstract.split()) <= 170
    assert not (ROOT/'paper/supplement.tex').exists()
    assert r'\input{knowledge_examples.tex}' in (ROOT/'paper/03_knowledge_representation.tex').read_text()
    field_data = ROOT/'metadata/environmental/environmental_measurements_curated.tsv'
    assert hashlib.sha256(field_data.read_bytes()).hexdigest() == '51177fb6b21e4b10712daaa731cdf3783d0fc351c536f562851efd233386573f'


def test_integrated_turtle_examples_parse_with_fragment_iris_and_comments():
    import importlib.util
    source = "\n".join((ROOT/'paper'/name).read_text() for name in
                       ['03_knowledge_representation.tex', 'knowledge_examples.tex'])
    for relative in ['scripts/validation/verify_manuscript_listings.py',
                     'scripts/manuscript/verify_manuscript_listings.py']:
        spec = importlib.util.spec_from_file_location('listing_validator', ROOT/relative)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        prefixes = validator.read_prefixes(source)
        listings = validator.read_listings(source)
        graphs = {label: validator.parse_listing(body, prefixes)
                  for label, body in listings if label.startswith('lst:ttl_')}
        assert len(graphs) == 7
        for graph in graphs.values():
            assert len(graph) > 0
        value = URIRef('https://rubalkhali.science/kb/RAK_4000001')
        predicate = URIRef('https://rubalkhali.science/kb/RAK_2000003')
        result = graphs['lst:ttl_temp'].value(value, predicate)
        assert str(result.datatype) == 'http://www.w3.org/2001/XMLSchema#double'
        assert float(result) == 20.7


def test_cross_paper_scan_handles_tex_numbers_and_ontology_labels():
    import importlib.util
    spec = importlib.util.spec_from_file_location('cross_paper', ROOT/'scripts/manuscript/check_cross_paper_consistency.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    text = {'methods': ['We retained $1{,}237$ profiles.',
                        'Trip 1, 64 sites visited',
                        'The ontology class Deep Soil Sample denotes the bulk compartment.']}
    assert checker.scan(text, '1,237')
    assert not any(checker.scan(text, pattern) for pattern, _ in checker.TERMINOLOGY)
    assert checker.scan({'bad': ['64 primary sites']}, checker.TERMINOLOGY[0][0])
