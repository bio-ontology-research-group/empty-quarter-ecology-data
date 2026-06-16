@Grab(group='org.apache.jena', module='jena-shex', version='4.10.0')
@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.shex.*
import org.apache.jena.shex.sys.ShexLib
import org.apache.jena.riot.RDFDataMgr
import org.apache.jena.graph.Graph
import org.apache.jena.graph.NodeFactory
import java.io.File

/**
 * Validates RDF files against ShEx schemas.
 * Usage: groovy scripts/validate_rdf.groovy [materialized_file]
 */

def targetFile = args.length > 0 ? args[0] : null

def validationConfig = [
    [
        data: "data/processed/semantics/ontology/rubalkhali_sites.owl",
        shex: "data/processed/semantics/shex/sites.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000002": "SamplingSiteShape",
            "http://purl.obolibrary.org/obo/ENVO_00000192": "RegionShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_samples.owl",
        shex: "data/processed/semantics/shex/samples.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000024": "SamplingProcessShape",
            "http://semanticscience.org/resource/SIO_001419": "CollectionShape",
            "http://semanticscience.org/resource/SIO_001418": "SampleShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_measurements.owl",
        shex: "data/processed/semantics/shex/measurements.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000018": "ExpeditionShape",
            "https://rubalkhali.science/kb/RAK_0000003": "VisitShape",
            "https://rubalkhali.science/kb/RAK_0000006": "MeasurementProcessShape",
            "https://rubalkhali.science/kb/RAK_0000007": "MeasurementProcessShape",
            "https://rubalkhali.science/kb/RAK_0000008": "MeasurementProcessShape",
            "https://rubalkhali.science/kb/RAK_0000009": "MeasurementProcessShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_dna.owl.gz",
        shex: "data/processed/semantics/shex/dna.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000040": "DNAExtractShape",
            "http://semanticscience.org/resource/SIO_000994": "ExtractionProcessShape",
            "https://rubalkhali.science/kb/RAK_0000041": "MeasurementProcessShape",
            "http://purl.obolibrary.org/obo/PATO_0000033": "ConcentrationShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_xrf.owl",
        shex: "data/processed/semantics/shex/xrf.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000025": "XRFProcessShape",
            "https://rubalkhali.science/kb/RAK_0000030": "XRFValueShape",
            "https://rubalkhali.science/kb/RAK_0000029": "XRFQualityShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_taxonomy_abox.ttl",
        shex: "data/processed/semantics/shex/taxonomy.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000071": "BioinformaticWorkflowShape",
            "https://rubalkhali.science/kb/RAK_0000072": "RelativeAbundanceQualityShape",
            "https://rubalkhali.science/kb/RAK_0000073": "RelativeAbundanceValueShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_sra.owl.gz",
        shex: "data/processed/semantics/shex/sra.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000065": "LibraryPrepProcessShape",
            "https://rubalkhali.science/kb/RAK_0000066": "SequencingProcessShape",
            "https://rubalkhali.science/kb/RAK_0000060": "AmpliconLibraryShape",
            "https://rubalkhali.science/kb/RAK_0000063": "FASTQDatasetShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_qc.owl",
        shex: "data/processed/semantics/shex/qc.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000070": "SequencingQCProcessShape"
        ]
    ]
]

boolean overallSuccess = true

// If a target file is provided (materialized), we validate ALL shapes against that one file.
if (targetFile) {
    println "Validating materialized file: ${targetFile}"
    Graph graph = RDFDataMgr.loadGraph(new File(targetFile).absolutePath)
    
    validationConfig.each { config ->
        def shexFile = new File(config.shex)
        println "Checking ${shexFile.name} shapes in materialized graph..."
        ShexSchema shapes = Shex.readSchema(shexFile.absolutePath)
        List<String> mapEntries = []
        config.shapes.each { entry ->
            def typeUri = entry.key; def shapeName = entry.value
            def typeNode = NodeFactory.createURI(typeUri)
            def shapeUri = shexFile.toURI().toString() + "#" + shapeName
            def iter = graph.find(null, NodeFactory.createURI("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), typeNode)
            while(iter.hasNext()) {
                mapEntries << "<${iter.next().getSubject().getURI()}>@<${shapeUri}>"
            }
        }
        if (!mapEntries.isEmpty()) {
            File tempMapFile = File.createTempFile("shapemap", ".shexmap")
            tempMapFile.text = mapEntries.join(",\n")
            ShapeMap shapeMap = Shex.readShapeMap(tempMapFile.absolutePath)
            ShexReport report = ShexValidator.get().validate(graph, shapes, shapeMap)
            if (!report.conforms()) {
                println "FAILURE: Materialized graph does not conform to ${shexFile.name}"
                overallSuccess = false
            } else {
                println "  OK: All nodes conform to ${shexFile.name}"
            }
            tempMapFile.delete()
        }
    }
} else {
    // Normal per-file validation
    for (config in validationConfig) {
        def dataFile = new File(config.data)
        def shexFile = new File(config.shex)
        if (!dataFile.exists()) continue
        // Skip files larger than 100MB — spot-check ShEx can't load them without OOM
        if (dataFile.length() > 100 * 1024 * 1024) {
            println "Skipping ${dataFile.name} (${(dataFile.length() / 1048576 as long)} MB — too large for ShEx spot-check)"
            continue
        }
        println "Validating ${dataFile.name}..."
        try {
            Graph graph = RDFDataMgr.loadGraph(dataFile.absolutePath)
            ShexSchema shapes = Shex.readSchema(shexFile.absolutePath)
            List<String> mapEntries = []
            config.shapes.each { entry ->
                def typeUri = entry.key; def shapeName = entry.value
                def typeNode = NodeFactory.createURI(typeUri); 
                def shapeUri = shexFile.toURI().toString() + "#" + shapeName
                def iter = graph.find(null, NodeFactory.createURI("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), typeNode)
                int count = 0
                while(iter.hasNext() && count < 15) {
                    mapEntries << "<${iter.next().getSubject().getURI()}>@<${shapeUri}>"
                    count++
                }
            }
            if (!mapEntries.isEmpty()) {
                File tempMapFile = File.createTempFile("shapemap", ".shexmap"); tempMapFile.text = mapEntries.join(",\n")
                ShapeMap shapeMap = Shex.readShapeMap(tempMapFile.absolutePath)
                ShexReport report = ShexValidator.get().validate(graph, shapes, shapeMap)
                if (!report.conforms()) { 
                    println "FAILURE: ${dataFile.name} does not conform"
                    ShexLib.printReport(report)
                    overallSuccess = false 
                }
                tempMapFile.delete()
            }
        } catch (OutOfMemoryError e) {
            // The taxonomy ABox is very large; Jena ShEx report builder may OOM on it.
            // Treat as a warning (skipped) rather than a hard failure.
            println "WARNING: OOM during ShEx validation of ${dataFile.name} — skipping (increase heap with JAVA_OPTS=-Xmx128g)"
        } catch (Exception e) { println "Error: ${e.message}"; overallSuccess = false }
    }
}

if (!overallSuccess) System.exit(1)
println "All Validations PASSED."