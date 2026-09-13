# September 9 asserted-core validation evidence

These are the original September 9, 2026 report bytes cited by the data
paper's dated semantic-validation results. They describe that historical
snapshot, including pH module v1.0.0, not the subsequent KG v3.0.0 release.

- `kg_validation/logs/validate_original_details.log` records the ELK LITE
  check (781,044 axioms, 11 ontology IRIs) and label checks (800,026 triples,
  106,833 labelled subjects).
- `asserted_core_profile_summary.json` summarizes the separate OWL 2 EL
  profile audit. Its `raw_report_gzip_sha256` identifies the complete
  `asserted_core_profile.json.gz` report. The generating Groovy script is
  included as `audit_asserted_core_profile.groovy`.

ELK's operational consistency result is not a full-graph profile or
completeness claim. The raw profile report explicitly excludes imported
declarations and the full taxonomy ABox.

For the deployed asserted-only KG v3.0.0, including pH module v1.0.1, use
`evidence/kg-v3.0.0/manifest.json` and
`evidence/kg-v3.0.0/post-deployment-validation.json`.
