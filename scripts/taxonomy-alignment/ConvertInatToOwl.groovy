@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')

import org.apache.commons.csv.CSVFormat
import org.apache.commons.csv.CSVParser
import java.nio.file.Files
import java.nio.file.Paths
import java.nio.charset.StandardCharsets

class ConvertInatToOwl {

    static void main(String[] args) {
        new ConvertInatToOwl().run(
            "data/taxonomy/inat_taxa.csv",
            "data/taxonomy/inat-darwin-core/VernacularNames-english.csv",
            "data/taxonomy/inat_converted.owl"
        )
    }

    void run(String taxCsvPath, String vernCsvPath, String outputPath) {
        println "Starting iNaturalist conversion (Full Dataset)..." 
        
        // 1. Load Common Names (In Memory - approx 200k keys, manageable)
        Map<String, Set<String>> commonNames = loadCommonNames(vernCsvPath)
        println "Loaded common names for ${commonNames.size()} taxa."

        // 2. Open Output Writer
        println "Writing ontology to $outputPath..."
        int processedCount = 0
        
        Files.newBufferedWriter(Paths.get(outputPath), StandardCharsets.UTF_8).withCloseable { writer ->
            
            // 3. Write Header
            writeHeader(writer)
            
            // 4. Stream and Process Taxonomy
            println "Processing taxonomy from $taxCsvPath..."
            
            Files.newBufferedReader(Paths.get(taxCsvPath)).withCloseable { reader ->
                // Use TDF and disable quoting to handle messy data
                CSVParser parser = new CSVParser(reader, CSVFormat.TDF.withFirstRecordAsHeader().withQuote(null))
                
                parser.each { record ->
                    try {
                        String id = record.get("taxon_id")
                        String name = record.get("name")
                        String rank = record.get("rank")
                        String ancestry = record.get("ancestry") 
                        
                        // Infer parent from ancestry
                        String parentId = null
                        if (ancestry) {
                            def parts = ancestry.split("/")
                            if (parts.length > 0) {
                                parentId = parts.last()
                            }
                        }
                        
                        if (id) {
                            writeTaxon(writer, id, name, rank, parentId, commonNames[id])
                            processedCount++
                            if (processedCount % 50000 == 0) print "."
                        }
                    } catch (Exception e) {
                        // Log error but continue
                        // System.err.println("Error processing line ${parser.getCurrentLineNumber()}: ${e.message}")
                    }
                }
            }
            
            // 5. Write Footer
            writer.write(" )\n")
        }
        
        println "\nConversion complete."
        println "Total Taxa Processed: $processedCount"
    }

    void writeHeader(BufferedWriter writer) {
        writer.write("Prefix(owl:=<http://www.w3.org/2002/07/owl#>)\n")
        writer.write("Prefix(rdf:=<http://www.w3.org/1999/02/22-rdf-syntax-ns#>)\n")
        writer.write("Prefix(xml:=<http://www.w3.org/XML/1998/namespace>)\n")
        writer.write("Prefix(xsd:=<http://www.w3.org/2001/XMLSchema#>)\n")
        writer.write("Prefix(rdfs:=<http://www.w3.org/2000/01/rdf-schema#>)\n")
        writer.write("Prefix(skos:=<http://www.w3.org/2004/02/skos/core#>)\n")
        writer.write("Prefix(ncbitaxon:=<http://purl.obolibrary.org/obo/ncbitaxon#>)\n")
        writer.write("Prefix(inat:=<http://inaturalist.org/taxa/>)\n\n")
        writer.write("Ontology(<http://inaturalist.org/taxonomy>\n")
    }

    void writeTaxon(BufferedWriter writer, String id, String name, String rank, String parentId, Set<String> vernaculars) {
        String iri = "<http://inaturalist.org/taxa/${id}>"
        
        // Declaration
        writer.write("Declaration(Class(${iri}))\n")
        
        // Label
        if (name) {
            String escapedName = escapeLiteral(name)
            writer.write("AnnotationAssertion(rdfs:label ${iri} \"${escapedName}\"^^xsd:string)\n")
        }
        
        // Rank
        if (rank) {
            String rankLower = rank.toLowerCase()
            writer.write("AnnotationAssertion(ncbitaxon:has_rank ${iri} \"${rankLower}\"^^xsd:string)\n")
        }
        
        // SubClassOf
        if (parentId && parentId.trim() != "") {
            String parentIri = "<http://inaturalist.org/taxa/${parentId}>"
            writer.write("SubClassOf(${iri} ${parentIri})\n")
        }
        
        // Common Names
        if (vernaculars) {
            vernaculars.each { vn ->
                String escapedVn = escapeLiteral(vn)
                writer.write("AnnotationAssertion(skos:altLabel ${iri} \"${escapedVn}\"@en)\n")
            }
        }
    }
    
    String escapeLiteral(String literal) {
        return literal.replace("\\", "\\\\").replace("\"", "\\\"")
    }

    Map<String, Set<String>> loadCommonNames(String path) {
        Map<String, Set<String>> map = [:].withDefault { new HashSet() }
        try {
            if (!Files.exists(Paths.get(path))) {
                println "Warning: Common names file not found at $path"
                return map
            }
            
            Files.newBufferedReader(Paths.get(path)).withCloseable { reader ->
                CSVParser parser = new CSVParser(reader, CSVFormat.DEFAULT.withFirstRecordAsHeader())
                parser.each {
                     record ->
                    String id = null
                    if (record.isMapped("id")) id = record.get("id")
                    else if (record.isMapped("taxonID")) id = record.get("taxonID")
                    
                    String name = null
                    if (record.isMapped("vernacularName")) name = record.get("vernacularName")
                    
                    if (id && name) {
                        map[id].add(name)
                    }
                }
            }
        } catch (Exception e) {
            println "Warning: Failed to load common names: ${e.message}"
        }
        return map
    }
}