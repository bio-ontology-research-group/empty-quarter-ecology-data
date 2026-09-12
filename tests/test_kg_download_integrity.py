"""Actual HTTP/gzip/Raptor validation rejects corrupted release downloads."""
from functools import partial
import gzip
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/release/kg/verify_downloads.py'
SPEC = importlib.util.spec_from_file_location('kg_download_verifier', SCRIPT)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def auxiliary_fixture(release):
    coordinate = {'verification_code': []}
    for field, name in VERIFIER.PROOF_FILES.items():
        content = json.dumps({'name': name, 'scope': 'synthetic fixture'}).encode()
        (release / name).write_bytes(content)
        coordinate[field + '_url'] = '/downloads/kg/3.0.0/' + name
        coordinate[field + '_sha256'] = hashlib.sha256(content).hexdigest()
    for name in sorted(VERIFIER.VERIFICATION_CODE):
        content = ('# Synthetic test fixture for ' + name + '\n').encode()
        (release / name).write_bytes(content)
        coordinate['verification_code'].append(dict(name=name, url='/downloads/kg/3.0.0/' + name,
                                                   sha256=hashlib.sha256(content).hexdigest()))
    return coordinate


@pytest.mark.parametrize('flaw', [None, 'hash', 'wrong_graph', 'blank_line_count',
                                 'missing_graph', 'unsafe_name', 'duplicate_name', 'wrong_url', 'comments_allowed'])
def test_complete_download_and_rdf_parse(tmp_path, flaw):
    if not shutil.which('rapper'):
        pytest.skip('Raptor CLI required for RDF syntax check')
    release = tmp_path / 'http/downloads/kg/3.0.0'
    release.mkdir(parents=True)
    raw = b'<urn:s> <urn:p> "0.03035258267"^^<http://www.w3.org/2001/XMLSchema#double> <https://rubalkhali.science/graph/asserted/3.0.0> .\n'
    if flaw == 'wrong_graph':
        raw = raw.replace(b'https://rubalkhali.science/graph/asserted/3.0.0', b'urn:wrong-graph')
    elif flaw in ('blank_line_count', 'comments_allowed'):
        raw += b'\n# a comment is not a quad\n'
    elif flaw == 'missing_graph':
        raw = b'<urn:s> <urn:p> <https://rubalkhali.science/graph/asserted/3.0.0> .\n'
    compressed = gzip.compress(raw, mtime=0)
    name = 'asserted.nq.gz'
    (release / name).write_bytes(compressed)
    item = {'name': name, 'url': '/downloads/kg/3.0.0/' + name,
            'bytes': len(compressed), 'sha256': ('0' * 64 if flaw == 'hash' else hashlib.sha256(compressed).hexdigest()),
            'triples': 3 if flaw == 'blank_line_count' else 1,
            'graph': 'https://rubalkhali.science/graph/asserted/3.0.0',
            'uncompressed_sha256': hashlib.sha256(raw).hexdigest()}
    if flaw == 'unsafe_name':
        item['name'] = '../escape.nq.gz'
    elif flaw == 'wrong_url':
        item['url'] = '/downloads/kg/3.0.0/../elsewhere/' + name
    entries = [item, item] if flaw == 'duplicate_name' else [item]
    (release / 'manifest.json').write_text(json.dumps({'version': '3.0.0', 'files': entries,
        'coordinate_import': auxiliary_fixture(release)}))
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path / 'http')))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = tmp_path / 'verification'
    try:
        result = subprocess.run([sys.executable, str(SCRIPT), '--base-url',
                                 f'http://127.0.0.1:{server.server_port}', '--output-dir', str(out)],
                                capture_output=True, text=True, timeout=30)
    finally:
        server.shutdown()
        server.server_close()
    valid = flaw in (None, 'comments_allowed')
    assert (result.returncode == 0) is valid, result.stderr
    if not valid:
        assert not (out / 'report.json').exists()
    else:
        report = json.loads((out / 'report.json').read_text())
        assert report['software']['python'] == sys.version.split()[0]
        assert report['software']['raptor'] == subprocess.check_output(['rapper', '--version'], text=True).strip()
        assert report['software']['validator_sha256'] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        assert report['passed'] and report['files'][0]['rdf_syntax_checked']
        assert report['files'][0]['triples'] == 1
        assert report['files'][0]['graph'] == item['graph']
        assert len(report['files']) == 1  # Auxiliary proofs never enter the primary inventory.
        assert len(report['auxiliary_files']) == 8
        assert all(row['full_read'] is True and row['http_status'] == 200 for row in report['auxiliary_files'])
    assert not (tmp_path / 'escape.nq.gz.parser.log').exists()


