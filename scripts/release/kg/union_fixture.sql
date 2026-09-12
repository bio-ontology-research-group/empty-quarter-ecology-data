-- Preconditions checked by caller: export fixture has 6 triples; both new
-- urn:eq:release-test:union-log3:* graphs are absent/empty.
-- Sources contain blank nodes, Unicode, language, double and WKT literals.
SPARQL DEFINE sql:log-enable 3 COPY GRAPH <urn:eq:release-test:export> TO GRAPH <urn:eq:release-test:union-log3:inferred>;
SPARQL INSERT DATA { GRAPH <urn:eq:release-test:union-log3:inferred> { <urn:eq:release-test:union-log3:added> <urn:eq:release-test:union-log3:predicate> "additional union fixture"@en } };
SPARQL DEFINE sql:log-enable 3 COPY GRAPH <urn:eq:release-test:export> TO GRAPH <urn:eq:release-test:union-log3:materialized>;
SPARQL DEFINE sql:log-enable 3 ADD GRAPH <urn:eq:release-test:union-log3:inferred> TO GRAPH <urn:eq:release-test:union-log3:materialized>;
SPARQL DEFINE sql:log-enable 3 ADD GRAPH <urn:eq:release-test:union-log3:inferred> TO GRAPH <urn:eq:release-test:union-log3:materialized>;
CHECKPOINT;
