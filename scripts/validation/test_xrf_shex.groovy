@Grab(group='org.apache.jena', module='jena-shex', version='4.10.0')
@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.shex.*
import org.apache.jena.shex.sys.ShexLib
import org.apache.jena.riot.RDFDataMgr
import org.apache.jena.graph.Graph
import org.apache.jena.graph.NodeFactory
import java.io.File

def dataFile = "data/processed/semantics/ontology/rubalkhali_xrf.owl"
def shexFile = "data/processed/semantics/shex/xrf.shex"

Graph graph = RDFDataMgr.loadGraph(new File(dataFile).absolutePath)
ShexSchema shapes = Shex.readSchema(new File(shexFile).absolutePath)

def shapesToValidate = [
    "https://rubalkhali.science/kb/RAK_0000025": "XRFProcessShape",
    "https://rubalkhali.science/kb/RAK_0000030": "XRFValueShape",
    "https://rubalkhali.science/kb/RAK_0000029": "XRFQualityShape"
]

shapesToValidate.each { typeUri, shapeName ->
    println "Validating ${shapeName}..."
    def typeNode = NodeFactory.createURI(typeUri)
    def shapeUri = new File(shexFile).toURI().toString() + "#" + shapeName
    def iter = graph.find(null, NodeFactory.createURI("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), typeNode)
    
    List<String> mapEntries = []
    int count = 0
    while(iter.hasNext() && count < 5) {
        mapEntries << "<${iter.next().getSubject().getURI()}>@<${shapeUri}>"
        count++
    }
    
    if (!mapEntries.isEmpty()) {
        File tempMapFile = File.createTempFile("shapemap", ".shexmap")
        tempMapFile.text = mapEntries.join(",\n")
        ShapeMap shapeMap = Shex.readShapeMap(tempMapFile.absolutePath)
        ShexReport report = ShexValidator.get().validate(graph, shapes, shapeMap)
        if (!report.conforms()) {
            println "FAILURE: ${shapeName} does not conform"
            ShexLib.printReport(report)
        } else {
            println "SUCCESS: ${shapeName} conforms"
        }
        tempMapFile.delete()
    }
}