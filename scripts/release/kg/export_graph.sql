-- Graph-specific, datatype/language/blank-node preserving N-Quads export.
-- Uses Virtuoso's native http_nquad serializer, as in the image-provided
-- dump_nquads procedure. Unlike that routine, serialization errors abort.
-- Each invocation requires an unused output prefix, checked by its caller.
CREATE PROCEDURE DB.DBA.EQ_EXPORT_GRAPH
  (IN graph_iri VARCHAR, IN output_prefix VARCHAR, IN chunk_bytes INTEGER := 250000000)
{
  DECLARE buffer, serializer ANY;
  DECLARE part, records INTEGER;
  DECLARE filename VARCHAR;
  part := 1;
  records := 0;
  serializer := vector (0, 0, 0);
  buffer := string_output (10000000);
  SET ISOLATION = 'committed';
  FOR (SELECT * FROM (SPARQL DEFINE input:storage ""
    SELECT ?s ?p ?o ?g WHERE {
      GRAPH ?g { ?s ?p ?o }
      FILTER (?g = iri(?:graph_iri))
    }) AS exported OPTION (LOOP)) DO
  {
    http_nquad (serializer, "s", "p", "o", "g", buffer);
    records := records + 1;
    IF (length (buffer) >= chunk_bytes)
    {
      filename := sprintf ('%s%06d.nq', output_prefix, part);
      string_to_file (filename, buffer, -2);
      part := part + 1;
      serializer := vector (0, 0, 0);
      buffer := string_output (10000000);
    }
  }
  IF (length (buffer) > 0)
  {
    filename := sprintf ('%s%06d.nq', output_prefix, part);
    string_to_file (filename, buffer, -2);
  }
  RESULT_NAMES (records);
  RESULT (records);
}
;