@pytest.mark.parametrize('flaw', [None, 'changed_bytes', 'missing_file', 'partial_status',
    'partial_body', 'partial_header', 'redirect', 'empty_file'])
def test_auxiliary_full_http_hash_validation(tmp_path, flaw):
    release = tmp_path / 'http/downloads/kg/3.0.0'
    release.mkdir(parents=True)
    coordinate = auxiliary_fixture(release)
    target = release / 'wkt-closure-preservation.json'
    # More than one read block establishes that the verifier consumes EOF.
    target.write_bytes(b'x' * (1024 * 1024 + 123))
    coordinate['certificate_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    if flaw == 'changed_bytes':
        target.write_bytes(target.read_bytes()[:-1] + b'y')
    elif flaw == 'missing_file':
        target.unlink()
    elif flaw == 'empty_file':
        target.write_bytes(b'')
        coordinate['certificate_sha256'] = hashlib.sha256(b'').hexdigest()
    elif flaw == 'redirect':
        (release / 'redirected.json').write_bytes(target.read_bytes())
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith('/wkt-closure-preservation.json') and flaw == 'redirect':
                self.send_response(302)
                self.send_header('Location', '/downloads/kg/3.0.0/redirected.json')
                self.end_headers()
            elif self.path.endswith('/wkt-closure-preservation.json') and flaw in ('partial_status', 'partial_body', 'partial_header'):
                self.send_response(206 if flaw == 'partial_status' else 200)
                if flaw == 'partial_header':
                    self.send_header('Content-Range', 'bytes 0-0/1048699')
                self.send_header('Content-Length', '1')
                self.end_headers()
                self.wfile.write(b'x')
            else:
                super().do_GET()
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(tmp_path / 'http')))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / 'out'
    output.mkdir()
    try:
        entries = VERIFIER.auxiliary_entries({'coordinate_import': coordinate})
        if flaw:
            with pytest.raises((RuntimeError, OSError)):
                VERIFIER.verify_auxiliary(f'http://127.0.0.1:{server.server_port}', entries, output)
        else:
            rows = VERIFIER.verify_auxiliary(f'http://127.0.0.1:{server.server_port}', entries, output)
            assert len(rows) == 8
            assert rows[0]['bytes'] == 1024 * 1024 + 123
            assert {row['name'] for row in rows} == set(VERIFIER.PROOF_FILES.values()) | VERIFIER.VERIFICATION_CODE
            for row in rows:
                assert row['sha256'] == hashlib.sha256((release / row['name']).read_bytes()).hexdigest()
                assert row['url'] == '/downloads/kg/3.0.0/' + row['name']
                assert row['http_status'] == 200 and row['full_read'] is True and row['passed'] is True
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('flaw', ['missing', 'missing_code', 'duplicate_code', 'wrong_code',
    'wrong_code_url', 'wrong_proof_url', 'invalid_code_hash', 'invalid_proof_hash'])
def test_auxiliary_inventory_fails_closed(tmp_path, flaw):
    coordinate = auxiliary_fixture(tmp_path)
    if flaw == 'missing':
        coordinate = None
    elif flaw == 'missing_code':
        coordinate['verification_code'].pop()
    elif flaw == 'duplicate_code':
        coordinate['verification_code'][0] = coordinate['verification_code'][1]
    elif flaw == 'wrong_code':
        coordinate['verification_code'][0]['name'] = 'different.py'
    elif flaw == 'wrong_code_url':
        coordinate['verification_code'][0]['url'] = 'https://other.example/code.py'
    elif flaw == 'wrong_proof_url':
        coordinate['certificate_url'] = '/downloads/kg/2.0.6/wkt-closure-preservation.json'
    elif flaw == 'invalid_code_hash':
        coordinate['verification_code'][0]['sha256'] = 'wrong'
    else:
        coordinate['repair_plan_sha256'] = 'wrong'
    with pytest.raises(ValueError):
        VERIFIER.auxiliary_entries({'coordinate_import': coordinate})
