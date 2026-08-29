@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.riot.RDFDataMgr
import org.apache.jena.graph.Graph
import org.apache.jena.graph.NodeFactory
import java.io.File

/**
 * Validates RDF files against ShEx schemas.
 * Usage: groovy scripts/validate_rdf.groovy [materialized_file]
 *
 * The actual ShEx call goes through scripts/validation/shexvalidate.sh
 * (a Java sub-process) — see ShexValidate.java for why.
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
        data: "data/processed/semantics/ontology/rubalkhali_dna.owl",
        shex: "data/processed/semantics/shex/dna.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000040": "DNAExtractShape",
            "https://rubalkhali.science/kb/RAK_0000309": "ExtractionProcessShape",
            "https://rubalkhali.science/kb/RAK_0000041": "MeasurementProcessShape",
            "https://rubalkhali.science/kb/RAK_0000043": "DNAConcentrationQualityShape",
            "https://rubalkhali.science/kb/RAK_0000044": "DNAConcentrationValueShape"
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
        data: "data/processed/semantics/ontology/rubalkhali_sra.owl",
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
            "https://rubalkhali.science/kb/RAK_0000200": "SequencingQCProcessShape"
        ]
    ],
    [
        data: "data/processed/semantics/ontology/rubalkhali_controls.ttl",
        shex: "data/processed/semantics/shex/controls.shex",
        shapes: [
            "https://rubalkhali.science/kb/RAK_0000300": "ControlMaterialShape",
            "https://rubalkhali.science/kb/RAK_0000304": "AnyControlRoleShape",
            "https://rubalkhali.science/kb/RAK_0000305": "AnyControlRoleShape",
            "https://rubalkhali.science/kb/RAK_0000306": "ExtractionBlankRoleShape",
            "https://rubalkhali.science/kb/RAK_0000307": "PCRBlankRoleShape",
            "https://rubalkhali.science/kb/RAK_0000309": "ExtractionProcessShape",
            "https://rubalkhali.science/kb/RAK_0000311": "PCRProcessShape",
            "https://rubalkhali.science/kb/RAK_0000308": "LaboratoryBatchShape",
            "https://rubalkhali.science/kb/RAK_0000318": "ControlFASTQShape",
            "https://rubalkhali.science/kb/RAK_0000313": "ControlAssertionShape",
            "https://rubalkhali.science/kb/RAK_0000320": "MetadataDispositionShape",
            "https://rubalkhali.science/kb/RAK_0000321": "MetadataDispositionShape",
            "https://rubalkhali.science/kb/RAK_0000316": "CompositionSpecificationShape",
            "https://rubalkhali.science/kb/RAK_0000317": "ExpectedTaxonAssertionShape"
        ],
        fullValidation: true
    ]
]

boolean overallSuccess = true

def shim = new File("scripts/validation/shexvalidate.sh").absolutePath
new File(shim).setExecutable(true)

/**
 * Run ShEx validation in an external JVM via the bash shim. Returns true
 * iff the report conforms.
 */
def runShex = { String graphPath, String shapesPath, List<String> mapEntries ->
    if (mapEntries.isEmpty()) return true
    File tempMap = File.createTempFile("shapemap", ".shexmap")
    tempMap.text = mapEntries.join(",\n")
    try {
        def proc = new ProcessBuilder(shim, graphPath, shapesPath, tempMap.absolutePath)
                .redirectErrorStream(true).start()
        def output = proc.inputStream.text
        int rc = proc.waitFor()
        if (rc == 0 && output.contains("CONFORM")) {
            return true
        }
        println "  ShEx output:"
        output.eachLine { println "    " + it }
        return false
    } finally {
        tempMap.delete()
    }
}

if (targetFile) {
    println "Validating materialized file: ${targetFile}"
    Graph graph = RDFDataMgr.loadGraph(new File(targetFile).absolutePath)

    validationConfig.each { config ->
        def shexFile = new File(config.shex)
        println "Checking ${shexFile.name} shapes in materialized graph..."
        List<String> mapEntries = []
        config.shapes.each { entry ->
            def typeUri = entry.key
            def shapeName = entry.value
            def typeNode = NodeFactory.createURI(typeUri)
            def shapeUri = shexFile.toURI().toString() + "#" + shapeName
            def iter = graph.find(null,
                NodeFactory.createURI("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                typeNode)
            while (iter.hasNext()) {
                mapEntries << "<${iter.next().getSubject().getURI()}>@<${shapeUri}>"
            }
        }
        if (!mapEntries.isEmpty()) {
            boolean ok = runShex(new File(targetFile).absolutePath, shexFile.absolutePath, mapEntries)
            if (ok) {
                println "  OK: All nodes conform to ${shexFile.name}"
            } else {
                println "FAILURE: Materialized graph does not conform to ${shexFile.name}"
                overallSuccess = false
            }
        }
    }
} else {
    // Per-file validation. Large legacy ABoxes are sampled, but compact
    // fail-closed modules such as laboratory controls validate every node.
    for (config in validationConfig) {
        def dataFile = new File(config.data)
        def shexFile = new File(config.shex)
        if (!dataFile.exists()) continue
        if (dataFile.length() > 100 * 1024 * 1024) {
            println "Skipping ${dataFile.name} (${(dataFile.length() / 1048576 as long)} MB — too large for ShEx spot-check)"
            continue
        }
        println "Validating ${dataFile.name}..."
        try {
            Graph graph = RDFDataMgr.loadGraph(dataFile.absolutePath)
            List<String> mapEntries = []
            config.shapes.each { entry ->
                def typeUri = entry.key
                def shapeName = entry.value
                def typeNode = NodeFactory.createURI(typeUri)
                def shapeUri = shexFile.toURI().toString() + "#" + shapeName
                def iter = graph.find(null,
                    NodeFactory.createURI("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                    typeNode)
                int count = 0
                int limit = config.get("fullValidation", false) ? Integer.MAX_VALUE : 15
                while (iter.hasNext() && count < limit) {
                    mapEntries << "<${iter.next().getSubject().getURI()}>@<${shapeUri}>"
                    count++
                }
            }
            if (!mapEntries.isEmpty()) {
                boolean ok = runShex(dataFile.absolutePath, shexFile.absolutePath, mapEntries)
                if (!ok) {
                    println "FAILURE: ${dataFile.name} does not conform"
                    overallSuccess = false
                }
            }
        } catch (Exception e) {
            println "Error: ${e.message}"
            overallSuccess = false
        }
    }
}

if (!overallSuccess) System.exit(1)
println "All Validations PASSED."
