import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/release/kg'
sys.path.insert(0, str(DIRECTORY))
SPEC = importlib.util.spec_from_file_location('kg_loader_wkt', DIRECTORY / 'load_asserted.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def source(tmp_path, count=70):
    inputs = tmp_path / 'inputs/scientific'
    inputs.mkdir(parents=True)
    path = inputs / 'rubalkhali_sites.owl'
    row = '<geo:asWKT rdf:datatype="http://www.opengis.net/ont/geosparql#wktLiteral">POINT(51.1 20.644662222222223)</geo:asWKT>\n'
    path.write_text(row * count)
    return inputs, path, dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def test_only_sites_receive_separate_hashed_loader_copy(tmp_path):
    inputs, path, record = source(tmp_path)
    original = path.read_bytes()
    directory, report = MODULE.loader_input(inputs, path, record)
    assert directory == '/release-inputs/loader'
    assert report['typed_point_whitespace_changes'] == 70
    assert report['source_sha256'] == record['sha256']
    assert path.read_bytes() == original
    assert (inputs.parent / 'loader' / path.name).read_bytes() == original.replace(b'POINT(', b'POINT (')


def test_other_modules_remain_exact_original_inputs(tmp_path):
    directory, report = MODULE.loader_input(tmp_path, tmp_path / 'taxonomy_abox.ttl', {'file': 'taxonomy_abox.ttl'})
    assert (directory, report) == ('/release-inputs/scientific', None)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('flaw', ['count', 'hash', 'existing'])
def test_changed_or_existing_loader_input_is_rejected(tmp_path, flaw):
    inputs, path, record = source(tmp_path, count=69 if flaw == 'count' else 70)
    if flaw == 'hash':
        record['sha256'] = '0' * 64
    if flaw == 'existing':
        (inputs.parent / 'loader').mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        MODULE.loader_input(inputs, path, record)
