-- Public protocol selection is handled by the tested application proxy.
-- SH_GRAPH_URI overrides explicit FROM when its selected graph is empty;
-- it must not be used to implement an overridable SPARQL default dataset.
DELETE FROM DB.DBA.SYS_SPARQL_HOST WHERE SH_HOST = '*';
CHECKPOINT;
