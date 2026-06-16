import groovy.json.JsonSlurper
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.zip.GZIPInputStream

def sparqlEndpoint = "http://localhost:8895/sparql"

// Samples to validate
// Map: SampleName -> [RunAccession, FeatureTableColumn]
def samples = [
    "10Dr2": ["ERR16062320", "e0325_10Dr2"],
    "11Sr2": ["ERR16062327", "e0331_11Sr2"],
    "12Sr1": ["ERR16062333", "e0334_12Sr1"]
]

def runSparqlQuery(endpoint, query) {
    def encodedQuery = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
    def url = "${endpoint}?query=${encodedQuery}&format=json"
    def connection = new URL(url).openConnection()
    if (connection.responseCode != 200) throw new RuntimeException("HTTP ${connection.responseCode}")
    return new JsonSlurper().parse(connection.inputStream)
}

println "=== Taxonomy Abundance Validation ==="

// 1. SPARQL Validation
samples.each { sampleName, info ->
    def runAccession = info[0]
    println "\nValidating Sample: ${sampleName} (Run: ${runAccession})"
    
    // Query for Relative Abundance Sum
    def queryRel = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX sio: <http://semanticscience.org/resource/>
    PREFIX rak: <https://rubalkhali.science/kb/>
    
    SELECT (SUM(?val) as ?sumRel)
    WHERE {
        ?fastq rdfs:label "FASTQ dataset for ${runAccession}" .
        ?quality sio:SIO_000011 ?fastq .
        ?quality a rak:RAK_0000072 . # Relative Quality
        ?quality sio:SIO_000214 ?value .
        ?value rak:RAK_2000020 ?val .
        
        # Filter by Rank (Phylum)
        ?dataset sio:SIO_000059 ?value .
        ?dataset rdfs:label ?dsLabel .
        FILTER(CONTAINS(?dsLabel, "(Phylum)"))
    }
    """
    
    try {
        def jsonRel = runSparqlQuery(sparqlEndpoint, queryRel)
        def sumRel = jsonRel.results.bindings[0].sumRel.value.toDouble()
        println "  SPARQL Sum Relative Abundance: ${sumRel}"
        
        if (Math.abs(sumRel - 1.0) < 0.01) {
            println "  ✅ Relative abundance sums to approx 1.0"
        } else {
            println "  ❌ Relative abundance sum deviation: ${Math.abs(sumRel - 1.0)}"
        }
        
        // Query for Absolute Abundance Sum
        def queryAbs = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX sio: <http://semanticscience.org/resource/>
        PREFIX rak: <https://rubalkhali.science/kb/>
        
        SELECT (SUM(?val) as ?sumAbs)
        WHERE {
            ?fastq rdfs:label "FASTQ dataset for ${runAccession}" .
            ?quality sio:SIO_000011 ?fastq .
            ?quality a rak:RAK_0000078 . # Absolute Quality
            ?quality sio:SIO_000214 ?value .
            ?value rak:RAK_2000021 ?val .
            
            # Filter by Rank (Phylum)
            ?dataset sio:SIO_000059 ?value .
            ?dataset rdfs:label ?dsLabel .
            FILTER(CONTAINS(?dsLabel, "(Phylum)"))
        }
        """
        def jsonAbs = runSparqlQuery(sparqlEndpoint, queryAbs)
        def sumAbs = jsonAbs.results.bindings[0].sumAbs.value.toDouble()
        println "  SPARQL Sum Absolute Counts: ${sumAbs}"
        
        samples[sampleName] << sumAbs // Store for later comparison
        
    } catch (e) {
        println "  Error running SPARQL: ${e.message}"
        samples[sampleName] << 0.0
    }
}

// 2. Feature Table Validation
println "\nCalculating sums from feature-table.tsv (this may take a moment)..."
def featureTable = new File("data/processed/taxon-tables/feature-table.tsv")
def fileSums = samples.collectEntries { k, v -> [(k): 0.0] }

if (featureTable.exists()) {
    featureTable.withReader {
        reader ->
        // Skip first line comment
        reader.readLine() 
        
        // Parse header
        def headerLine = reader.readLine()
        def headers = headerLine.split('\t')
        
        // Map sample name to column index
        def colIndices = [: ]
        samples.each { name, info ->
            def colName = info[1]
            def idx = headers.findIndexOf { it == colName }
            if (idx != -1) {
                colIndices[name] = idx
            } else {
                println "  Warning: Column ${colName} not found in feature table header."
            }
        }
        
        // Iterate rows
        def line
        while ((line = reader.readLine()) != null) {
            def parts = line.split('\t')
            colIndices.each { name, idx ->
                if (idx < parts.size()) {
                    try {
                        fileSums[name] += parts[idx].toDouble()
                    } catch (NumberFormatException e) {
                        // ignore
                    }
                }
            }
        }
    }
    
    // Compare
    println "\n=== Comparison Results ==="
    samples.each { name, info ->
        def sparqlSum = info[2]
        def fileSum = fileSums[name]
        def diff = fileSum - sparqlSum
        println "Sample ${name}:"
        println "  Feature Table Sum: ${fileSum}"
        println "  RDF SPARQL Sum:    ${sparqlSum}"
        if (diff == 0) {
            println "  ✅ Exact Match"
        } else if (diff > 0) {
            println "  ⚠️  RDF is lower by ${diff} (${String.format('%.2f', (diff/fileSum)*100)}%). Likely due to unmapped OTUs."
        } else {
            println "  ❌ RDF is higher! This is unexpected."
        }
    }
    
} else {
    println "Error: feature-table.tsv not found."
}
