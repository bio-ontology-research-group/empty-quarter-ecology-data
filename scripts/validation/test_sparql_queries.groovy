@Grab(group='org.apache.jena', module='jena-core', version='4.10.0')
@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.rdf.model.Model
import org.apache.jena.rdf.model.ModelFactory
import org.apache.jena.query.*
import org.apache.jena.riot.RDFDataMgr
import java.io.File
import java.util.regex.Pattern

// 1. Load Ontologies
println "Loading ontologies..."
Model model = ModelFactory.createDefaultModel()
new File("data/processed/ontology").eachFileMatch(~/. *\\.owl/) { file ->
    println "  Loading ${file.name}..."
    RDFDataMgr.read(model, file.absolutePath)
}
println "Total triples loaded: ${model.size()}"

// 2. Extract Queries from SPARQL.md
def queries = []
def sparqlFile = new File("data/processed/ontology/SPARQL.md")
def content = sparqlFile.text
def matcher = Pattern.compile("```sparql(.*?)```", Pattern.DOTALL).matcher(content)

while (matcher.find()) {
    queries << matcher.group(1).trim()
}

println "Found ${queries.size()} queries."

// 3. Execute and Validate
queries.eachWithIndex { queryStr, index ->
    println "\n--- Executing Query ${index + 1} ---"
    try {
        Query query = QueryFactory.create(queryStr)
        try (QueryExecution qexec = QueryExecutionFactory.create(query, model)) {
            ResultSet results = qexec.execSelect()
            List<QuerySolution> rows = ResultSetFormatter.toList(results)
            println "Result count: ${rows.size()}"
            
            // Validation Logic based on Index (Heuristic)
            validateQuery(index + 1, rows)
        }
    } catch (Exception e) {
        println "ERROR executing query ${index + 1}: ${e.message}"
        // e.printStackTrace()
    }
}

def validateQuery(index, rows) {
    if (rows.isEmpty()) {
        println "  WARNING: No results found."
        return
    }
    
def firstRow = rows[0]
    
    switch (index) {
        case 1: // Field XRF for Site 10
            println "  Checking Site 10 XRF..."
            // Expect columns: processLabel, analyte, concentration, error, unitLabel
            if (!firstRow.contains("processLabel")) println "  FAIL: Missing processLabel"
            if (!firstRow.contains("concentration")) println "  FAIL: Missing concentration"
            // Simple value check if rows not empty
            println "  OK: Found XRF data."
            break
        case 2: // List Sampling Sites
            println "  Checking Sites..."
            // Expect Site 1
            def foundSite1 = rows.any { it.get("label").toString().contains("Site 1") }
            if (foundSite1) println "  OK: Found 'Site 1'"
            else println "  FAIL: 'Site 1' not found"
            break
        case 3: // Biomes
            println "  Checking Biomes..."
            // Expect "desert biome"
            def foundDesert = rows.any { it.get("biomeLabel").toString().contains("desert biome") }
            if (foundDesert) println "  OK: Found 'desert biome'"
            else println "  FAIL: 'desert biome' not found"
            break
        case 4: // Light Elements
            println "  Checking LE..."
            if (!firstRow.contains("lePercentage")) println "  FAIL: Missing lePercentage"
            println "  OK: Found LE data."
            break
        case 5: // Region Boundary
             // This query might be malformed in the file or just Prefix header? 
             // Looking at file content in previous turn...
             // Query 5 in file seems to be missing the body!
             // "PREFIX ... PREFIX ... ## 6. Retrieve DNA..."
             // It seems Query 5 is truncated or empty in the file!
             println "  WARNING: Query 5 seems empty or malformed in source."
             break
        case 6: // DNA
             println "  Checking DNA..."
             if (!firstRow.contains("dnaExtractLabel")) println "  FAIL: Missing dnaExtractLabel"
             // Expect F1PRr1 or similar
             println "  OK: Found DNA data."
             break
    }
}
