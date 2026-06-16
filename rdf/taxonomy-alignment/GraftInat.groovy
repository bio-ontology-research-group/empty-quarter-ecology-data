@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='commons-cli', module='commons-cli', version='1.5.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.semanticweb.owlapi.formats.FunctionalSyntaxDocumentFormat
import groovy.cli.commons.CliBuilder
import java.nio.file.Files
import java.nio.file.Paths

class GraftInat {

    // Rank properties
    static final List<String> RANK_PROPS = [
        "http://purl.obolibrary.org/obo/ncbitaxon#has_rank",
        "http://gtdb.ecogenomic.org/taxonomy/rank", 
        "http://www.geneontology.org/formats/oboInOwl#has_rank"
    ]
    
    // Explicit Rank mapping for NCBI subclass check
    static final Map<String, String> NCBI_RANK_CLASSES = [
        "http://purl.obolibrary.org/obo/NCBITaxon_species": "species",
        "http://purl.obolibrary.org/obo/NCBITaxon_genus": "genus",
        "http://purl.obolibrary.org/obo/NCBITaxon_family": "family",
        "http://purl.obolibrary.org/obo/NCBITaxon_order": "order",
        "http://purl.obolibrary.org/obo/NCBITaxon_class": "class",
        "http://purl.obolibrary.org/obo/NCBITaxon_phylum": "phylum",
        "http://purl.obolibrary.org/obo/NCBITaxon_superkingdom": "domain"
    ]

    static void main(String[] args) {
        def cli = new CliBuilder(usage: 'groovy GraftInat.groovy -base <path> -inat <path> -output <path>')
        cli.base(args: 1, required: true, 'Path to base ontology (merged_taxonomy.owl)')
        cli.inat(args: 1, required: true, 'Path to iNaturalist ontology (inat_converted.owl)')
        cli.output(args: 1, required: true, 'Path to output ontology (final_ecosystem.owl)')
        
        def options = cli.parse(args)
        if (!options) return

        new GraftInat().run(options.base, options.inat, options.output)
    }

    void run(String basePath, String inatPath, String outputPath) {
        println "Initializing Manager..."
        def manager = OWLManager.createOWLOntologyManager()
        def df = manager.getOWLDataFactory()

        // 1. Load Ontologies
        println "Loading Base: $basePath"
        def baseOnt = manager.loadOntologyFromOntologyDocument(new File(basePath))
        
        println "Loading iNaturalist: $inatPath"
        def inatOnt = manager.loadOntologyFromOntologyDocument(new File(inatPath))

        // 2. Index Base (Label -> List<Class>)
        println "Indexing Base Ontology..."
        Map<String, List<OWLClass>> baseIndex = [:].withDefault { [] }
        
        baseOnt.getClassesInSignature(true).each {
             cls ->
             String label = getLabel(baseOnt, cls)
             String norm = normalize(label)
             if (norm) {
                 baseIndex[norm] << cls
             }
        }
        println "Base Index Size: ${baseIndex.size()} keys"

        // 3. Smart Lexical Anchoring (Step A)
        println "Anchoring iNaturalist Classes..."
        int anchorCount = 0
        int disambiguatedCount = 0
        int failedDisambiguationCount = 0
        
        def finalOnt = manager.createOntology(IRI.create("http://merged.taxonomy.org/final_ecosystem"))
        
        // Copy axioms first (Merge Step)
        println "Merging axioms into Final Ontology..."
        manager.addAxioms(finalOnt, baseOnt.getAxioms())
        manager.addAxioms(finalOnt, inatOnt.getAxioms())
        
        // Iterate Inat Classes
        inatOnt.getClassesInSignature(true).each {
            inatClass ->
            String label = getLabel(inatOnt, inatClass)
            String norm = normalize(label)
            
            if (norm && baseIndex.containsKey(norm)) {
                List<OWLClass> matches = baseIndex[norm]
                OWLClass target = null
                
                if (matches.size() == 1) {
                    target = matches[0]
                } else {
                    // Disambiguate by Rank
                    String inatRank = getRank(inatOnt, inatClass.getIRI(), false)
                    String normInatRank = normalizeRank(inatRank)
                    
                    for (OWLClass candidate : matches) {
                        String baseRank = getRank(baseOnt, candidate.getIRI(), true) // Treat base as 'source' style usually? Or mixed.
                        if (normalizeRank(baseRank) == normInatRank) {
                            target = candidate
                            break
                        }
                    }
                    if (target) disambiguatedCount++
                    else failedDisambiguationCount++
                }
                
                if (target) {
                    def ax = df.getOWLEquivalentClassesAxiom(inatClass, target)
                    manager.addAxiom(finalOnt, ax)
                    anchorCount++
                }
            }
        }
        
        // Step B: Grafting
        // Since we copied all axioms from inatOnt, the 'Graft' is implicit.
        // Unanchored nodes retain their subClassOf relationships to their parents.
        // If the parent is anchored (Equivalent to Base), the child is effectively grafted.
        
        println "Saving Final Ecosystem to $outputPath..."
        manager.saveOntology(finalOnt, new FunctionalSyntaxDocumentFormat(), IRI.create(new File(outputPath).toURI()))
        
        println "\n=== Graft Statistics ==="
        println "Total Anchors Created: $anchorCount"
        println "  - Direct/Single Matches: ${anchorCount - disambiguatedCount}"
        println "  - Disambiguated (Rank): $disambiguatedCount"
        println "  - Failed Disambiguation (Homonyms ignored): $failedDisambiguationCount"
    }

