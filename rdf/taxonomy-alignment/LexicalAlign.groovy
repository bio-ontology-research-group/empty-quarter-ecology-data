@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')
@Grab(group='commons-cli', module='commons-cli', version='1.5.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.apache.commons.csv.CSVFormat
import org.apache.commons.csv.CSVPrinter
import groovy.cli.commons.CliBuilder
import java.nio.file.Files
import java.nio.file.Paths
import java.util.regex.Pattern

class LexicalAlign {

    static void main(String[] args) {
        def cli = new CliBuilder(usage: 'groovy LexicalAlign.groovy -source <path> -target <path>')
        cli.source(args: 1, 'Path to source ontology')
        cli.target(args: 1, 'Path to target ontology')
        
        def options = cli.parse(args)
        if (!options || !options.source || !options.target) {
            cli.usage()
            System.exit(1)
        }

        new LexicalAlign().run(options.source, options.target)
    }

    void run(String sourcePath, String targetPath) {
        println "Loading ontologies..."
        def manager = OWLManager.createOWLOntologyManager()
        
        // Load Source
        def sourceOnt = loadOntology(manager, sourcePath)
        println "Source loaded: ${sourceOnt.getOntologyID()}"
        
        // Load Target
        def targetOnt = loadOntology(manager, targetPath)
        println "Target loaded: ${targetOnt.getOntologyID()}"

        // Build Indices
        println "Building indices with normalization..."
        def sourceIndex = buildIndex(sourceOnt)
        def targetIndex = buildIndex(targetOnt)

        // Calculate Depths
        println "Calculating depths..."
        def sourceDepths = calculateDepths(sourceOnt)
        def targetDepths = calculateDepths(targetOnt)

        // Compare
        println "Comparing..."
        def matches = [] // List of [sourceIRI, targetIRI, matchString, sourceDepth, targetDepth, matchType]
        def sourceMatchedIRIs = new HashSet<IRI>()
        def targetMatchedIRIs = new HashSet<IRI>()

        sourceIndex.each { label, sourceIRIs ->
            if (targetIndex.containsKey(label)) {
                def targetIRIs = targetIndex[label]
                sourceIRIs.each { sIRI ->
                    targetIRIs.each { tIRI ->
                        
                        String type = "Synonym"
                        if (isLabel(sourceOnt, sIRI, label) && isLabel(targetOnt, tIRI, label)) {
                            type = "Label"
                        } else if (isLabel(sourceOnt, sIRI, label) || isLabel(targetOnt, tIRI, label)) {
                             type = "Mixed"
                        }

                        matches << [
                            source_iri: sIRI,
                            target_iri: tIRI,
                            match_string: label,
                            source_depth: sourceDepths.getOrDefault(sIRI, 0),
                            target_depth: targetDepths.getOrDefault(tIRI, 0),
                            match_type: type
                        ]
                        sourceMatchedIRIs.add(sIRI)
                        targetMatchedIRIs.add(tIRI)
                    }
                }
            }
        }

        // Stats Calculation
        def sourceTotal = sourceDepths.size()
        def targetTotal = targetDepths.size()
        def matchCount = matches.size() // Total distinct pairings
        // Unique matched classes
        def sourceMatchedCount = sourceMatchedIRIs.size()
        def targetMatchedCount = targetMatchedIRIs.size()

        def avgDepthSourceMatch = avg(sourceMatchedIRIs.collect { sourceDepths[it] })
        def avgDepthSourceUnmatch = avg(sourceDepths.keySet().findAll { !sourceMatchedIRIs.contains(it) }.collect { sourceDepths[it] })

        def avgDepthTargetMatch = avg(targetMatchedIRIs.collect { targetDepths[it] })
        def avgDepthTargetUnmatch = avg(targetDepths.keySet().findAll { !targetMatchedIRIs.contains(it) }.collect { targetDepths[it] })

        // Console Output
        println "\n=== Lexical Alignment Statistics ==="
        System.out.format("%-25s | %-10s | %-10s%n", "Metric", "Source", "Target")
        println "-" * 55
        System.out.format("%-25s | %-10d | %-10d%n", "Total Classes", sourceTotal, targetTotal)
        System.out.format("%-25s | %-10d | %-10d%n", "Matched Classes (Unique)", sourceMatchedCount, targetMatchedCount)
        System.out.format("%-25s | %-9.1f%% | %-9.1f%%%n", "Match %", (sourceMatchedCount/sourceTotal)*100, (targetMatchedCount/targetTotal)*100)
        System.out.format("%-25s | %-10.2f | %-10.2f%n", "Avg Depth (Matched)", avgDepthSourceMatch, avgDepthTargetMatch)
        System.out.format("%-25s | %-10.2f | %-10.2f%n", "Avg Depth (Unmatched)", avgDepthSourceUnmatch, avgDepthTargetUnmatch)
        println "-" * 55
        println "Total Pairings: $matchCount"

        // CSV Output
        def csvPath = Paths.get("lexical_seed.csv")
        def writer = Files.newBufferedWriter(csvPath)
        def csvPrinter = new CSVPrinter(writer, CSVFormat.DEFAULT.withHeader("source_iri", "target_iri", "match_string", "source_depth", "target_depth", "match_type"))
        
        matches.each { m ->
            csvPrinter.printRecord(m.source_iri, m.target_iri, m.match_string, m.source_depth, m.target_depth, m.match_type)
        }
        csvPrinter.flush()
        csvPrinter.close()
        println "\nResults written to lexical_seed.csv"
    }

    OWLOntology loadOntology(OWLOntologyManager manager, String path) {
        return manager.loadOntologyFromOntologyDocument(new File(path))
    }

    String normalize(String label) {
        String s = label.trim().toLowerCase()
        
        // 1. Remove GTDB Rank Prefixes (d__, p__, c__, etc.)
        s = s.replaceAll(/^[dpcofgs]__/, "")
        
        // 2. NEW: Strip GTDB specific lineage suffixes
        s = s.replaceAll(/_[a-z0-9]+$/, "")
        
        // 3. Remove "Candidatus" variations
        s = s.replaceAll(/^candidatus\s+/, "")
        s = s.replaceAll(/^ca\.\s+/, "")
        
        return s.trim()
    }

    Map<String, Set<IRI>> buildIndex(OWLOntology ont) {
        def index = [:].withDefault { new HashSet() }
        def exactSynonym = "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"
        def relatedSynonym = "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym"

        ont.getClassesInSignature(true).each { cls ->
            EntitySearcher.getAnnotations(cls, ont).each { ann ->
                if (ann.getValue().isLiteral()) {
                    def val = ann.getValue().asLiteral().get().getLiteral()
                    def propStr = ann.getProperty().getIRI().toString()
                    
                    if (ann.getProperty().isLabel() || 
                        propStr == exactSynonym || 
                        propStr == relatedSynonym || 
                        propStr.endsWith("genbank_synonym") ||
                        propStr.endsWith("hasRelatedSynonym")) {
                        
                        index[normalize(val)].add(cls.getIRI())
                    }
                }
            }
        }
        return index
    }

    boolean isLabel(OWLOntology ont, IRI iri, String text) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        boolean match = false
        EntitySearcher.getAnnotations(cls, ont).each {
             ann ->
             if (ann.getProperty().isLabel() && ann.getValue().isLiteral()) {
                 if (normalize(ann.getValue().asLiteral().get().getLiteral()) == text) {
                     match = true
                 }
             }
        }
        return match
    }

    Map<IRI, Integer> calculateDepths(OWLOntology ont) {
        def depths = [: ]
        def factory = ont.getOWLOntologyManager().getOWLDataFactory()
        
        ont.getClassesInSignature(true).each {
            cls ->
            depths[cls.getIRI()] = getDepth(cls, ont, new HashSet())
        }
        return depths
    }

    int getDepth(OWLClass cls, OWLOntology ont, Set<OWLClass> visited) {
        if (cls.isOWLThing()) return 0
        if (visited.contains(cls)) return -1 
        visited.add(cls)

        def supers = EntitySearcher.getSuperClasses(cls, ont).collect { it }
        def namedSupers = supers.findAll { !it.isAnonymous() }.collect { it.asOWLClass() }
        
        if (namedSupers.isEmpty()) return 0 

        int maxParentDepth = -1
        namedSupers.each {
            parent ->
             int d = getDepth(parent, ont, new HashSet(visited))
             if (d > maxParentDepth) maxParentDepth = d
        }
        
        return maxParentDepth + 1
    }

    double avg(List<Integer> values) {
        if (!values) return 0.0
        return values.sum() / values.size()
    }
}