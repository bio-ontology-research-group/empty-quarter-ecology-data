# KG 3.0.0 deployment acceptance

This is the operator sequence, not a record of successful deployment. The
scientific source archive and `PUBLICATION_METADATA.md` describe reconstruction
and metadata assembly. Preserve failed attempts and use new evidence directories
for retries. Production remains unchanged until the activation gate passes.

1. Rebuild the 16 manifested RDF modules from the frozen scientific source
   tables in a fresh workspace. Compare every module hash with the independently
   replayed build. Preserve the original modules. Before loading, derive the
   separately hashed site loader copy with `prepare_wkt_import.py` as described
   in `WKT_IMPORT.md`; require exactly 70 point-whitespace adaptations and an
   unchanged polygon. `load_asserted.py` applies this automatically. Load the
   resulting asserted union into the isolated release database. Native N-Quads
   exports also require this adapter when reloaded into the pinned engine.
2. Run the rule fixtures on the exact engine image and configuration. Run the
   finite materializer to a complete zero-addition pass, followed by its scoped
   contradiction diagnostics and `verify_release_witnesses.py`. A running,
   interrupted, failed or partially evaluated report cannot certify closure.
   For this candidate's historical 16-site import repair, preserve the completed
   original report. Run `certify_wkt_repair.py --preflight` against the frozen
   graph, source-bound staging points and exact repair plan. Define the canonical
   named repair procedure only after confirming its name is unused; check its
   compilation before issuing the separate canonical call. Require the explicit
   commit marker and the independently tested rollback safeguards. Then produce
   the separate immutable closure-preservation certificate. Never edit the
   original materialization report to conceal the input transition.
3. Run `finalize_graphs.py` with the explicit release root, candidate container,
   loopback endpoint, completed materialization directory, `--repair-certificate`
   and `--repair-plan`. It binds the actual report, certificate and plan hashes
   before any export or union write. It creates only
   the initially empty materialized graph, using logged row-autocommit COPY/ADD.
   It checks cardinality and both source inclusions before exporting the three
   graphs. Partial targets and export evidence are retained on failure; do not
   clear them or retry blindly.
4. Assemble and inspect metadata outside the publication directory, then stage
   the five artifacts and listed metadata files into the candidate-only website.
   Check the version IRI's manifest and Turtle redirects, their final HTTP 200
   targets, MIME types, three graph IRIs and matching immutable version.
5. Run all candidate query and browser gates. `query_gates.py` requires 31 exact
   result checks, including IDs, multiplicity, values and declared numeric
   tolerances. All six named-taxonomy variants and the top-20 API must also
   verify numeric ordering explicitly; the browser must do the same for its
   taxonomy example. `mode_gates.py` requires nine asserted/materialized and explicit
   dataset-override checks. The browser suite must exercise all nine examples,
   the six source-derived inference witnesses and all five download links.
6. Run `check_engine_contract.py` against the candidate `/sparql` endpoint.
   Its 14 checks cover dataset semantics, read-only access and all four
   advertised graph formats. Every successful response must be complete;
   Turtle, N-Triples, RDF/XML and JSON-LD must preserve the six-triple source
   fixture, including binary64 and GeoSPARQL literal datatypes.
   SELECT JSON and XML must also preserve the six actual bound RDF terms;
   a correct `DATATYPE()` result alone cannot establish serialization fidelity.
7. Run `verify_downloads.py` against the candidate origin. Download every byte
   of all five artifacts; check compressed hashes and sizes, and fully parse
   each N-Quads export with Raptor. Check its graph contexts, triple count and
   uncompressed hash. Browser range requests alone do not satisfy this gate.
   Also fully download and hash the eight auxiliary certificate, plan, audit
   and verifier files listed under `coordinate_import`. Bind the audit and
   checker bytes to the independently validated repair certificate.
8. Pass explicit `--query`, `--mode`, `--download`, `--browser`, `--witness`,
   `--materialization`, `--protocol` and `--repair` report paths, plus `--manifest`, to
   `write_validation_evidence.py`. It invokes the activation validator before
   writing public, field-whitelisted `validation.json`. Retain the exact fixture
   graphs through the post-cutover protocol check; they are outside every
   released graph and the asserted default dataset.
9. Pass those same eight reports to `cutover.py activate`. It verifies their
   content, live graph counts, the HTTP manifest, candidate routing, and the
   exact old production container/configuration. It snapshots the old nginx
   configuration and changes its contents without replacing the bind-mounted
   inode. Configuration-test or reload failure triggers rollback.
10. Repeat the query, mode, protocol, browser, metadata and full-download gates
    against `https://rubalkhali.science`, writing new post-cutover reports.
    Roll back with `cutover.py rollback` if a required public gate fails. Do not
    describe the immutable candidate validation report as post-cutover proof.
    After those checks pass, preserve their evidence and remove only the
    enumerated release-owned fixture graphs. Verify the fixture graphs are
    empty and the three released graph counts are unchanged.

Keep the old production database and containers available for rollback. Never
reuse a published version path for changed bytes. A subsequent release requires
new versioned graphs, downloads and evidence. No step grants a new data licence
or claims that missing historical laboratory records have been reconstructed.
