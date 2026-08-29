@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='com.google.code.gson', module='gson', version='2.10.1')
@Grab(group='commons-cli', module='commons-cli', version='1.5.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.semanticweb.owlapi.reasoner.structural.StructuralReasonerFactory
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import groovy.cli.commons.CliBuilder
import java.nio.file.Files
import java.nio.file.Paths

class PrepAgentCandidates {

    static void main(String[] args) {
        def cli = new CliBuilder(usage: 'groovy PrepAgentCandidates.groovy -ontology <path> -anchors <path>')
        cli.ontology(args: 1, required: true, 'Path to merged_taxonomy.owl')
        cli.anchors(args: 1, required: true, 'Path to verified_anchors.csv') // Needed to identify "shared" children easily
        
        def options = cli.parse(args)
        if (!options) return

        new PrepAgentCandidates().run(options.ontology, options.anchors)
    }

    void run(String ontologyPath, String anchorsPath) {
        println "Initializing..."
        def manager = OWLManager.createOWLOntologyManager()
        
        println "Loading Ontology: $ontologyPath..."
        def ont = manager.loadOntologyFromOntologyDocument(new File(ontologyPath))
        
        println "Loading Anchors..."
        Set<String> sharedIRIs = new HashSet<>()
        new File(anchorsPath).eachLine { line, count ->
            if (count > 1) { // Skip header
                def parts = line.split(",")
                if (parts.size() >= 2) {
                    sharedIRIs.add(parts[0]) // Source IRI
                    sharedIRIs.add(parts[1]) // Target IRI
                }
            }
        }
        println "Loaded ${sharedIRIs.size()} anchored IRIs."

        // 1. Find Sensu Candidates
        println "Scanning for 'sensu' conflicts..."
        Map<String, OWLClass> ncbiMap = [:] // Name -> Class
        Map<String, OWLClass> gtdbMap = [:] // Name -> Class
        
        ont.getClassesInSignature(true).each { cls ->
            String label = getLabel(ont, cls)
            if (label) {
                if (label.endsWith("(sensu NCBI)")) {
                    String coreName = label.replace(" (sensu NCBI)", "").trim()
                    ncbiMap[coreName] = cls
                } else if (label.endsWith("(sensu GTDB)")) {
                    String coreName = label.replace(" (sensu GTDB)", "").trim()
                    gtdbMap[coreName] = cls
                }
            }
        }
        
        println "Found ${ncbiMap.size()} NCBI sensu classes and ${gtdbMap.size()} GTDB sensu classes."

        // 2. Pair and Filter
        List<Map> candidates = []
        def validRanks = ["genus", "family", "order", "class", "phylum"]
        
        ncbiMap.each { name, ncbiClass ->
            if (gtdbMap.containsKey(name)) {
                OWLClass gtdbClass = gtdbMap[name]
                
                String rank = getRank(ont, ncbiClass)
                if (rank && validRanks.contains(rank.toLowerCase())) {
                    
                    // Analyze Children
                    def ncbiChildren = getChildren(ont, ncbiClass)
                    def gtdbChildren = getChildren(ont, gtdbClass)
                    
                    // Count Shared vs Unique
                    int sharedCount = 0
                    int ncbiUnique = 0
                    int gtdbUnique = 0
                    
                    // How to determine "Shared"?
                    // 1. If Child IRI is in sharedIRIs set (meaning it was anchored)
                    // 2. AND if the anchor maps to a child in the other set?
                    // Simplifying: Just count children that are "Anchored" (Verified)
                    // If a child is an "EquivalentClass" (merged), it appears in both sets?
                    // If merged in Phase 2, then yes, the same IRI (or equivalent) might appear?
                    // Wait, if they are Equivalent, they are effectively the same class.
                    // But here we are analyzing PARENTS that are NOT equivalent.
                    // So their children might be equivalent.
                    
                    // Use Reasoner or simple check?
                    // If merged_taxonomy.owl has EquivalentClasses for children, we need to respect that.
                    // But `getChildren` returns specific IRIs.
                    // If child A (NCBI) is equivalent to child B (GTDB), they are shared.
                    
                    // Let's use the `sharedIRIs` set. 
                    // If a child in NCBI list is in `sharedIRIs`, it means it has a match in GTDB.
                    // Does that match belong to `gtdbClass`?
                    // That's the real question.
                    // Approximation: Count how many children are "Anchored".
                    
                    // Better metric: Intersection of Child Names? Or exact IRI equivalence?
                    // Since Phase 2 merged verified anchors, `merged_taxonomy.owl` contains `EquivalentClasses(A, B)`.
                    // We should check if `A` (child of NCBI Parent) is equivalent to any `B` (child of GTDB Parent).
                    
                    // Let's use a Structural Reasoner to resolve equivalence of children.
                    def factory = new StructuralReasonerFactory()
                    def reasoner = factory.createReasoner(ont)
                    
                    Set<OWLClass> ncbiChildEquivs = new HashSet<>()
                    ncbiChildren.each { c -> 
                        ncbiChildEquivs.add(c)
                        reasoner.getEquivalentClasses(c).each { eq -> ncbiChildEquivs.add(eq) }
                    }
                    
                    Set<OWLClass> gtdbChildEquivs = new HashSet<>()
                    gtdbChildren.each { c ->
                        gtdbChildEquivs.add(c)
                        reasoner.getEquivalentClasses(c).each { eq -> gtdbChildEquivs.add(eq) }
                    }
                    
                    // Intersection
                    Set<OWLClass> intersection = new HashSet<>(ncbiChildEquivs)
                    intersection.retainAll(gtdbChildEquivs)
                    
                    // But we count "Logical Entities", not IRIs.
                    // If A == B, that's 1 shared child.
                    // The intersection set will contain both A and B.
                    // We need to deduplicate by equivalence.
                    // Or simpler: Iterate NCBI children, check if (Child OR its Equivalent) is in GTDB Children list.
                    
                    Set<OWLClass> sharedEntities = new HashSet<>()
                    Set<OWLClass> gtdbChildrenSet = new HashSet<>(gtdbChildren)
                    
                    ncbiChildren.each { nc ->
                        boolean isShared = false
                        // Check exact or equivalent
                        if (gtdbChildrenSet.contains(nc)) isShared = true
                        else {
                            reasoner.getEquivalentClasses(nc).each { eq ->
                                if (gtdbChildrenSet.contains(eq)) isShared = true
                            }
                        }
                        
                        if (isShared) {
                            sharedCount++
                        } else {
                            ncbiUnique++
                        }
                    }
                    gtdbUnique = gtdbChildren.size() - sharedCount // Approximation
                    if (gtdbUnique < 0) gtdbUnique = 0 // Safety
                    
                    candidates << [
                        name: name,
                        rank: rank,
                        ncbi_iri: ncbiClass.getIRI().toString(),
                        gtdb_iri: gtdbClass.getIRI().toString(),
                        shared_children_count: sharedCount,
                        ncbi_total_children: ncbiChildren.size(),
                        gtdb_total_children: gtdbChildren.size(),
                        ncbi_unique_count: ncbiUnique,
                        gtdb_unique_count: gtdbUnique
                    ]
                }
            }
        }
        
        // Output JSON
        String jsonPath = "conflict_candidates.json"
        println "Writing ${candidates.size()} candidates to $jsonPath..."
        def gson = new GsonBuilder().setPrettyPrinting().create()
        Files.newBufferedWriter(Paths.get(jsonPath)).withCloseable { writer ->
            writer.write(gson.toJson(candidates))
        }
    }

    String getLabel(OWLOntology ont, OWLClass cls) {
        String label = null
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            if (ann.getProperty().isLabel() && ann.getValue().isLiteral()) {
                label = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        return label
    }
    
    String getRank(OWLOntology ont, OWLClass cls) {
        String rank = null
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            def propStr = ann.getProperty().getIRI().toString()
            if (propStr.endsWith("has_rank") && ann.getValue().isLiteral()) {
                rank = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        return rank
    }
    
    List<OWLClass> getChildren(OWLOntology ont, OWLClass cls) {
        List<OWLClass> children = []
        EntitySearcher.getSubClasses(cls, ont).each { ce ->
            if (!ce.isAnonymous()) {
                children << ce.asOWLClass()
            }
        }
        return children
    }
}
