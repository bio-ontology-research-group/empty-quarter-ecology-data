@Grab(group='org.apache.jena', module='jena-shex', version='4.10.0')
@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.shex.*
import org.apache.jena.shex.sys.ShexLib
import org.apache.jena.riot.RDFDataMgr
import org.apache.jena.graph.Graph
import org.apache.jena.graph.NodeFactory
import java.io.File

def dataFile = new File("data/processed/ontology/rubalkhali_measurements.owl")
def shexFile = new File("data/processed/shex/measurements.shex")
def shapeUri = shexFile.toURI().toString() + "#VisitShape"
def focusNodeUri = "https://rubalkhali.science/kb/RAK_3000069"

println "Validating Visit node ${focusNodeUri}..."

Graph graph = RDFDataMgr.loadGraph(dataFile.absolutePath)
ShexSchema shapes = Shex.readSchema(shexFile.absolutePath)

// Construct ShapeMap for single node
def shapeMapStr = "<${focusNodeUri}>@<${shapeUri}>"
File tempMapFile = File.createTempFile("shapemap", ".shexmap")
tempMapFile.text = shapeMapStr

ShapeMap shapeMap = Shex.readShapeMap(tempMapFile.absolutePath)
ShexReport report = ShexValidator.get().validate(graph, shapes, shapeMap)

ShexLib.printReport(report)

tempMapFile.delete()
