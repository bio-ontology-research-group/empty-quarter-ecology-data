# Preserve site-coordinate precision when importing into Virtuoso 7.2.17

The pinned engine has a short-token `POINT(...)` fast path that stores some points as binary32. This affects 16 of the 70 released site points. The original scientific module remains unchanged. Before loading it, prepare a separate, hashed loader copy:

```sh
python scripts/release/kg/prepare_wkt_import.py \
  --source ontology/rubalkhali_sites.owl --format xml \
  --output rubalkhali_sites.loader.owl --report sites-import.json
```

Use the generated loader copy, not the original file, in the otherwise unchanged `ld_dir` / `rdf_loader_run` import. The report must record exactly 70 whitespace changes. All 71 WKT values remain present: 70 points change only `POINT(` to `POINT (`; the polygon is unchanged. Coordinate digits, stable IRIs and datatypes are preserved. Check the downloaded original module against its release checksum before preparing the loader copy; retain both hashes.

Native N-Quads export removes this whitespace. Therefore the adapter is also required when importing downloaded graph exports, including compressed exports:

```sh
python scripts/release/kg/prepare_wkt_import.py \
  --source rubalkhali-kg-3.0.0-asserted.nq.gz --format nq \
  --output asserted.loader.nq --report asserted-import.json
```

Use the actual downloaded filename. Check its published checksum first. The output is uncompressed; stream it through the normal N-Quads loader. Apply the same adapter to other exported graphs before loading them. An inferred delta with no WKT point values correctly reports zero changes. The adapter does not assign or change graph names. Its source hash covers the exact downloaded compressed bytes; its decoded hash and output hash document the loader derivation.

This is a deliberately narrow adapter for the released uppercase, unescaped, single-line `POINT` literals in RDF/XML, N-Triples and N-Quads, not a general XML or WKT rewriting library. Existing spaced points are unchanged, so adaptation is idempotent. Source, output and report must be distinct; existing outputs and reports are refused. Never replace the published original source modules or exports with loader copies.

The live fixture imported all 70 source points, committed, queried from a separate connection, exported using the native N-Quads serializer, and reloaded. Both adapted paths preserve every source coordinate within the unchanged 1e-10 degree tolerance (maximum observed discrepancy 4.5e-13 degrees). Both unadapted paths fail for the same 16 points (maximum 1.821289e-6 degrees). This verifies numerical precision, not identical RDF lexical serialization or acquisition accuracy. `tests/test_wkt_import_precision.py` also checks the original 71-value module, unchanged polygon, gzip input, unrelated literals, idempotence and protected output/report paths.
