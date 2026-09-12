# KG release tooling

The deployed **v3.0.0 is asserted-only**. Start with the
[release guide](../../../docs/KG_V3_0_0_RELEASE.md) and
[asserted acceptance sequence](ASSERTED_DEPLOYMENT.md).
The immutable source archive supplies the standalone scientific replay.
The operator drivers retain exact historical deployment paths and require
explicit target preparation before reuse. The remaining sections document the
separate reasoning implementation and earlier materialization investigations.

## Release-local finite entailment

`materialize.py` computes the least fixed point of the emitted positive rules
on an explicitly loaded RDF dataset. It is a selected RDF/OWL rule program,
not a complete OWL-Horst, OWL 2 RL, EL or DL reasoner.

## Scope

The rule list implements:

- Equivalent-class/property expansion, transitive subclass/subproperty closure,
  instance typing, subproperty facts, domain and resource-valued range.
- Inverse and symmetric properties, and repeated transitive-property expansion
  including self-edges entailed by cycles.
- Every nonempty finite chain of named properties or anonymous inverses of a
  named property found in the loaded schema. Inverse operands reverse the
  corresponding edge; they do not introduce a new RDF predicate.
  The project TBox contains four chains of length two or three, including the
  measurement-value/output/target chain. Imported RO axioms also use inverse
  operands. Malformed lists and anonymous operands other than exactly one
  `owl:inverseOf` named property fail the schema audit.
- `hasValue` fact introduction and classification; `someValuesFrom`
  classification when an existing edge and typed filler provide its witness;
  `allValuesFrom` typing of existing resource fillers; nonempty intersection
  introduction/elimination; union introduction and resource enumeration typing.

No existential filler is invented. This instance-level program does not replace
the separate class-subsumption entailment test for existential measurement
patterns. It does not compute equality, cardinality, keys, datatype value-space
entailments, facets, negative-property consequences or complete consistency.
The machine-readable schema audit counts these omitted constructs and records
all `owl:imports` IRIs. Imports are used only when explicitly present in the
loaded, manifested asserted union; there is no implicit network retrieval.

The fixed-point claim refers to the emitted rule program and its input schema.
An operational pass limit or a query/SQL error produces failure, never a partial
success. A complete final pass must add zero triples for every rule. Explicit
disjoint-type, complement-type, `owl:Nothing` and PCR/extraction-role clash checks
run after convergence; passing these checks has only that diagnostic scope.

## Graphs and staging

The administrator loads a fresh, deduplicated asserted union, and creates no
inferred data in advance. Materialization requires a nonempty asserted graph and
an empty, distinct inferred graph. Its insertion guards exclude every triple
already in either graph, making inferred data an exclusive delta. Asserted data
are never updated. The administrator also disables query-time inference and
keeps anonymous SPARQL updates disabled. The runner accepts loopback endpoints
only and requires an explicit `--staging-only` flag.

The source/module hashes and import coverage belong in the release input
manifest. The final assertion hash and the delta hash belong in the export
manifest. The runner records graph counts, schema inventory, exact rule-program
hash, implementation/runtime versions, per-rule additions, convergence and
diagnostic results. A count guard detects changes in asserted cardinality;
the release must remain write-frozen during the run, because a count is not a
content hash. `rules.rq` and `materialization.json` make the actual schedule
replayable. `schema_audit.json` fails rather than accepting a row-truncated
schema response.
Every HTTP read rejects non-200 status and `X-SQL-State`, `X-SQL-Message` or
`X-SPARQL-MaxRows` headers before parsing its body. Virtuoso can otherwise
return apparently valid JSON, including aggregate counts, for partial
anytime-query results; such responses can never certify zero additions.

Each SQL update selects a bounded number of distinct conclusion triples, excluding
triples already present. Each rule repeats until a batch adds zero triples;
the full schedule repeats until every rule adds zero. `rules.rq` records the
unchanged logical rules and `execution_rules.rq` records the bounded update
queries, with separate hashes and per-batch counts. Batching changes the
execution schedule, not its least fixed point. Tests compare three-triple
batches with the unbounded reference closure, including duplicate witnesses.
The default is 200,000 triples; the release continuation uses the existing
`--batch-size 500000` option to reduce repeated scans. Each report records its
actual batch size and execution-query hash.
The instance-subclass rule is partitioned by currently instantiated named
classes so the engine can use its predicate/object index; one additional
partition covers anonymous classes. The exhaustive class inventory is
recomputed for every full pass with a count-versus-result truncation guard.
Its existence semijoin checks whether a schema class has an instance without
multiplying rows by the number of instances; the selected class set is unchanged.
New types introduced later in a pass are handled in subsequent passes. Exact
partition queries, class inventories and hashes are saved under
`execution_partitions/`. Tests compare partitioned closure with the unbounded
reference, including anonymous classes and types activated by later rules.

