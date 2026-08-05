import groovy.json.JsonSlurper
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

def sparqlEndpoint = "http://10.73.11.158:8085/sparql"
def fastqIri = "https://rubalkhali.science/kb/RAK_7790087"

def runSparqlQuery(endpoint, query) {
    def encodedQuery = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
    def url = "${endpoint}?query=${encodedQuery}&format=json"
    def connection = new URL(url).openConnection()
    if (connection.responseCode != 200) {
        println "Error: HTTP ${connection.responseCode}"
        return null
    }
    return new JsonSlurper().parse(connection.inputStream)
}

println "Checking for qualities linked to ${fastqIri}..."
def query = """
PREFIX sio: <http://semanticscience.org/resource/>
SELECT ?quality ?type WHERE {
  ?quality sio:SIO_000011 <${fastqIri}> .
  OPTIONAL { ?quality a ?type }
} LIMIT 10
"""

def json = runSparqlQuery(sparqlEndpoint, query)
println "JSON Response: " + groovy.json.JsonOutput.toJson(json)