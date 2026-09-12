import importlib.util
from pathlib import Path
import gzip
import subprocess
import sys
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/release/kg/prepare_wkt_import.py'
spec = importlib.util.spec_from_file_location('wkt_import', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('fmt,line', [
    ('xml', '<geo:asWKT rdf:datatype="'+module.WKT+'">POINT(51.14483 20.644662222222223)</geo:asWKT>\n'),
    ('nq', '<urn:s> <urn:p> "POINT(51.14483 20.644662222222223)"^^<'+module.WKT+'> <urn:g> .\n'),
])
def test_only_whitespace_changes_and_adapter_is_idempotent(fmt, line):
    adapted, count = module.adapt_line(line, fmt)
    assert count == 1
    assert adapted == line.replace('POINT(', 'POINT (')
    assert module.adapt_line(adapted, fmt) == (adapted, 0)


@pytest.mark.parametrize('line', ['<urn:s> <urn:p> "POINT(1 2)" <urn:g> .\n',
    '<urn:s> <urn:p> "POINT(1 2)"^^<urn:other> <urn:g> .\n',
    '<urn:s> <urn:p> "POLYGON((1 2,3 4,1 2))"^^<'+module.WKT+'> <urn:g> .\n'])
def test_unrelated_literals_unchanged(line):
    assert module.adapt_line(line, 'nq') == (line, 0)


def test_gzip_source_preserved_and_output_exclusive(tmp_path):
    source = tmp_path / 'source.nq.gz'
    text = '<urn:s> <urn:p> "POINT(1 2)"^^<'+module.WKT+'> <urn:g> .\n'
    with gzip.open(source, 'wt') as out:
        out.write(text)
    original = source.read_bytes()
    output = tmp_path / 'loader.nq'
    report = module.prepare(source, output, 'nq')
    assert source.read_bytes() == original
    assert output.read_text() == text.replace('POINT(', 'POINT (')
    assert report['typed_point_whitespace_changes'] == 1
    with pytest.raises(ValueError):
        module.prepare(source, output, 'nq')


@pytest.mark.parametrize('collision', ['source','output','dangling_symlink'])
def test_cli_rejects_report_path_collisions(tmp_path, collision):
    source=tmp_path/'source.nq'; source.write_text('<urn:s> <urn:p> "text" .\n')
    original=source.read_bytes(); output=tmp_path/'output.nq'
    report=source if collision=='source' else output
    if collision=='dangling_symlink':
        report=tmp_path/'report.json'; report.symlink_to(tmp_path/'absent')
    result=subprocess.run([sys.executable,str(SCRIPT),'--source',str(source),'--output',str(output),'--format','nq','--report',str(report)],capture_output=True)
    assert result.returncode != 0
    assert source.read_bytes()==original and not output.exists()


def test_frozen_site_module_changes_70_points_not_polygon(tmp_path):
    from rdflib import Graph, Namespace
    source=SCRIPT.parents[3]/'ontology/rubalkhali_sites.owl'
    if not source.exists():
        pytest.skip('frozen module is not packaged alongside this isolated test')
    output=tmp_path/'loader.owl'
    report=module.prepare(source,output,'xml')
    assert report['typed_point_whitespace_changes']==70
    geo=Namespace('http://www.opengis.net/ont/geosparql#')
    before=Graph().parse(str(source),format='xml'); after=Graph().parse(str(output),format='xml')
    assert len(before)==len(after)
    old=list(before.subject_objects(geo.asWKT)); new=dict(after.subject_objects(geo.asWKT))
    assert len(old)==71
    assert sum(str(o).startswith('POLYGON') for s,o in old)==1
    for subject,literal in old:
        assert str(new[subject])==str(literal).replace('POINT(','POINT (',1)
        assert new[subject].datatype==literal.datatype
