@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')
@Grab(group='commons-cli', module='commons-cli', version='1.5.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.semanticweb.owlapi.formats.FunctionalSyntaxDocumentFormat
import org.semanticweb.owlapi.reasoner.structural.StructuralReasonerFactory
import org.apache.commons.csv.CSVFormat
import org.apache.commons.csv.CSVParser
import groovy.cli.commons.CliBuilder
import java.nio.file.Files
import java.nio.file.Paths

class MergeTaxonomies {

    // known rank properties
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
        def cli = new CliBuilder(usage: 'groovy MergeTaxonomies.groovy -source <path> -target <path> -anchors <path> -hints <path> -output <path>')
        cli.source(args: 1, required: true, 'Path to source ontology')
        cli.target(args: 1, required: true, 'Path to target ontology')
        cli.anchors(args: 1, required: true, 'Path to verified_anchors.csv')
        cli.hints(args: 1, required: true, 'Path to parent_hints.csv')
        cli.output(args: 1, required: true, 'Path to output merged ontology')
        
        def options = cli.parse(args)
        if (!options) return

        new MergeTaxonomies().run(options.source, options.target, options.anchors, options.hints, options.output)
    }

    void run(String sourcePath, String targetPath, String anchorsPath, String hintsPath, String outputPath) {
        println "Initializing Manager..."
        def manager = OWLManager.createOWLOntologyManager()
        def dataFactory = manager.getOWLDataFactory()

        // 1. Load Ontologies
        println "Loading Source: $sourcePath"
        def sourceOnt = manager.loadOntologyFromOntologyDocument(new File(sourcePath))
        
        println "Loading Target: $targetPath"
        def targetOnt = manager.loadOntologyFromOntologyDocument(new File(targetPath))

        // 2. Merge Axioms (Phase 1)
        println "Merging axioms..."
        def mergedOnt = manager.createOntology(IRI.create("http://merged.taxonomy.org/merged"))
        
        [sourceOnt, targetOnt].each { ont ->
            manager.addAxioms(mergedOnt, ont.getAxioms())
        }
        println "Merged Ontology contains ${mergedOnt.getAxiomCount()} axioms."

        Set<IRI> mergedIRIs = new HashSet<>()

        // 3. Apply Leaf Anchors (Phase 2)
        println "Applying Leaf Anchors from $anchorsPath..."
        int anchorCount = 0
        Files.newBufferedReader(Paths.get(anchorsPath)).withCloseable { reader ->
            CSVParser parser = new CSVParser(reader, CSVFormat.DEFAULT.withFirstRecordAsHeader())
            parser.each { record ->
                def row = record.toMap()
                def sIRI = IRI.create(row.source_iri)
                def tIRI = IRI.create(row.target_iri)
                
                def sClass = dataFactory.getOWLClass(sIRI)
                def tClass = dataFactory.getOWLClass(tIRI)
                
                def ax = dataFactory.getOWLEquivalentClassesAxiom(sClass, tClass)
                manager.addAxiom(mergedOnt, ax)
                anchorCount++
                mergedIRIs.add(sIRI)
                mergedIRIs.add(tIRI)
            }
        }
        
        // 4. Lexical Backbone Merge (Phase 3)
        println "Performing Lexical Backbone Merge..."
        int backboneMerges = 0
        
        // Build Index for Source
        def sourceIndex = [:].withDefault { [] }
        sourceOnt.getClassesInSignature(true).each { cls ->
             // Skip if already merged
             if (!mergedIRIs.contains(cls.getIRI())) {
                 String label = getLabel(sourceOnt, cls)
                 String norm = normalize(label)
                 if (norm) {
                     sourceIndex[norm] << cls
                     if (norm == "bacteria") println "Debug: Found Bacteria in Source: ${cls.getIRI()} (Rank: ${getRank(sourceOnt, cls.getIRI(), true)})"
                 }
             }
        }
        
        // Check Target
        targetOnt.getClassesInSignature(true).each { tClass ->
             if (!mergedIRIs.contains(tClass.getIRI())) {
                 String label = getLabel(targetOnt, tClass)
                 String norm = normalize(label)
                 if (norm == "bacteria") println "Debug: Found Bacteria in Target: ${tClass.getIRI()} (Rank: ${getRank(targetOnt, tClass.getIRI(), false)})"
                 if (norm && sourceIndex.containsKey(norm)) {
                     def sClasses = sourceIndex[norm]
                     sClasses.each { sClass ->
                         // Check Ranks
                         String sRank = getRank(sourceOnt, sClass.getIRI(), true)
                         String tRank = getRank(targetOnt, tClass.getIRI(), false)
                         
                         String r1 = normalizeRank(sRank)
                         String r2 = normalizeRank(tRank)

                         // Debug specific taxa
                         if (norm == "bacteria" || norm == "proteobacteria") {
                             println "Debug: Comparing ${norm} -> Rank S: ${r1} vs Rank T: ${r2}"
                         }
                         
                         // Merge if ranks match OR if both are not species (high-level backbone merge)
                         if (r1 == r2 || (r1 != "species" && r2 != "species")) {
                             // Match! Merge.
                             def ax = dataFactory.getOWLEquivalentClassesAxiom(sClass, tClass)
                             manager.addAxiom(mergedOnt, ax)
                             backboneMerges++
                             mergedIRIs.add(sClass.getIRI())
                             mergedIRIs.add(tClass.getIRI())
                         }
                     }
                 }
             }
        }
        
        // 5. Apply Parent Hints / Structural Merges (Phase 4)
        println "Applying Structural Hints (Votes >= 1)..."
        Map<String, Integer> voteCounts = [:] 
        
        Files.newBufferedReader(Paths.get(hintsPath)).withCloseable { reader ->
            CSVParser parser = new CSVParser(reader, CSVFormat.DEFAULT.withFirstRecordAsHeader())
            parser.each { record ->
                def sIRI = record.get("source_parent_iri")
                def tIRI = record.get("target_parent_iri")
                def countStr = record.get("evidence_count")
                int count = countStr ? countStr.toInteger() : 1
                
                String key = "${sIRI}|${tIRI}"
                voteCounts[key] = voteCounts.getOrDefault(key, 0) + count
            }
        }

        int structureMerges = 0
        voteCounts.each {
            key, count ->
            if (count >= 1) { // Lower threshold per instructions
                def parts = key.split("\\|")
                def sIRI = IRI.create(parts[0])
                def tIRI = IRI.create(parts[1])
                
                // Only merge if not already merged in backbone phase
                if (!mergedIRIs.contains(sIRI) && !mergedIRIs.contains(tIRI)) {
                    def sClass = dataFactory.getOWLClass(sIRI)
                    def tClass = dataFactory.getOWLClass(tIRI)
                    
                    def ax = dataFactory.getOWLEquivalentClassesAxiom(sClass, tClass)
                    manager.addAxiom(mergedOnt, ax)
                    structureMerges++
                    mergedIRIs.add(sIRI)
                    mergedIRIs.add(tIRI)
                }
            }
        }

        // 6. Sensu Disambiguation (Phase 5)
        println "Disambiguating Homonyms (Sensu)..."
        def reasonerFactory = new StructuralReasonerFactory()
        def reasoner = reasonerFactory.createReasoner(mergedOnt)
        
        Map<String, Set<OWLClass>> labelMap = [: ]
        
        mergedOnt.getClassesInSignature(true).each { cls ->
            getLabels(mergedOnt, cls).each { label ->
                def norm = normalize(label)
                if (norm) {
                    labelMap.computeIfAbsent(norm, k -> new HashSet<>()).add(cls)
                }
            }
        }
        
        int sensuRenamed = 0
        
        labelMap.each {
            label, classes ->
            if (classes.size() > 1) {
                boolean allEquivalent = true
                def classList = classes.toList()
                def first = classList[0]
                
                for (int i = 1; i < classList.size(); i++) {
                    if (!reasoner.getEquivalentClasses(first).contains(classList[i])) {
                        allEquivalent = false
                        break
                    }
                }
                
                if (!allEquivalent) {
                    classes.each { cls ->
                        String iriStr = cls.getIRI().toString()
                        String context = "Unknown"
                        if (iriStr.contains("NCBITaxon")) context = "NCBI"
                        else if (iriStr.contains("gtdb")) context = "GTDB"
                        else if (iriStr.contains("ncbitaxon")) context = "NCBI"
                        
                        if (context != "Unknown") {
                            def axiomsToRemove = new HashSet<OWLAnnotationAssertionAxiom>()
                            EntitySearcher.getAnnotationAssertionAxioms(cls, mergedOnt).each { ax ->
                                if (ax.getProperty().isLabel() && ax.getValue().isLiteral()) {
                                    def lit = ax.getValue().asLiteral().get().getLiteral()
                                    if (normalize(lit) == label) {
                                        axiomsToRemove.add(ax)
                                    }
                                }
                            }
                            manager.removeAxioms(mergedOnt, axiomsToRemove)
                            
                            String originalText = axiomsToRemove ? axiomsToRemove.first().getValue().asLiteral().get().getLiteral() : label
                            String newLabel = "${originalText} (sensu ${context})"
                            
                            def ann = dataFactory.getOWLAnnotation(dataFactory.getRDFSLabel(), dataFactory.getOWLLiteral(newLabel))
                            def ax = dataFactory.getOWLAnnotationAssertionAxiom(cls.getIRI(), ann)
                            manager.addAxiom(mergedOnt, ax)
                            
                            sensuRenamed++
                        }
                    }
                }
            }
        }

        // Output
        println "Saving Merged Ontology to $outputPath..."
        manager.saveOntology(mergedOnt, new FunctionalSyntaxDocumentFormat(), IRI.create(new File(outputPath).toURI()))

        println "\n=== Merge Statistics ==="
        println "Anchors Applied: $anchorCount"
        println "Backbone Classes Merged (Lexical): $backboneMerges"
        println "Renamed Moves (Child Evidence): $structureMerges"
        println "Ambiguous Taxa Renamed (Sensu): $sensuRenamed"
    }

    // Helpers
    
    Set<String> getLabels(OWLOntology ont, OWLClass cls) {
        def labels = new HashSet<String>()
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            if (ann.getProperty().isLabel() && ann.getValue().isLiteral()) {
                labels.add(ann.getValue().asLiteral().get().getLiteral())
            }
        }
        return labels
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

    String normalize(String label) {
        if (!label) return ""
        String s = label.trim().toLowerCase()
        s = s.replaceAll(/^[dpcofgs]__/, "")
        s = s.replaceAll(/_[a-z0-9]+$/, "") 
        s = s.replaceAll(/^candidatus\s+/, "")
        s = s.replaceAll(/^ca\.\s+/, "")
        return s.trim()
    }
    
    String getRank(OWLOntology ont, IRI iri, boolean isSource) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        String rank = null
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            def propStr = ann.getProperty().getIRI().toString()
            if (isRankProperty(propStr) && ann.getValue().isLiteral()) {
                rank = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        if (rank) return rank

        if (!isSource || rank == null) {
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
        }

        if (isSource && rank == null) {
             EntitySearcher.getSuperClasses(cls, ont).each { ce ->
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