    // --- Helpers ---

    String normalize(String label) {
        if (!label) return ""
        String s = label.trim().toLowerCase()
        s = s.replaceAll(/^[dpcofgs]__/, "")
        s = s.replaceAll(/_[a-z0-9]+$/, "") 
        s = s.replaceAll(/^candidatus\s+/, "")
        s = s.replaceAll(/^ca\.\s+/, "")
        return s.trim()
    }
    
    String getLabel(OWLOntology ont, OWLClass cls) {
        String label = null
        EntitySearcher.getAnnotations(cls, ont).each {
            ann ->
            if (ann.getProperty().isLabel() && ann.getValue().isLiteral()) {
                label = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        return label
    }

    String getRank(OWLOntology ont, IRI iri, boolean checkSubclasses) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        String rank = null
        
        // 1. Annotation
        EntitySearcher.getAnnotations(cls, ont).each {
            ann ->
            def propStr = ann.getProperty().getIRI().toString()
            if (isRankProperty(propStr) && ann.getValue().isLiteral()) {
                rank = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        if (rank) return rank

        // 2. GTDB Prefix (Label-based)
        String label = getLabel(ont, cls)
        if (label) {
            if (label.startsWith("d__")) return "domain"
            if (label.startsWith("p__")) return "phylum"
            if (label.startsWith("c__")) return "class"
            if (label.startsWith("o__")) return "order"
            if (label.startsWith("f__")) return "family"
            if (label.startsWith("g__")) return "genus"
            if (label.startsWith("s__")) return "species"
        }

        // 3. NCBI Subclass check (Expensive, use sparingly)
        if (checkSubclasses && rank == null) {
             EntitySearcher.getSuperClasses(cls, ont).each {
                 ce ->
                 if (!ce.isAnonymous()) {
                     def sIRI = ce.asOWLClass().getIRI().toString()
                     if (NCBI_RANK_CLASSES.containsKey(sIRI)) {
                         rank = NCBI_RANK_CLASSES[sIRI]
                     }
                 }
             }
        }
        return rank
    }
    
    boolean isRankProperty(String propIri) {
        if (RANK_PROPS.contains(propIri)) return true
        if (propIri.toLowerCase().endsWith("rank") || propIri.contains("has_rank")) return true
        return false
    }

    String normalizeRank(String r) {
        if (r == null) return "unknown"
        String n = r.trim().toLowerCase()
        if (n == "superkingdom") return "domain"
        if (n == "kingdom") return "domain"
        return n
    }
}
