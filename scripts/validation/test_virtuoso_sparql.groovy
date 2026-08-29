import groovy.json.JsonSlurper
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * Spot-check a curated set of competency queries against the live Virtuoso
 * endpoint. The queries are sourced from data/processed/ontology/SPARQL.md
 * if present; if that file is stale or missing we fall back to inline
 * minimal queries so the deployment gate still has signal.
 *
 * Notes:
 *  - Earlier versions reloaded data via `isql-v load_data.sql` before
 *    querying. We removed that — it's slow (~2 min on the full taxonomy)
 *    and broken (the .execute().waitFor() pattern deadlocks when stdout
 *    fills the pipe buffer). Validation should observe the live state,
 *    not mutate it.
 *  - SPARQL.md is checked into the repo and may reference older property
 *    IRIs (e.g. RAK_2000021 for absolute abundance) that have since been
 *    re-numbered. Such queries will return 0 results today; that's logged
 *    as a soft warning, not a hard failure. The hard expectations live in
 *    the inline `BASELINE_CHECKS` below.
 */

def sparqlEndpoint = "http://localhost:8895/sparql"
def sparqlMd = new File("data/processed/ontology/SPARQL.md")

// Inline baseline checks: each entry is [name, query, validator-closure].
// The validator returns true on pass. Any false → overall FAIL.
def BASELINE_CHECKS = [
    [
        name: "70 sampling sites",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a rak:RAK_0000002 }
        """,
        check: { json -> (json.results.bindings[0].n.value as int) == 70 }
    ],
    [
        name: "Site labels include 'Site 1'",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?label WHERE { ?s a rak:RAK_0000002 ; rdfs:label ?label . FILTER(?label = "Site 1") }
        """,
        check: { json -> json.results.bindings.size() == 1 }
    ],
    [
        name: "Desert biome assignment present",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT (COUNT(*) AS ?n) WHERE {
              ?site a rak:RAK_0000002 .
              ?site a [ owl:onProperty rak:RAK_2000001 ; owl:someValuesFrom ?b ] .
              ?b rdfs:label ?bl .
              FILTER(CONTAINS(?bl, "desert"))
            }
        """,
        check: { json -> (json.results.bindings[0].n.value as int) >= 60 }
    ],
    [
        name: "XRF measurement values exist",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            PREFIX sio: <http://semanticscience.org/resource/>
            SELECT (COUNT(*) AS ?n) WHERE {
              ?p a rak:RAK_0000025 ; sio:SIO_000229 ?v .
            }
        """,
        check: { json -> (json.results.bindings[0].n.value as int) >= 10000 }
    ],
    [
        name: "Absolute abundance count (RAK_2000026) ≥ 1,000,000",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            SELECT (COUNT(*) AS ?n) WHERE {
              GRAPH <https://rubalkhali.science/kb/> {
                ?v a rak:RAK_0000076 ; rak:RAK_2000026 ?c
              }
            }
        """,
        check: { json -> (json.results.bindings[0].n.value as int) >= 1_000_000 }
    ],
    [
        name: "No RAK_0000076 carries colliding RAK_2000021 (post-rename invariant)",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            SELECT (COUNT(*) AS ?n) WHERE {
              GRAPH <https://rubalkhali.science/kb/> {
                ?v a rak:RAK_0000076 ; rak:RAK_2000021 ?c
              }
            }
        """,
        check: { json -> (json.results.bindings[0].n.value as int) == 0 }
    ],
    [
        name: "Monthly weather processes still distinct from abundance",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            SELECT (COUNT(*) AS ?n) WHERE {
              ?p a rak:RAK_0000035 ; rak:RAK_2000021 ?t .
            }
        """,
        check: { json -> (json.results.bindings[0].n.value as int) >= 1000 }
    ],
    [
        name: "Sampling sites carry geospatial coords",
        query: """
            PREFIX rak: <https://rubalkhali.science/kb/>
            PREFIX geo: <http://www.opengis.net/ont/geosparql#>
            SELECT (COUNT(*) AS ?n) WHERE { ?s a rak:RAK_0000002 ; geo:asWKT ?w }
        """,
        check: { json -> (json.results.bindings[0].n.value as int) == 70 }
    ]
]

def runQuery = { String query ->
    def encoded = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
    def url = "${sparqlEndpoint}?query=${encoded}&format=json"
    def conn = new URL(url).openConnection()
    conn.setConnectTimeout(10_000)
    conn.setReadTimeout(60_000)
    if (conn.responseCode != 200) {
        throw new RuntimeException("HTTP ${conn.responseCode}")
    }
    return new JsonSlurper().parse(conn.inputStream)
}

println "=== Baseline competency checks against live Virtuoso ==="
int failures = 0
BASELINE_CHECKS.each { c ->
    print "  ${c.name}... "
    try {
        def json = runQuery(c.query)
        if (c.check(json)) {
            println "OK"
        } else {
            println "FAIL: " + groovy.json.JsonOutput.toJson(json.results.bindings).take(200)
            failures++
        }
    } catch (Exception e) {
        println "FAIL: ${e.message}"
        failures++
    }
}

// Soft pass over SPARQL.md if available — log results, no hard fail.
if (sparqlMd.exists()) {
    println "\n=== Soft sweep: queries from SPARQL.md ==="
    def content = sparqlMd.text
    def matcher = (content =~ /(?s)```sparql(.*?)```/)
    def blocks = []
    while (matcher.find()) { blocks << matcher.group(1).trim() }
    def prefixes = blocks ? blocks[0] : ""
    def queries = blocks.size() > 1 ? blocks.drop(1) : []

    queries.eachWithIndex { qb, idx ->
        def full = qb.trim().toLowerCase().startsWith("prefix") ? qb : prefixes + "\n" + qb
        try {
            def json = runQuery(full)
            def n = json.results.bindings.size()
            println "  Q${idx + 1}: ${n} rows"
        } catch (Exception e) {
            println "  Q${idx + 1}: ERROR ${e.message}"
        }
    }
}

if (failures > 0) {
    println "\n${failures} BASELINE CHECK${failures == 1 ? '' : 'S'} FAILED."
    System.exit(1)
}
println "\nAll baseline competency checks PASSED."
