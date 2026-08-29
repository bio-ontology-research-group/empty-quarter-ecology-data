import groovy.json.JsonSlurper
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

def sparqlEndpoint = "http://localhost:8895/sparql"

def runSparqlQuery(endpoint, query) {
    def encodedQuery = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
    def url = "${endpoint}?query=${encodedQuery}&format=json"
    def connection = new URL(url).openConnection()
    if (connection.responseCode != 200) throw new RuntimeException("HTTP ${connection.responseCode}")
    return new JsonSlurper().parse(connection.inputStream)
}

def queryStr = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX rak: <https://rubalkhali.science/kb/>

SELECT (COUNT(DISTINCT ?value) AS ?distinctValues) (COUNT(DISTINCT ?quality) AS ?distinctQualities)
WHERE {
  ?fastq rdfs:label "FASTQ dataset for ERR16062320" .
  ?quality sio:SIO_000011 ?fastq .
  ?quality a rak:RAK_0000072 .
  # SIO-canonical: value sio:SIO_000215 quality (value is subject).
  ?value sio:SIO_000215 ?quality .
}
"""

println "Executing SPARQL validation against Virtuoso..."
try {
    def json = runSparqlQuery(sparqlEndpoint, queryStr)
    def vCount = json.results.bindings[0].distinctValues.value.toInteger()
    def qCount = json.results.bindings[0].distinctQualities.value.toInteger()
    println "Distinct Values: ${vCount}"
    println "Distinct Qualities: ${qCount}"
    
    def expected = 2457 
    if (total == expected) {
        println "✅ SUCCESS: Count matches feature-table.tsv expectation."
    } else {
        println "❌ DISCREPANCY: Expected ${expected}, but found ${total}."
    }
} catch (e) {
    println "Error: ${e.message}"
}