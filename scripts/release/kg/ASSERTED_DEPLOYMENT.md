# Asserted-only acceptance sequence

The v3.0.0 deployment uses a separate fresh serving database; ongoing inference
is isolated. `DEPLOYMENT_GATES.md` describes the alternative historical
materialized candidate and is not the asserted-release activation contract.

1. Rebuild all 16 source modules from the frozen scientific archive and compare
   hashes. Preserve source bytes and apply the coordinate-preserving import
   adapter only to separate loader copies.
2. Load a fresh asserted database, verify 45,706,977 triples and the native
   six-triple export fixture, then export and package the three immutable files
   with `package_asserted_release.py`.
3. Run `query_gates.py --asserted-only`, `check_engine_contract.py`,
   `asserted_release_gates.py`, the website's `browser_kg_candidate.py
   --asserted-only --check-all-examples --check-downloads`, and
   `verify_downloads.py`. Require complete results; preserve failed evidence.
   Raptor must support N-Quads input and output, not only Turtle.
4. Run `asserted_cutover.py activate --gates-dir <candidate-evidence>` using
   Python 3.11. The script checks the exact candidate/report/production identities
   and requires all five suites before changing the reversible nginx entry point.
5. Repeat every gate against `https://rubalkhali.science`, in a separate public
   evidence directory. A required failure triggers `asserted_cutover.py rollback`.
6. Run `publish_asserted_public_validation.py --root <release-root>
   --gates-dir <public-evidence>`. It repeats the substantive report validation
   and live manifest/count checks, then exclusively creates the sanitized
   `post-deployment-validation.json`.

Preserve the old stack, source manifests, failed attempts and both candidate
and public evidence. Never overwrite released artifacts or relabel unfinished
inference as completed entailment. `run_asserted_checks.py` records the exact
paths and detached execution commands used on onto; these paths are not a
portable installation recipe.
