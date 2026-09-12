import importlib.util
import json
from pathlib import Path
import shutil
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/release/kg/package_asserted_release.py'
SPEC = importlib.util.spec_from_file_location('package_asserted_release', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def source_fixture(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = {'version': '3.0.0', 'module_count': 16,
                'records': [{'file': f'module-{i}.ttl', 'sha256': str(i).zfill(64)} for i in range(16)]}
    files = {
        'README.md': 'Historical source release instructions.\n',
        'scripts/release/kg/prepare_wkt_import.py': 'pass\n',
        'scripts/rdf/generate_ph_dataset.py': 'old producer\n',
        'scripts/release/rebuild_public_sources.sh': 'old driver\n',
        'data/metadata/samples/ph/version_registry.tsv': 'predecessor\n',
        'data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.0/manifest.json': '{}\n',
        'expected/fresh_modules_manifest.json': json.dumps(manifest),
        'data/metadata/frozen.tsv': 'scientific\tinput\n',
    }
    records = []
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        records.append({'path': name, 'bytes': path.stat().st_size, 'sha256': MODULE.digest(path),
                        'source_path': '/private/operator/tree/' + name})
    (source / 'SOURCE_MANIFEST.json').write_text(json.dumps({'version': '3.0.0', 'records': records}))
    for name in MODULE.PH_FILES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name.removeprefix('data/'), target)
    (source / 'scripts/rdf/generate_ph_dataset.py').write_text('new producer\n')
    (source / 'database.private.env').write_text('DBA_PASSWORD=NEVER-PUBLISH\n')
    (source / 'expected/ph_v1_0_1_reference.ttl').write_text('UNLISTED GENERATED PAYLOAD\n')
    replay = tmp_path / 'replay.json'
    replay.write_text(json.dumps({'mode': '--all', 'passed': True, 'checks': [
        dict(file=row['file'], sha256=row['sha256'], expected_sha256=row['sha256'], passed=True)
        for row in manifest['records']]}))
    return source, manifest, replay


def test_source_whitelist_retains_dependencies_and_excludes_private_payloads(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    clean = tmp_path / 'clean'
    names, transition = MODULE.source_package(source, clean, manifest, replay, SCRIPT)
    assert 'data/metadata/frozen.tsv' in names
    assert 'data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.0/manifest.json' in names
    assert set(MODULE.PH_FILES) <= set(names)
    assert 'database.private.env' not in names
    assert 'expected/ph_v1_0_1_reference.ttl' not in names
    assert '/private/operator' not in (clean / 'SOURCE_MANIFEST.json').read_text()
    assert (clean / 'historical/predecessor-README.md').read_text() == (source / 'README.md').read_text()
    assert transition['changed'][0]['path'] == 'scripts/rdf/generate_ph_dataset.py'
    frozen = MODULE.read(clean / 'SOURCE_MANIFEST.json')
    assert all(MODULE.digest(clean / row['path']) == row['sha256'] for row in frozen['records'])
    assert 'asserted data only' in (clean / 'README.md').read_text()


def test_unapproved_scientific_input_change_fails(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    (source / 'data/metadata/frozen.tsv').write_text('changed\n')
    with pytest.raises(ValueError, match='Unapproved predecessor source change'):
        MODULE.source_package(source, tmp_path / 'clean', manifest, replay, SCRIPT)


def test_replay_must_match_all_sixteen_modules(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    evidence = MODULE.read(replay)
    evidence['checks'] = evidence['checks'][:-1]
    replay.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='Independent replay'):
        MODULE.source_package(source, tmp_path / 'clean', manifest, replay, SCRIPT)


def test_published_confirmation_must_have_reviewed_exact_bytes(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    (source / (MODULE.PH + 'confirmation.json')).write_text('{"mail_body":"private"}')
    with pytest.raises(ValueError, match='pH provenance hash mismatch'):
        MODULE.source_package(source, tmp_path / 'clean', manifest, replay, SCRIPT)


def test_archive_is_exact_and_refuses_overwrite(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    clean = tmp_path / 'clean'
    names, _ = MODULE.source_package(source, clean, manifest, replay, SCRIPT)
    target = tmp_path / 'source.tar.gz'
    record = MODULE.archive(clean, names, target, 'rubalkhali-kg-3.0.0-source')
    assert record['sha256'] == MODULE.digest(target)
    with tarfile.open(target) as archive:
        assert {member.name.split('/', 1)[1] for member in archive.getmembers()} == set(names)
        assert all(member.isfile() for member in archive.getmembers())
    with pytest.raises(FileExistsError):
        MODULE.archive(clean, names, target, 'rubalkhali-kg-3.0.0-source')


def test_symlink_and_parent_paths_rejected(tmp_path):
    (tmp_path / 'payload').write_text('safe')
    (tmp_path / 'link').symlink_to(tmp_path / 'payload')
    with pytest.raises(ValueError):
        MODULE.checked_source(tmp_path, 'link')
    with pytest.raises(ValueError):
        MODULE.checked_source(tmp_path, '../payload')


def test_explicit_import_overlay_adds_missing_adapter_and_records_hashes(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    # Model the reviewed r7 archive, which had no WKT adapter in its whitelist.
    original = MODULE.read(source / 'SOURCE_MANIFEST.json')
    original['records'] = [row for row in original['records']
                           if row['path'] != 'scripts/release/kg/prepare_wkt_import.py']
    (source / 'SOURCE_MANIFEST.json').write_text(json.dumps(original))
    code = tmp_path / 'release-code'
    code.mkdir()
    for name in MODULE.IMPORT_FILES:
        (code / name).write_text('frozen ' + name + '\n')
    (code / 'database.private.env').write_text('NEVER-PUBLISH')
    clean = tmp_path / 'clean'
    names, transition = MODULE.source_package(source, clean, manifest, replay, SCRIPT, code)
    for name in MODULE.IMPORT_FILES:
        relative = 'scripts/release/kg/' + name
        assert relative in names
        assert MODULE.digest(clean / relative) == MODULE.digest(code / name)
    assert len(transition['import_code_updates']) == len(MODULE.IMPORT_FILES)
    assert 'scripts/release/kg/database.private.env' not in names
    assert (clean / 'scripts/rdf/generate_ph_dataset.py').read_bytes() == (source / 'scripts/rdf/generate_ph_dataset.py').read_bytes()


def test_changed_predecessor_import_code_is_preserved(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    code = tmp_path / 'release-code'
    code.mkdir()
    for name in MODULE.IMPORT_FILES:
        (code / name).write_text('new import code ' + name + '\n')
    clean = tmp_path / 'clean'
    names, transition = MODULE.source_package(source, clean, manifest, replay, SCRIPT, code)
    historical = 'historical/import-code/prepare_wkt_import.py'
    assert historical in names
    assert (clean / historical).read_bytes() == (source / 'scripts/release/kg/prepare_wkt_import.py').read_bytes()
    adapter = next(row for row in transition['import_code_updates'] if row['path'].endswith('/prepare_wkt_import.py'))
    assert adapter['predecessor_sha256'] == MODULE.digest(clean / historical)


def test_updated_query_listing_excludes_manuscript_prose(tmp_path):
    source, manifest, replay = source_fixture(tmp_path)
    path = source / 'paper/05_validation.tex'
    path.parent.mkdir()
    listing = '\\begin{lstlisting}[language=SPARQL]\nSELECT ?count WHERE {} ORDER BY DESC(?count)\n\\end{lstlisting}'
    path.write_text('\n'.join([listing] * 3))
    original = MODULE.read(source / 'SOURCE_MANIFEST.json')
    original['records'].append(dict(path='paper/05_validation.tex', bytes=path.stat().st_size, sha256=MODULE.digest(path)))
    (source / 'SOURCE_MANIFEST.json').write_text(json.dumps(original))
    path.write_text('PRIVATE MANUSCRIPT PROSE\n' + path.read_text().replace('DESC(?count)', 'DESC(xsd:double(?count))'))
    clean = tmp_path / 'clean'
    _, transition = MODULE.source_package(source, clean, manifest, replay, SCRIPT)
    published = (clean / 'paper/05_validation.tex').read_text()
    assert 'PRIVATE MANUSCRIPT PROSE' not in published
    assert published.count('DESC(xsd:double(?count))') == 3
    assert transition['printed_query_projection']['published_sha256'] == MODULE.digest(clean / 'paper/05_validation.tex')
