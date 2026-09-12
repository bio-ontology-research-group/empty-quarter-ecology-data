#!/usr/bin/env python3
"""Package an immutable asserted-only KG release; never load, infer or deploy."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile

VERSION = '3.0.0'
GRAPH = 'https://rubalkhali.science/graph/asserted/3.0.0'
DOWNLOAD = '/downloads/kg/3.0.0/'
PH = 'data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1/'
PH_FILES = tuple(PH + name for name in (
    'ph_measurements.xlsx', 'manifest.json', 'trip4_specimen_reconciliation.tsv', 'confirmation.json'))
ALLOWED_CHANGED = {
    'scripts/rdf/generate_ph_dataset.py', 'scripts/release/rebuild_public_sources.sh',
    'data/metadata/samples/ph/version_registry.tsv', 'expected/fresh_modules_manifest.json',
    'paper/05_validation.tex',
}
IMPORT_FILES = ('prepare_wkt_import.py', 'WKT_IMPORT.md', 'load_asserted.py', 'kg_admin.py',
                'query_gates.py', 'asserted_release_gates.py', 'verify_downloads.py',
                'check_engine_contract.py', 'export_fixture.ttl')
POLICY = ('Explicit predecessor scientific-source whitelist plus the four confirmed pH successor inputs, '
          'current replay proof, nine named import/acceptance files, printed SELECT projections and public packaging code. '
          'No private correspondence, credentials, '
          'unlisted generated reference payloads or repository crawl. Source-manifest operator paths are removed. '
          'Original scientific tables and third-party notices are retained. No new licence is granted.')


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def checked_source(root, relative):
    rel = PurePosixPath(relative)
    require(not rel.is_absolute() and '..' not in rel.parts, 'Unsafe source path')
    path = root / relative
    require(path.is_file() and not path.is_symlink() and root in path.resolve().parents,
            'Source must be an internal regular file: ' + relative)
    return path


def archive(root, names, target, prefix):
    require(len(names) == len(set(names)), 'Duplicate archive member')
    with target.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw,
                                               compresslevel=1, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as tar:
            for name in sorted(names):
                path = checked_source(root, name)
                info = tarfile.TarInfo(prefix + '/' + name)
                info.size, info.mode, info.mtime = path.stat().st_size, 0o644, 0
                with path.open('rb') as stream:
                    tar.addfile(info, stream)
    return dict(name=target.name, url=DOWNLOAD + target.name,
                bytes=target.stat().st_size, sha256=digest(target), media_type='application/gzip')


def verify_modules(manifest, inputs):
    records = manifest['records']
    require(manifest.get('version') == VERSION and manifest.get('module_count') == 16
            and len(records) == 16 and len({r['file'] for r in records}) == 16,
            'Exactly sixteen distinct versioned modules required')
    require('rubalkhali_ph_eq_ph_shared_v1_0_1.ttl' in {r['file'] for r in records}
            and 'rubalkhali_ph_eq_ph_shared_v1_0_0.ttl' not in {r['file'] for r in records},
            'Only the confirmed successor pH module belongs in the asserted union')
    for record in records:
        path = checked_source(inputs, record['file'])
        require('/' not in record['file'] and record['load_graph'] == GRAPH
                and path.stat().st_size == record['bytes'] and digest(path) == record['sha256'],
                'Module hash, size or graph mismatch: ' + record['file'])


def source_package(source, clean, module_manifest, replay_path, packaging_code, import_code=None):
    """Copy only the old reviewed whitelist and explicitly enumerated additions."""
    original = read(source / 'SOURCE_MANIFEST.json')
    require(original.get('version') == VERSION, 'Expected versioned predecessor source whitelist')
    records = original['records']
    require(len(records) == len({r['path'] for r in records}), 'Duplicate source whitelist entry')
    replay = read(replay_path)
    expected = {r['file']: r['sha256'] for r in module_manifest['records']}
    checks = replay.get('checks', [])
    require(replay.get('passed') is True and replay.get('mode') == '--all'
            and len(checks) == 16 and {r['file']: r['sha256'] for r in checks} == expected
            and all(r.get('passed') is True and r['sha256'] == r['expected_sha256'] for r in checks),
            'Independent replay must match every current module hash')
    current_expected = read(source / 'expected/fresh_modules_manifest.json')
    require(current_expected == module_manifest, 'Source and loaded module manifests differ')
    clean.mkdir(parents=True, exist_ok=False)
    paths, changed = set(), []
    query_projection = None
    for record in records:
        relative = record['path']
        path = checked_source(source, relative)
        actual = digest(path)
        if actual != record['sha256'] or path.stat().st_size != record['bytes']:
            require(relative in ALLOWED_CHANGED, 'Unapproved predecessor source change: ' + relative)
            changed.append(dict(path=relative, predecessor_sha256=record['sha256'], sha256=actual))
        target = clean / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if relative == 'paper/05_validation.tex':
            listings = re.findall(r'\\begin\{lstlisting\}\[[\s\S]*?\\end\{lstlisting\}', path.read_text())
            require(len(listings) == 3, 'Exactly three printed scientific SELECT listings required')
            target.write_text('% Printed scientific SELECT queries; extracted without manuscript prose.\n'
                              + '\n\n'.join(listings) + '\n')
            query_projection = dict(path=relative, source_sha256=actual, published_sha256=digest(target),
                scope='Three exact printed SELECT listings only, including numeric count ordering; manuscript prose excluded. Scientific module hashes unchanged.')
        paths.add(relative)
    for relative in PH_FILES:
        target = clean / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_source(source, relative), target)
        paths.add(relative)
    import_changes = []
    if import_code is not None:
        import_code = Path(import_code).resolve()
        for name in IMPORT_FILES:
            original = checked_source(import_code, name)
            relative = 'scripts/release/kg/' + name
            target = clean / relative
            prior_hash = digest(target) if target.exists() else None
            if prior_hash is not None and prior_hash != digest(original):
                historical_name = 'historical/import-code/' + name
                historical = clean / historical_name
                historical.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, historical)
                paths.add(historical_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            require(digest(target) == digest(original), 'Frozen release import code changed during copying')
            paths.add(relative)
            import_changes.append(dict(path=relative, predecessor_sha256=prior_hash,
                                       sha256=digest(target),
                                       scope='Explicit frozen asserted-release import and acceptance code; scientific generators unchanged.'))
    version = read(clean / (PH + 'manifest.json'))
    reconciliation = version['specimen_reconciliation']
    require(version['dataset_version'] == 'EQ-PH-SHARED-v1.0.1', 'Wrong pH source version')
    for name, hash_key in [('trip4_specimen_reconciliation.tsv', 'mapping_sha256'),
                           ('confirmation.json', 'evidence_sha256')]:
        require(digest(clean / (PH + name)) == reconciliation[hash_key], 'pH provenance hash mismatch')
    require(digest(clean / (PH + 'ph_measurements.xlsx')) == version['source']['sha256'],
            'pH workbook hash mismatch')
    confirmation = read(clean / (PH + 'confirmation.json'))
    require(set(confirmation) == {'confirmed_at', 'evidence_id', 'fact', 'scope', 'source_role', 'supersedes'}
            and digest(clean / (PH + 'confirmation.json')) ==
            'f9e1dbd92c35612fe139db94eb62230d0999cf7df12a78c5763a386d78d2d9a8',
            'Only reviewed factual pH provenance may be published; no correspondence')
    # Historical evidence remains intact and is identified as predecessor evidence.
    historical = clean / 'historical/predecessor-README.md'
    historical.parent.mkdir(exist_ok=True)
    shutil.move(str(clean / 'README.md'), historical)
    paths.add('historical/predecessor-README.md')
    (clean / 'README.md').write_text(source_readme())
    for relative, origin in [('validation/asserted-source-rebuild.json', replay_path),
                             ('scripts/release/kg/package_asserted_release.py', packaging_code)]:
        target = clean / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        paths.add(relative)
    transition = dict(predecessor_source_manifest_sha256=digest(source / 'SOURCE_MANIFEST.json'),
                      changed=changed, added=list(PH_FILES),
                      import_code_updates=import_changes,
                      printed_query_projection=query_projection,
                      current_module_manifest_sha256=digest(source / 'expected/fresh_modules_manifest.json'),
                      independent_rebuild_report_sha256=digest(replay_path),
                      predecessor_evidence_scope='Other validation records were generated for the predecessor; current proof is asserted-source-rebuild.json.')
    write_json(clean / 'validation/ph-successor-source-transition.json', transition)
    paths.add('validation/ph-successor-source-transition.json')
    new_records = [dict(path=name, bytes=(clean / name).stat().st_size, sha256=digest(clean / name))
                   for name in sorted(paths)]
    frozen = dict(version=VERSION, release_mode='asserted-only', files=len(new_records),
                  bytes=sum(r['bytes'] for r in new_records), policy=POLICY, records=new_records)
    # Do not retain private/operator source_path strings from the predecessor manifest.
    (clean / 'SOURCE_MANIFEST.json').write_text(json.dumps(frozen, indent=2) + '\n')
    (clean / 'SOURCE_SHA256SUMS').write_text(''.join(r['sha256'] + '  ' + r['path'] + '\n' for r in new_records))
    return sorted(paths | {'SOURCE_MANIFEST.json', 'SOURCE_SHA256SUMS'}), transition


def source_readme():
    return '''# Rub al-Khali KG 3.0.0: asserted source release

This package regenerates all 16 asserted modules, including the confirmed
EQ-PH-SHARED-v1.0.1 specimen mapping. Inference is a separate ongoing operation;
this release contains and advertises asserted data only.

The inputs are frozen scientific tables, workbooks, ontologies and producer
code. This rebuild does not reconstruct historical raw-read processing.
No private correspondence, credentials or operator configuration is included.
The pH confirmation is a reviewed factual provenance record, not an email.

## Rebuild all modules

Use Linux x86-64 with at least 48 GB available RAM and 30 GB output space.
The pinned generation runtime is Python 3.11.14, Java 21.0.10, Groovy 4.0.28
and RDFLib 7.1.4. Environment installation and pinned Maven dependency
resolution require network access; scientific inputs are bundled.

```sh
sha256sum -c SOURCE_SHA256SUMS
micromamba create -y -p "$PWD/.runtime" --file environment/conda-linux-64.lock
micromamba run -p "$PWD/.runtime" python -m pip install --no-deps --require-hashes -r environment/pip-overlay.lock.txt
export CONDA_PREFIX="$PWD/.runtime"
export JAVA_HOME="$CONDA_PREFIX/lib/jvm"
export PATH="$CONDA_PREFIX/bin:$PATH"
bash scripts/release/rebuild_public_sources.sh "$PWD" /absolute/path/to/new-output
```

The output directory must be new. The final gate compares all 16 hashes with
expected/fresh_modules_manifest.json. The independent current replay is
validation/asserted-source-rebuild.json. Other archived validation records
and historical/predecessor-README.md describe the predecessor investigation;
they do not certify this release's entailment or deployment.

Follow scripts/release/kg/WKT_IMPORT.md before importing original site XML
or native N-Quads into Virtuoso. The source-preserving POINT whitespace
adapter retains coordinate digits and prevents the engine's binary32 path.
Load exactly one serialization of each manifested module into the asserted
graph. Never load both pH versions or the retired rubalkhali_kb.owl alias.

The included materializer and its tests support separate future reasoning
work; no partial inferred output belongs to this release. Public query and
download acceptance evidence is supplied separately by the deployment.
No new licence is granted. Preserve existing third-party terms and notices.

## Verify a deployed asserted-only release

From this package, using the pinned Python environment:

```sh
python scripts/release/kg/query_gates.py --asserted-only --base-url https://rubalkhali.science --root "$PWD" --expectations "$PWD/expected/query_expectations" --paper "$PWD/paper" --output-dir /absolute/path/to/new-query-evidence
python scripts/release/kg/asserted_release_gates.py --base-url https://rubalkhali.science --ph-source /absolute/path/to/new-output/data/processed/ontology/rubalkhali_ph_eq_ph_shared_v1_0_1.ttl --output /absolute/path/to/new-identity-evidence.json
python scripts/release/kg/check_engine_contract.py --endpoint https://rubalkhali.science/sparql --output /absolute/path/to/new-protocol-evidence.json
python scripts/release/kg/verify_downloads.py --base-url https://rubalkhali.science --output-dir /absolute/path/to/new-download-evidence
```

The full download parser requires Raptor's `rapper` on PATH; install the pinned
tool with workflow/bin/bootstrap_raptor.sh. The protocol check uses the exact
six-triple export_fixture.ttl in an explicitly isolated release-test graph.
Its fixture graph must be staged by the release administrator before running
that check; it is outside the public default dataset and released graph.
These checks cover 26 source-derived query results, six asserted-mode and pH
identity checks, 14 protocol checks, and full artifact hashes and RDF parses.
'''


def package(args):
    root, source, output = args.root.resolve(), args.source.resolve(), args.output_dir.resolve()
    require(root.parent == Path('/data/empty-quarter-releases'), 'Explicit isolated release root required')
    require(output == root / 'publication/kg/3.0.0', 'Canonical release output directory required')
    require(not (output / 'manifest.json').exists(), 'Published metadata must never be overwritten')
    inputs = root / 'inputs/scientific'
    module_manifest = read(inputs / 'manifest.json')
    verify_modules(module_manifest, inputs)
    exported = read(args.export_report)
    require(exported.get('passed') is True and exported.get('version', VERSION) == VERSION,
            'Successful asserted export report required')
    rows = exported.get('files', [exported])
    require(len(rows) == 1, 'Exactly one asserted export required')
    asserted = dict(rows[0])
    name = 'rubalkhali-kg-3.0.0-asserted.nq.gz'
    require(asserted.get('name') == name and asserted.get('graph') == GRAPH
            and isinstance(asserted.get('triples'), int) and asserted['triples'] > 0,
            'Versioned nonempty asserted export required')
    path = checked_source(output, name)
    require(digest(path) == asserted['sha256'] and path.stat().st_size == asserted['bytes']
            and len(asserted['uncompressed_sha256']) == 64, 'Asserted artifact integrity failed')
    loader_path = root / 'evidence/asserted_load/report.json'
    adaptation_path = root / 'evidence/asserted_load/import_adaptations.json'
    loader, adaptations = read(loader_path), read(adaptation_path)
    require(loader.get('passed') is True and loader['graph'] == GRAPH
            and loader['triples'] == asserted['triples']
            and loader['input_manifest_sha256'] == digest(inputs / 'manifest.json'),
            'Export must match the independently hash-verified asserted load')
    require(exported.get('input_manifest_sha256') == digest(inputs / 'manifest.json')
            and exported.get('loader_report_sha256') == digest(loader_path),
            'Export report must bind current source and loader bytes')
    require(len(adaptations) == 1 and adaptations[0]['typed_point_whitespace_changes'] == 70
            and adaptations[0]['coordinate_digits_changed'] is False
            and adaptations[0]['original_source_preserved'] is True,
            'Fresh source-preserving seventy-point import proof required')
    sites = next(r for r in module_manifest['records'] if r['file'] == 'rubalkhali_sites.owl')
    require(adaptations[0]['source_sha256'] == sites['sha256'], 'Adapter source hash differs')
    fixture_path = args.export_fixture or root / 'evidence/export_fixture.json'
    fixture = read(fixture_path)
    require(fixture.get('passed') is True and fixture.get('triples') == 6
            and all(fixture.get(key) is True for key in ('binary64_preserved',
                'blank_nodes_unicode_language_preserved', 'wkt_datatype_preserved')),
            'Passing six-triple native export fixture required')
    require(exported.get('export_fixture_sha256') == digest(fixture_path), 'Export fixture hash mismatch')
    replay_path = args.rebuild_report or source.parent / 'rebuilt/rebuild_verification.json'
    clean = root / 'evidence/asserted_source_package'
    import_code = (args.import_code or root / 'release-code').resolve()
    names, transition = source_package(source, clean, module_manifest, replay_path, Path(__file__), import_code)
    files = [archive(clean, names, output / 'rubalkhali-kg-3.0.0-source.tar.gz',
                     'rubalkhali-kg-3.0.0-source')]
    module_names = [r['file'] for r in module_manifest['records']] + ['manifest.json', 'SHA256SUMS', 'catalog-v001.xml']
    files.append(archive(inputs, module_names, output / 'rubalkhali-kg-3.0.0-modules.tar.gz',
                         'rubalkhali-kg-3.0.0-modules'))
    files[0].update(kind='source', description='Frozen scientific inputs, producer code, pinned runtime and current sixteen-module replay proof.')
    files[1].update(kind='modules', description='Sixteen original asserted RDF modules with checksums and offline import catalogue.')
    asserted.update(kind='asserted', url=DOWNLOAD + name, media_type='application/gzip',
                    description='Deduplicated asserted union; no inferred triples.')
    files.append(asserted)
    auxiliaries = []
    public_adapter = clean / 'scripts/release/kg/prepare_wkt_import.py'
    require(digest(public_adapter) == digest(checked_source(import_code, 'prepare_wkt_import.py')),
            'Published adapter differs from frozen release loader code')
    auxiliary_sources = [('input-modules-manifest.json', inputs / 'manifest.json'),
                         ('asserted-loader-report.json', loader_path),
                         ('site-import-adaptations.json', adaptation_path),
                         ('native-export-fixture.json', fixture_path),
                         ('prepare_wkt_import.py', public_adapter),
                         ('source-rebuild-verification.json', replay_path)]
    for public_name, original in auxiliary_sources:
        target = output / public_name
        require(not target.exists(), 'Auxiliary evidence already exists: ' + public_name)
        # Loader adapter reports contain operator paths; publish only scientific/hash fields.
        if public_name == 'site-import-adaptations.json':
            write_json(target, [{k: v for k, v in row.items() if k not in ('source', 'output')} for row in adaptations])
        elif public_name == 'asserted-loader-report.json':
            allowed = ('version', 'started_utc', 'completed_utc', 'graph', 'module_count', 'triples', 'input_manifest_sha256', 'passed')
            write_json(target, {key: loader[key] for key in allowed if key in loader})
        else:
            shutil.copyfile(original, target)
        auxiliaries.append(dict(name=public_name, url=DOWNLOAD + public_name,
                                bytes=target.stat().st_size, sha256=digest(target)))
    timestamp = args.released_at or datetime.now(timezone.utc).isoformat()
    require(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).tzinfo is not None,
            'Release timestamp must have an explicit timezone')
    manifest = dict(version=VERSION, release_mode='asserted-only',
        version_iri='https://rubalkhali.science/kb/v3.0.0/', released_at=timestamp,
        files=files, graphs={'asserted': GRAPH}, counts={'asserted': asserted['triples']},
        default_graph=GRAPH, available_modes=['asserted'], query_time_inference=False,
        graph_semantics={'asserted': 'Deduplicated union of sixteen freshly regenerated scientific and pinned reference modules.'},
        reasoning={'status': 'not-included', 'scope': 'Inference runs separately; no inferred or materialized graph is part of this immutable release.'},
        query_contract='The public dataset contains only the asserted graph. Unreleased graphs and materialized mode are unavailable.',
        coordinate_import={'method': 'fresh-source-preserving-import', 'files': auxiliaries,
            'loader_code_sha256': digest(checked_source(import_code, 'load_asserted.py')),
            'adapter_code_sha256': digest(public_adapter),
            'scope': 'The separately hashed POINT whitespace adapter was applied before the fresh asserted load; no historical post-inference repair is claimed.'},
        validation_url=DOWNLOAD + 'validation.json',
        project_data_licence=None,
        licence_statement='No new licence is granted. Preserve existing third-party terms and annotations.',
        reproducibility_scope='Rebuild all sixteen asserted modules from bundled frozen scientific tables; historical raw-read reconstruction and public sequence access are separate.',
        evidence={'input_manifest_sha256': digest(inputs / 'manifest.json'),
            'private_loader_report_sha256': digest(loader_path), 'export_report_sha256': digest(args.export_report),
            'source_rebuild_report_sha256': digest(replay_path), 'native_export_fixture_sha256': digest(fixture_path),
            'rdf_syntax_validation': 'Full HTTP download, RDF syntax and graph-context validation required before activation.',
            'http_download_validation': 'Not performed by this packaging step.'},
        immutable_release_policy='These three artifacts and this manifest must never change. Publish any later entailed release under a new semantic version.')
    write_json(output / 'manifest.json', manifest)
    with (output / 'SHA256SUMS').open('x') as stream:
        stream.write(''.join(row['sha256'] + '  ' + row['name'] + '\n' for row in files + auxiliaries))
    with (output / 'README.md').open('x') as stream:
        stream.write(source_readme() + '\n## Download validation\n\nVerify the compressed artifacts with `sha256sum -c SHA256SUMS` after downloading the listed files.\n'
                     'The asserted N-Quads contains only <' + GRAPH + '>.\n'
                     'Native serialization hashes identify the released bytes; module hashes identify reproducible source generation.\n')
    with (output / 'service-description.ttl').open('x') as stream:
        stream.write('@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .\n'
                     '@prefix void: <http://rdfs.org/ns/void#> .\n'
                     '<https://rubalkhali.science/kb/v3.0.0/service> a sd:Service ;\n'
                     ' sd:endpoint <https://rubalkhali.science/sparql> ; sd:supportedLanguage sd:SPARQL11Query ;\n'
                     ' sd:defaultDataset <https://rubalkhali.science/kb/v3.0.0/> .\n'
                     '<https://rubalkhali.science/kb/v3.0.0/> a sd:Dataset ; sd:defaultGraph <' + GRAPH + '> ;\n'
                     ' sd:namedGraph [ sd:name <' + GRAPH + '> ; sd:graph <' + GRAPH + '> ] .\n'
                     '<' + GRAPH + '> a sd:Graph ; void:triples ' + str(asserted['triples']) + ' .\n')
    print(json.dumps({'status': 'packaged-asserted-only', 'files': files,
                      'manifest_sha256': digest(output / 'manifest.json'), 'deployment_performed': False}), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--export-report', type=Path, required=True)
    parser.add_argument('--export-fixture', type=Path)
    parser.add_argument('--rebuild-report', type=Path)
    parser.add_argument('--import-code', type=Path,
                        help='Frozen code used by the asserted loader; defaults to ROOT/release-code')
    parser.add_argument('--released-at')
    package(parser.parse_args())


if __name__ == '__main__':
    main()