An interrupted failed run can be resumed into a new report directory with
`--resume-report` and `--resume-generator`, identifying the preserved failed
report and its exact generator source. The runner verifies their source hash,
emitted-rule hash, graph IRIs, asserted count and failed status, and rejects any
asserted/delta overlap. It preserves the existing positive delta, starts a new
complete rule pass, and requires the same zero-addition convergence criterion.
This requires the administrator to preserve the frozen asserted input and
exclusive ownership of inferred writes; counts alone cannot prove content
identity. The original failure report remains unchanged.
An operator-interrupted controller requires a separate preserved running-report
hash and explicit evidence that the controller was stopped, its current SQL
child completed, and no further update can overlap the replacement controller.
This interruption is recorded separately from a rule or resource failure.

The staging engine must permit the update sizes required by the rule program.
This release uses `[SPARQL] MaxConstructTriples=100000000` with a finite
`MaxMemInUse=17179869184` (16 GiB construct-memory limit) inside a 128 GiB
container. The query row limit remains separate. Resource-limit failures are
recorded as failures and never interpreted as convergence. The engine's
`sys_stat('sparql_construct_max_triples')` and
`sys_stat('sparql_max_mem_in_use')` values are checked after restart: on the
pinned engine, configuring a zero triple limit fell back to `ResultSetMaxRows`,
and a positive 100,000,000 setting was capped at 2,097,150. Both the initial
200,000-triple and continuation 500,000-triple update batches stay below this
measured cap.
The release continuation also uses `[Parameters]
TransactionAfterImageLimit=250000000`, verified through
`sys_stat('txn_after_image_limit')`. The default 50,000,000-byte limit aborted
a 500,000-triple property-propagation batch with `SR325`; its transaction
rolled back and the failed report was preserved. The bounded 250 MB setting
retains transaction logging, the batch size and the rule program. Configuration
and runtime readbacks are recorded in `transaction_image_configuration.json`
and `transaction_image_runtime.log`. OpenLink documents this limit and its
[bounded configuration adjustment](https://docs.openlinksw.com/virtuoso/virtuosotipsandtrickssparulupdatestrl/).
The candidate records `[Flags] hash_join_enable=1`. A trial of value2 produced
unexpected additional schema triples in the isolated entailment fixture and
was reverted before release inference resumed. The retained fixtures verify
the selected engine and optimizer configuration together.

The SQL command file contains an administrator-owned argv array for a wrapper
that reads SQL from stdin. The provided staging example obtains the DBA secret
inside the isolated container; the secret is never read or printed by this
program. Use a different container/command file for another release. Neither
the runner nor fixture driver modifies the production database.

## Execute

On the staging host, with the scripts and an RDFLib-enabled Python runtime:

```sh
python3 verify_staging_fixture.py \
  --endpoint http://127.0.0.1:18896/sparql \
  --sql-command-file staging_sql_command.json \
  --graph-prefix urn:eq:release-test:RUN-IDENTIFIER \
  --output-dir /path/to/new/fixture-report

python3 materialize.py \
  --endpoint http://127.0.0.1:18896/sparql \
  --sql-command-file staging_sql_command.json \
  --asserted-graph https://rubalkhali.science/graph/asserted/3.0.0 \
  --inferred-graph https://rubalkhali.science/graph/inferred/3.0.0 \
  --batch-size 500000 \
  --output-dir /path/to/new/materialization-report \
  --staging-only
```

The fixture driver is restricted to `urn:eq:release-test:` graphs and requires
both targets empty. It uses the same emitted rules as the release run. Its
positive witnesses include both project chain lengths, a 40-edge hierarchy,
intersection and restriction classification, a transitive cycle, and the
negative ancestor of a PCR-control role. Negative witnesses check extraction
and positive roles, fabricated existential fillers and unclaimed equality.
The local tests additionally force failure at an insufficient three-pass cap:

```sh
python -m pytest -q tests/test_release_entailment.py
```

A fresh release must pass these fixtures on its actual Virtuoso image and must
independently verify real graph witnesses and canonical control identities.
Synthetic witness success alone does not prove that all release modules were
loaded correctly. Run `verify_release_witnesses.py` with `--endpoint`,
`--asserted-graph`, `--inferred-graph`, `--controls` (the fresh controls Turtle)
and a new `--output` JSON path. This read-only check compares the entire asserted
control-role inventory with its source, checks every canonical PCR role's
negative ancestry and absence of positive/extraction roles, checks both
measurement chains on nonempty real data, and verifies delta disjointness.
The final public materialized graph is a deduplicated union
of asserted and inferred graphs created by the release administrator; serving
that union needs no implicit query-time ruleset.

Specification basis: [W3C OWL 2 RL/RDF rules](https://www.w3.org/TR/owl2-profiles/#Reasoning_in_OWL_2_RL_and_RDF_Graphs).
The named subset and exclusions above govern this implementation, rather than
a claim to implement every rule in that specification.

## Geometry precision repair certificate

The pinned engine stores 16 original point spellings at reduced precision.
`prepare_wkt_import.py` preserves the source coordinate digits and inserts a
space after `POINT` to select the verified binary64 import path. Apply that
adapter to both original RDF/XML and exported N-Quads before loading them.
The source geometry inventory contains 70 points and one polygon; the existing
coordinate comparison tolerance is `1e-10`.

`certify_wkt_repair.py` implements a separate, read-only certificate for the
exact 16-point repair after finite-rule materialization completes. Its proof
is restricted to the recorded 27-rule program and generator hashes. The
preflight requires `geo:asWKT` to have only its annotation-property declaration,
no incoming schema references, no inferred `asWKT` statements, and no old
geometry objects anywhere in the inferred delta. It checks the completed
all-zero rule schedule and diagnostics, the hash-verified 16-module source
audit, all 71 geometry subjects, and the 70 source-derived stored replacement
terms in the isolated staging graph. These conditions establish that the
changed annotation facts participate in no grounding of a rule body.

The repair administrator obtains SQL from `canonical_repair_sql(plan)`. The
procedure binds existing stored terms from the validated staging graph, checks all
16 old lexical strings and datatypes, checks the 16 inserted terms, and emits
`WKT_REPAIR_COMMITTED_16` after successful commit. Its release-specific procedure
uses logged transactions and a rollback/resignal exit handler. The isolated
execution fixture must demonstrate successful precision restoration and
rollback after a forced failure before scientific execution. The error-handling
semantics are documented by OpenLink for
[procedure transactions](https://docs.openlinksw.com/virtuoso/procedures_transactions/),
[dynamic execution](https://docs.openlinksw.com/virtuoso/fn_exec/), and
[condition handlers](https://docs.openlinksw.com/virtuoso/handlingplcondit/).
The administrator first verifies that the release-specific procedure name is
absent, then executes and checks the definition file. Only a successful
definition permits the separate invocation from `canonical_repair_call()`.
This separation prevents a definition failure from falling through to a call.

Run the checker with `--preflight` before repair, then with
`--repair-execution execution.json` after the administrator's exclusive write
window. Both calls require `--endpoint`, `--materialization-dir`,
`--source-audit`, `--repair-plan`, `--source-sites`, and a new `--output` path.
The execution record contains status `passed`, `exclusive_write_window: true`,
both graph IRIs, `procedure_absent_before_definition: true`,
`definition_checked_before_call: true`, the repair-plan and original
materialization-report hashes, and hash-bound `preflight_file`, `sql_file`,
`sql_log_file`, `call_file`, and `call_log_file` references.
Each file reference has the corresponding `_sha256` field.

The final certificate verifies the source coordinates, unchanged polygon,
exactly 16 changes, unchanged staged terms, and unchanged graph counts under
the exclusive repair execution. It preserves the original materialization
report as evidence for the pre-repair input and certifies closure preservation
through this specific repair. Its public fields contain scientific facts and
hashes; operator paths and command arguments remain in private execution
evidence. Export and cutover gates call `validate_certificate` with the actual
original-report hash, repair-plan hash, and graph counts. The publication
manifest subsequently binds the certificate file hash and the final exports.
