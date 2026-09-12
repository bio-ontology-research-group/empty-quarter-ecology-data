# Prepare release metadata without publishing

`assemble_publication_metadata.py` is fixed to KG 3.0.0. It reads completed
release evidence, hashes the five local download artifacts, and writes a new
metadata directory outside the publication tree. It never changes graphs,
copies downloads into production, restarts a service or publishes a manifest.

Run after `evidence/graph_exports/report.json` and
`materialization-transaction-cap/materialization.json` are complete:

```sh
python3 scripts/release/kg/assemble_publication_metadata.py \
  --root /data/empty-quarter-releases/EXACT-RELEASE-WORKSPACE \
  --reference-attribution /path/to/candidate_module_download_audit.json \
  --export-fixture-report /path/to/export-fixture-report.json \
  --materialization-dir /data/empty-quarter-releases/EXACT-RELEASE-WORKSPACE/materialization-transaction-cap \
  --repair-certificate /path/to/wkt-closure-preservation.json \
  --repair-plan /path/to/wkt-repair-plan.json \
  --source-audit /path/to/geometry_rule_source_audit.json \
  --released-at 2026-09-10T00:00:00Z \
  --output-dir /data/empty-quarter-releases/EXACT-RELEASE-WORKSPACE/evidence/prepared-publication-metadata
```

The output directory must not exist. `--released-at` is explicit release
metadata, not an automatically inferred current time. Inputs are the five
canonical files in `publication/kg/3.0.0/`, the export report, completed
materialization report, both exact rule files, monitored contradiction
diagnostics, and the independently verified reference-annotation audit.
The native export fixture report is also required; its status and hash are
recorded with its exact six-triple scope, including binary64 tolerance
1e-17 and normalization of WKT POINT whitespace for comparison.
RDFLib is the only nonstandard Python dependency.

The separate coordinate-repair certificate, exact plan and source-isolation
audit are mandatory.
Their byte hashes must match the export report, and the certificate must bind
the unchanged original materialization report and exact rule program. The
assembler copies them as `wkt-closure-preservation.json` and
`wkt-repair-plan.json` and records their versioned URLs and hashes under
`coordinate_import`. The historical materialization report remains explicitly
pre-repair; the independent certificate carries its closure result through
the bounded annotation-only transition. Fresh rebuilds apply the import
adapter before materialization and need no historical repair.

Eight auxiliary downloads accompany the five primary artifacts: the certificate,
plan, source audit, and five verifier/operator sources (`certify_wkt_repair.py`,
`audit_geometry_rule_reachability.py`, `assemble_publication_metadata.py`,
`finalize_graphs.py`, and `kg_admin.py`). Their URLs and byte hashes are bound
under `coordinate_import`; the audit and checker hashes must also match the
certificate. Full HTTP reads verify all eight before activation. To reuse the
verification code, place these five files in the extracted source archive's
`scripts/release/kg/` directory beside its pinned `materialize.py`.

The source archive is the verified r8 payload, served under its canonical
filename; its SHA-256 is
`320ecfe3e26dce4b378ef233e78f9256829b08e9343eda300fd73533a8afeb26`.
The modules archive SHA-256 is
`7dcbeb447831e9af25973f9a4fac8376ef7d1564abc85e0118edd87baa39f974`.
The three N-Quads hashes and cardinalities come from the final export report.
The source package includes `prepare_wkt_import.py` and `WKT_IMPORT.md`:
original site XML and native N-Quads exports require a separately hashed
loader copy to avoid Virtuoso's short-token POINT binary32 path. Original
download bytes and 16-module hashes remain unchanged. The complete 70-site
fixture preserves coordinates within 1e-10 degrees through adapted import
and native-export reload; the unadapted paths fail for 16 sites. This import
requirement is separate from the historical six-triple serializer fixture.
The corrected asserted count must be 45,706,821, not the pre-normalization
45,706,822. Every artifact is independently hashed again during assembly.
If a later validated materializer requires a replacement source archive,
update the explicitly pinned source archive hash/size before assembling;
do not silently accept different source bytes under this verified record.
Use `--materialization-dir` to select a different completed evidence directory
immediately inside the same release workspace. The default is
`materialization-batched`; its report must match the current generator source.
For this release, the explicit `materialization-transaction-cap` selection
above is required after that recovery run completes; earlier reports were
interrupted or failed. The actual
materializer command also requires `--batch-size 500000`; revision 6's source
example and the generated final release README provide that explicit option.
The driver's default remains 200,000, so omitting the option would not
reproduce this release's batch setting.

The proven engine transaction after-image limit is 250,000,000 bytes:
`[Parameters] TransactionAfterImageLimit=250000000`, with matching
`sys_stat('txn_after_image_limit')` readback. The previous 50,000,000-byte
limit caused SR325 in `subproperty_fact` batch 8. Preserve that failed
`materialization-guarded` report; it is not evidence of completed closure.
The recovery checkpoint retained 45,706,821 asserted and 87,678,125 inferred
triples, with unchanged rule source and 500,000-triple batches. The next
completed report must be selected explicitly after its guarded fixed-point
check succeeds; runtime configuration evidence alone is insufficient.

Outputs are `manifest.json`, `SHA256SUMS`, `README.md`,
`service-description.ttl`, `THIRD_PARTY_ATTRIBUTIONS.json`, `rules.rq`, and
`execution_rules.rq`. The README includes download verification, source
rebuild instructions, graph semantics and exact reproducibility limits.
`inference_runtime.json` is copied separately; the manifest includes the
actual report's Python/RDFLib versions plus observed transitive package and
pinned engine information, with a distinct source-generation runtime.
The service description declares asserted default data and three explicit
named graphs. It introduces no automatic inference or new licence.
When the materializer partitions subclass typing by active classes, each
pass is checked against the logical rule inventory plus that pass's own
hash-verified class inventory and execution queries. Active classes can
legitimately change between passes. Exact `execution_partitions/` JSON/query
files are copied into the prepared metadata and their hashes recorded.

The manifest records RDF syntax-validation status exactly as supplied by the
export report, including pending status. HTTP validation is not inferred.
It includes the exact three graph IRIs and links separate acceptance evidence
at `/downloads/kg/3.0.0/validation.json`. That acceptance document can record
this manifest's hash and gate-file hashes without a circular dependency.
The administrator must pass actual download/hash/syntax and query gates
before promoting these prepared files. Immutable release paths must not be
silently overwritten with different content after publication.
Native N-Quads hashes identify the released engine serialization. They do not
promise identical blank-node identifiers, ordering or literal spelling on a
fresh database import; the README distinguishes this from exact replay of
the original 16 module hashes and semantic graph/finite-closure reproduction.

Focused synthetic acceptance tests:

```sh
python3 -m unittest discover -s tests -p test_publication_metadata.py
```

They cover all five artifacts, correct graph/default semantics, missing or
failed closure, stale root cardinality, artifact/rule tampering, missing
diagnostics and prohibited publication-directory/overwrite requests.
