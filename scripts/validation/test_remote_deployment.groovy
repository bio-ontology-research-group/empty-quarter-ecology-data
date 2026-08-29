import groovy.json.JsonSlurper
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

// Configuration
def sparqlEndpoint = "http://10.73.11.158:8895/sparql"
def sparqlFile = new File("data/processed/ontology/SPARQL.md")

println "Targeting Remote Endpoint: ${sparqlEndpoint}"

// 2. Parse Queries
if (!sparqlFile.exists()) {
    println "ERROR: SPARQL.md not found at ${sparqlFile.absolutePath}"
    System.exit(1)
}

def content = sparqlFile.text
def matcher = (content =~ /(?s)```sparql(.*?)```/)
def blocks = []
while (matcher.find()) { blocks << matcher.group(1).trim() }
if (blocks.isEmpty()) {
     println "ERROR: No SPARQL blocks found in ${sparqlFile.name}"
     System.exit(1)
}

def prefixes = blocks[0]
def queries = blocks.drop(1)

// 3. Execute
int passed = 0
int failed = 0

queries.eachWithIndex { queryBody, index ->
    def queryNum = index + 1
    println "\n--- Query ${queryNum} ---"
    def fullQuery = queryBody.trim().toLowerCase().startsWith("prefix") ? queryBody : prefixes + "\n" + queryBody
    try {
        def json = runSparqlQuery(sparqlEndpoint, fullQuery)
        def bindings = json.results.bindings
        println "Results: ${bindings.size()}"
        
        // Basic Validation Logic
        if (bindings.size() > 0) {
            passed++
             // specific checks per query if needed
            switch(queryNum) {
                case 1: // Site 10 XRF
                    if (bindings.any { it.processLabel?.value?.contains("5847") }) println "  [PASS] Found Test 5847"
                    break
                case 2: // Sites
                    if (bindings.any { it.label?.value?.contains("Site 1") }) println "  [PASS] Found Site 1"
                    break
                case 3: // Biomes
                    if (bindings.any { it.biomeLabel?.value?.contains("desert") }) println "  [PASS] Found desert biome"
                    break
                case 5: // DNA
                    if (bindings.any { it.soilSampleLabel?.value?.contains("1Dr1") }) println "  [PASS] Found DNA for 1Dr1"
                    break
            }
        } else {
             println "  [WARN] No results returned."
             // Query 7 might be empty depending on data
        }

    } catch (e) { 
        println "  [FAIL] ERROR: ${e.message}" 
        failed++
    }
}

println "\nSummary: ${passed} Queries Executed Successfully, ${failed} Failed."

def runSparqlQuery(endpoint, query) {
    def encodedQuery = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
    def url = "${endpoint}?query=${encodedQuery}&format=json"
    def connection = new URL(url).openConnection()
    connection.setConnectTimeout(5000)
    connection.setReadTimeout(10000)
    if (connection.responseCode != 200) {
        throw new RuntimeException("HTTP ${connection.responseCode} - ${connection.responseMessage}")
    }
    return new JsonSlurper().parse(connection.inputStream)
}

