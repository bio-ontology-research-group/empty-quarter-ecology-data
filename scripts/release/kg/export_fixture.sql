DB.DBA.TTLP (file_to_string_output ('/release-inputs/export_fixture.ttl'), '', 'urn:eq:release-test:export', 0);
DB.DBA.EQ_EXPORT_GRAPH ('urn:eq:release-test:export', '/release-exports/export-fixture-', 250000000);
