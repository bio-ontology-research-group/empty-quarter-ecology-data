-- Frozen asserted snapshot is the fallback dataset. Explicit query/protocol
-- datasets remain available and are checked independently before deployment.
INSERT REPLACING DB.DBA.SYS_SPARQL_HOST
  (SH_HOST, SH_GRAPH_URI, SH_USER_URI, SH_BASE_URI, SH_DEFINES)
  VALUES ('*', 'https://rubalkhali.science/graph/asserted/3.0.0', 'SPARQL', NULL, NULL);
CHECKPOINT;
