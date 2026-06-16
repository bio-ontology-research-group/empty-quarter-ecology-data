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

// 1. Query for sums (using the new dataset structure)
def sumQuery = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX rak: <https://rubalkhali.science/kb/>

SELECT (SUM(?count) AS ?totalSum) (SUM(?relAb) AS ?totalRelAb) (COUNT(DISTINCT ?taxon) AS ?countTaxa)
WHERE {
  ?fastq rdfs:label "FASTQ dataset for ERR16062320" .
  
  # Absolute
  ?qualAbs sio:SIO_000011 ?fastq ;
           a rak:RAK_0000078 ;
           sio:SIO_000214 ?valAbs ;
           sio:SIO_000011 ?taxon .
  ?valAbs rak:RAK_2000021 ?count .
  
  # Relative
  ?qualRel sio:SIO_000011 ?fastq ;
           a rak:RAK_0000072 ;
           sio:SIO_000214 ?valRel ;
           sio:SIO_000011 ?taxon .
  ?valRel rak:RAK_2000020 ?relAb .

  FILTER(?taxon != ?fastq)
}
"""

def taxaQuery = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX rak: <https://rubalkhali.science/kb/>

SELECT DISTINCT ?taxonLabel ?count ?relAb
WHERE {
  ?fastq rdfs:label "FASTQ dataset for ERR16062320" .
  
  ?qualAbs sio:SIO_000011 ?fastq ;
           a rak:RAK_0000078 ;
           sio:SIO_000214 ?valAbs ;
           sio:SIO_000011 ?taxon .
  ?taxon rdfs:label ?taxonLabel .
  ?valAbs rak:RAK_2000021 ?count .
  
  ?qualRel sio:SIO_000011 ?fastq ;
           a rak:RAK_0000072 ;
           sio:SIO_000214 ?valRel ;
           sio:SIO_000011 ?taxon .
  ?valRel rak:RAK_2000020 ?relAb .

  FILTER(?taxon != ?fastq)
  FILTER(?taxonLabel IN ("Beijerinckiaceae", "Luedemannella", "AKIW781 (Family)"))
}
"""

println "Executing Aggregate Validation against Virtuoso (Run ERR16062320 / Sample 10Dr2)..."
try {
    println "Fetching sums..."
    def sumJson = runSparqlQuery(sparqlEndpoint, sumQuery)
    def sumB = sumJson.results.bindings[0]
    
    double totalSum = sumB.totalSum.value.toDouble()
    double totalRelAb = sumB.totalRelAb.value.toDouble()
    int countTaxa = sumB.countTaxa.value.toInteger()

    println "\n--- Summary Statistics ---"
    println "Unique Taxa Entries Found: ${countTaxa}"
    println "Sum of All Counts:         ${totalSum} (Expected: 503679.0)"
    println "Sum of Relative Abundance: ${totalRelAb} (Expected: ~1.0)"
    
    if (Math.abs(totalSum - 503679.0) < 0.1) println "✅ Total Count Matches."
    else println "❌ Total Count Mismatch."
    
    if (Math.abs(totalRelAb - 1.0) < 0.0001) println "✅ Sum of RelAb is 1.0."
    else println "❌ Sum of RelAb Mismatch."

    println "\nFetching specific taxa..."
    def taxaJson = runSparqlQuery(sparqlEndpoint, taxaQuery)
    def taxaResults = taxaJson.results.bindings
    
    def expected = [
        "Beijerinckiaceae": [count: 33771.0],
        "Luedemannella":    [count: 12747.0],
        "AKIW781 (Family)": [count: 28463.0]
    ]

    taxaResults.each { b ->
        String label = b.taxonLabel.value
        double c = b.count.value.toDouble()
        println "${label}: ${c} (Expected: ${expected[label].count}) " + 
                (Math.abs(c - expected[label].count) < 0.1 ? "✅" : "❌")
    }

} catch (e) {
    println "Error: ${e.message}"
}
