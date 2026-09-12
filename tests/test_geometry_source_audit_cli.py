import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest
from rdflib import Graph, Literal, Namespace, URIRef

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts/release/kg'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('geometry_source_audit',SCRIPTS/'audit_geometry_rule_reachability.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def inventory(tmp_path):
    rows=[]
    for n in range(16):
        name=f'module{n}.owl';data=b'<source/>'
        (tmp_path/name).write_bytes(data)
        rows.append(dict(file=name,sha256=hashlib.sha256(data).hexdigest()))
    return dict(records=rows)


def test_cli_explicit_paths_and_historical_defaults(monkeypatch,tmp_path):
    calls=[];monkeypatch.setattr(module,'audit',lambda source,output:calls.append((source,output)))
    module.main([])
    module.main(['--source',str(tmp_path/'source'),'--output',str(tmp_path/'out.json')])
    assert calls==[(module.SOURCE,module.OUTPUT),(tmp_path/'source',tmp_path/'out.json')]


def test_exact16_regular_unique_sources(tmp_path):
    manifest=inventory(tmp_path)
    assert len(module.checked_records(manifest,tmp_path))==16
    with pytest.raises(ValueError,match='exactly 16'):
        module.checked_records(dict(records=manifest['records'][:-1]),tmp_path)
    manifest['records'][-1]=manifest['records'][0].copy()
    with pytest.raises(ValueError,match='unique'):
        module.checked_records(manifest,tmp_path)


@pytest.mark.parametrize('name',['../escape.owl','/absolute.owl','dir/file.owl','dir\\file.owl','bad\nfile.owl'])
def test_unsafe_manifest_names_rejected(tmp_path,name):
    manifest=inventory(tmp_path);manifest['records'][0]['file']=name
    with pytest.raises(ValueError,match='safe basename'):
        module.checked_records(manifest,tmp_path)


def test_symlink_source_rejected(tmp_path):
    manifest=inventory(tmp_path)
    (tmp_path/'module0.owl').unlink();(tmp_path/'module0.owl').symlink_to(tmp_path/'module1.owl')
    with pytest.raises(ValueError,match='nonsymlink'):
        module.checked_records(manifest,tmp_path)


def test_exact71_geometries_and70_points():
    geo=Namespace('http://www.opengis.net/ont/geosparql#');graph=Graph()
    for n in range(70):graph.add((URIRef(f'urn:site:{n}'),geo.asWKT,Literal(f'POINT({n} 20)',datatype=geo.wktLiteral)))
    graph.add((URIRef('urn:polygon'),geo.asWKT,Literal('POLYGON((0 0,1 0,0 0))',datatype=geo.wktLiteral)))
    assert len(module.checked_geometry_inventory(graph,geo))==71
    graph.remove((URIRef('urn:site:0'),None,None))
    with pytest.raises(ValueError,match='71 geometry facts'):
        module.checked_geometry_inventory(graph,geo)
