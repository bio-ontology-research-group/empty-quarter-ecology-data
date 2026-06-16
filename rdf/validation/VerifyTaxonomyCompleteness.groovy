@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='com.google.code.gson', module='gson', version='2.10.1')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import com.google.gson.Gson
import java.nio.file.Files
import java.nio.file.Paths

class VerifyTaxonomyCompleteness {

    static void main(String[] args) {
        new VerifyTaxonomyCompleteness().run()
    }

    void run() {
        println "Loading module..."
        def manager = OWLManager.createOWLOntologyManager()
        def ont = manager.loadOntologyFromOntologyDocument(new File("data/processed/ontology/ecosystem_module.owl"))
        
        println "Loading mapping..."
        def gson = new Gson()
        def mappingType = new com.google.gson.reflect.TypeToken<Map<String, List<Map>>>(){}.getType()
        Map<String, List<Map>> mappings = gson.fromJson(new File("data/processed/ontology/mapped_taxonomy.json").text, mappingType)
        
        List<String> taxa = Files.readAllLines(Paths.get("data/taxonomy/unique_taxa.txt")).findAll { !it.trim().isEmpty() }
        
        println "Verifying ${taxa.size()} taxa..."
        
        int passed = 0
        int failed = 0
        List<String> failures = []
        
        taxa.each { taxonStr ->
            boolean taxonPassed = true
            List<Map> pathMap = mappings[taxonStr]
            
            if (!pathMap) {
                failures << "NO MAPPING: $taxonStr"
                taxonPassed = false
            } else {
                // Check Leaf
                def leaf = pathMap.last()
                if (leaf.iri == null) {
                    failures << "UNMAPPED LEAF: $taxonStr (Leaf: ${leaf.name})"
                    taxonPassed = false
                } else {
                    IRI leafIRI = IRI.create(leaf.iri)
                    if (!ont.containsClassInSignature(leafIRI)) {
                        failures << "MISSING IN MODULE: $taxonStr (IRI: $leafIRI)"
                        taxonPassed = false
                    } else {
                        // Check Label
                        String label = getLabel(ont, leafIRI)
                        if (!label) {
                            failures << "NO LABEL: $taxonStr (IRI: $leafIRI)"
                            taxonPassed = false
                        }
                        
                        // Check Ancestry Depth
                        // We expect to find parents up to Root.
                        // Count depth by traversing subclass relationships in the module
                        int depth = getDepth(ont, leafIRI)
                        
                        // Rule: A valid taxonomy usually has at least Domain(1), Phylum(2), Class(3)...
                        // Some paths might be shorter (Unclassified Bacteria).
                        // Let's check if depth is reasonable relative to the input string parts.
                        // Input string: "d__Bacteria;p__..." -> 2 parts. Depth should be >= 2.
                        int inputDepth = taxonStr.split(";").size()
                        
                        // Adjust inputDepth for "NA" trails? No, usually distinct levels.
                        if (depth < inputDepth && depth < 2) { // Allow some slack, but < 2 is weird for bacteria
                             failures << "SHALLOW ANCESTRY: $taxonStr (Input Parts: $inputDepth, Module Depth: $depth)"
                             taxonPassed = false
                        }
                    }
                }
            }
            
            if (taxonPassed) passed++
            else failed++
        }
        
        println "\n=== Verification Results ==="
        println "Total: ${taxa.size()}"
        println "Passed: $passed"
        println "Failed: $failed"
        
        if (failed > 0) {
            println "\nFailures (First 20):"
            failures.take(20).each { println it }
            
            // Save failures
            new File("data/taxonomy/verification_failures.txt").text = failures.join("\n")
            println "All failures written to data/taxonomy/verification_failures.txt"
        } else {
            println "ALL CHECKS PASSED."
        }
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
    
    int getDepth(OWLOntology ont, IRI iri) {
        return getDepthRecursive(ont, iri, new HashSet<IRI>())
    }

    int getDepthRecursive(OWLOntology ont, IRI iri, Set<IRI> visited) {
        if (visited.contains(iri)) return 0 // Cycle detected, stop depth counting
        visited.add(iri)
        
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        if (cls.isOWLThing()) return 0
        
        int maxDepth = 0
        EntitySearcher.getSuperClasses(cls, ont).each { ce ->
            if (!ce.isAnonymous()) {
                // Pass a copy or the same set? 
                // Same set for this path.
                int d = getDepthRecursive(ont, ce.asOWLClass().getIRI(), new HashSet<>(visited))
                if (d > maxDepth) maxDepth = d
            }
        }
        return maxDepth + 1
    }
}
