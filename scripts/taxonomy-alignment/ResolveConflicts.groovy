@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')
@Grab(group='commons-cli', module='commons-cli', version='1.5.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.apache.commons.csv.CSVFormat
import org.apache.commons.csv.CSVParser
import org.apache.commons.csv.CSVPrinter
import groovy.cli.commons.CliBuilder
import java.nio.file.Files
import java.nio.file.Paths
import java.nio.file.StandardOpenOption

class ResolveConflicts {

    static void main(String[] args) {
        def cli = new CliBuilder(usage: 'groovy ResolveConflicts.groovy -source <path> -target <path> -conflicts <path> -verified <path>')
        cli.source(args: 1, required: true, 'Path to source ontology')
        cli.target(args: 1, required: true, 'Path to target ontology')
        cli.conflicts(args: 1, required: true, 'Path to conflict_seeds.csv')
        cli.verified(args: 1, required: true, 'Path to existing verified_anchors.csv to append to')
        
        def options = cli.parse(args)
        if (!options) return

        new ResolveConflicts().run(options.source, options.target, options.conflicts, options.verified)
    }

    void run(String sourcePath, String targetPath, String conflictsPath, String verifiedPath) {
        println "Loading ontologies..."
        def manager = OWLManager.createOWLOntologyManager()
        def sourceOnt = manager.loadOntologyFromOntologyDocument(new File(sourcePath))
        def targetOnt = manager.loadOntologyFromOntologyDocument(new File(targetPath))

        println "Indexing parent labels/synonyms..."
        def sourceIndex = buildIndex(sourceOnt)
        def targetIndex = buildIndex(targetOnt)

        println "Processing conflicts..."
        List<Map<String, String>> resolved = []
        Map<String, Integer> parentHints = [:] // "sParentIRI|tParentIRI" -> count
        
        Files.newBufferedReader(Paths.get(conflictsPath)).withCloseable { reader ->
            CSVParser parser = new CSVParser(reader, CSVFormat.DEFAULT.withFirstRecordAsHeader())
            parser.each { record ->
                def row = record.toMap()
                def sIRI = IRI.create(row.source_iri)
                def tIRI = IRI.create(row.target_iri)

                // Get Parents
                def sParents = getParents(sourceOnt, sIRI)
                def tParents = getParents(targetOnt, tIRI)
                
                if (sParents.isEmpty() || tParents.isEmpty()) {
                    row.status = "RESOLVED_VALID_ROOT"
                    resolved << row
                    return
                }
                
                def sParent = sParents.first()
                def tParent = tParents.first()
                
                String sLabelRaw = getLabel(sourceOnt, sParent) ?: ""
                String tLabelRaw = getLabel(targetOnt, tParent) ?: ""
                
                String sLabelNorm = normalize(sLabelRaw)
                String tLabelNorm = normalize(tLabelRaw)
                
                String decision = "RESOLVED_MOVED" // Default: Structural Change (Reclassification)

                // Step B: Check for Valid Parent Match
                // Direct Normalized Match
                if (sLabelNorm == tLabelNorm && !sLabelNorm.isEmpty()) {
                    decision = "RESOLVED_RANK_SHIFT" // Parents match by name, so difference was likely rank or ID
                } 
                // Synonym Match (Source Parent name exists as synonym in Target Parent)
                else if (checkSynonymMatch(targetIndex, tParent, sLabelRaw)) {
                     decision = "RESOLVED_SYNONYM"
                }
                // Reverse Synonym Match
                else if (checkSynonymMatch(sourceIndex, sParent, tLabelRaw)) {
                     decision = "RESOLVED_SYNONYM"
                }
                
                // Step C & D: If not a name match, it is a Move/Reclassification
                if (decision == "RESOLVED_MOVED") {
                    // Log the hint
                    def hintKey = "${sParent.toString()}|${tParent.toString()}"
                    parentHints[hintKey] = parentHints.getOrDefault(hintKey, 0) + 1
                }
                
                row.status = decision
                resolved << row
            }
        }
        
        println "Resolved ${resolved.size()} conflicts."
        
        // Append to verified_anchors.csv
        println "Appending to $verifiedPath..."
        def verifiedFile = Paths.get(verifiedPath)
        
        // Check if file exists to determine if we need a header (if creating new) - usually we append
        // But prompt says "Append". 
        // CSVPrinter by default won't add header if we don't ask, but we should ensure column order matches verified_anchors.
        // verified_anchors cols: source_iri,target_iri,match_string,match_type,status,s_rank,t_rank
        
        Files.newBufferedWriter(verifiedFile, StandardOpenOption.APPEND).withCloseable { writer ->
            def printer = new CSVPrinter(writer, CSVFormat.DEFAULT) 
            resolved.each { r ->
                printer.printRecord(r.source_iri, r.target_iri, r.match_string, r.match_type, r.status, r.s_rank, r.t_rank)
            }
            printer.flush()
        }
        
        // Write parent_hints.csv
        println "Writing parent_hints.csv..."
        Files.newBufferedWriter(Paths.get("parent_hints.csv")).withCloseable { writer ->
             def printer = new CSVPrinter(writer, CSVFormat.DEFAULT.withHeader("source_parent_iri", "target_parent_iri", "evidence_count", "type"))
             parentHints.each { key, count ->
                 def parts = key.split("\\|")
                 // Type is inferred: "Reclassification"
                 printer.printRecord(parts[0], parts[1], count, "Reclassification")
             }
        }
    }

    // --- Helpers ---
    
    String normalize(String label) {
        if (!label) return ""
        String s = label.trim().toLowerCase()
        s = s.replaceAll(/^[dpcofgs]__/, "")
        s = s.replaceAll(/_[a-z0-9]+$/, "") // remove GTDB suffixes
        s = s.replaceAll(/^candidatus\s+/, "")
        s = s.replaceAll(/^ca\.\s+/, "")
        return s.trim()
    }

    Map<String, Set<IRI>> buildIndex(OWLOntology ont) {
        def index = [:].withDefault { new HashSet() }
        ont.getClassesInSignature(true).each { cls ->
             EntitySearcher.getAnnotations(cls, ont).each { ann ->
                  if (ann.getValue().isLiteral()) {
                       // We should normalize here too? Or keep raw for strict synonym lookup?
                       // Prompt: "Synonym Match: Does a synonym of Source_Parent match Target_Parent (normalized)?"
                       // Let's store raw lowercase for broader matching, or normalized?
                       // Safer to store normalized keys if we compare normalized query.
                       def val = ann.getValue().asLiteral().get().getLiteral()
                       index[normalize(val)].add(cls.getIRI())
                  }
             }
        }
        return index
    }
    
    boolean checkSynonymMatch(Map<String, Set<IRI>> index, IRI subjectIRI, String queryLabel) {
        def q = normalize(queryLabel)
        if (index.containsKey(q)) {
            return index[q].contains(subjectIRI)
        }
        return false
    }

    String getLabel(OWLOntology ont, IRI iri) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        String label = null
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            if (ann.getProperty().isLabel() && ann.getValue().isLiteral()) {
                label = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        return label
    }

    Set<IRI> getParents(OWLOntology ont, IRI iri) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        def parents = new HashSet<IRI>()
        EntitySearcher.getSuperClasses(cls, ont).each { ce ->
             if (!ce.isAnonymous()) {
                 parents.add(ce.asOWLClass().getIRI())
             }
        }
        return parents
    }
}