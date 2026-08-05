// scripts/validation/ShexValidate.java
//
// Standalone ShEx validation entry-point. Run via:
//   java --source 21 -cp <jena-shex-jars> ShexValidate.java \
//        <graph> <shapes.shex> <shapeMap.shexmap> [--list]
//
// The reason we don't call ShExValidator from the Groovy side: Groovy 2.4's
// internal ASM 5 bytecode generator chokes on the call-site classes it needs
// to synthesize for Jena 4.10's API surface (Java 11+ bytecode features —
// invokedynamic + modern lambdas — produce an "Illegal type in constant pool"
// VerifyError). Running ShEx in a fresh JVM, invoked by Groovy via
// ProcessBuilder, sidesteps the call-site machinery entirely.
//
// Args:
//   <graph>        Path to RDF file (or a file-of-paths if --list given)
//   <shapes>       Path to ShEx schema
//   <shapeMap>     Path to ShEx shape map
//   --list         (optional) Treat <graph> as a list of RDF file paths,
//                  one per line, and merge them into one model.
//
// Output:
//   stdout begins with one of "CONFORM", "FAIL", or "ERROR ..."
//   on FAIL, follow-up lines describe the report
//
// Exit codes:
//   0 = conform, 1 = non-conform, 2 = error

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

import org.apache.jena.graph.Graph;
import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.shex.ShapeMap;
import org.apache.jena.shex.Shex;
import org.apache.jena.shex.ShexReport;
import org.apache.jena.shex.ShexSchema;
import org.apache.jena.shex.ShexValidator;
import org.apache.jena.shex.sys.ShexLib;

public class ShexValidate {
    public static void main(String[] args) {
        try {
            if (args.length < 3) {
                System.out.println("ERROR usage: ShexValidate <graph> <shapes> <shapeMap> [--list]");
                System.exit(2);
            }
            String graphPath = args[0];
            String shapesPath = args[1];
            String shapeMapPath = args[2];
            boolean listMode = args.length >= 4 && "--list".equals(args[3]);

            Graph graph;
            if (listMode) {
                List<String> paths = Files.readAllLines(Paths.get(graphPath));
                Model model = ModelFactory.createDefaultModel();
                for (String p : paths) {
                    p = p.trim();
                    if (p.isEmpty() || p.startsWith("#")) continue;
                    try {
                        RDFDataMgr.read(model, p);
                    } catch (Exception e) {
                        System.out.println("WARN load " + p + ": " + e.getMessage());
                    }
                }
                graph = model.getGraph();
            } else {
                graph = RDFDataMgr.loadGraph(graphPath);
            }

            ShexSchema shapes = Shex.readSchema(shapesPath);
            ShapeMap shapeMap = Shex.readShapeMap(shapeMapPath);
            ShexReport report = ShexValidator.get().validate(graph, shapes, shapeMap);

            if (report.conforms()) {
                System.out.println("CONFORM");
                System.exit(0);
            }
            System.out.println("FAIL");
            // Use Jena's built-in printer for the violation details.
            ShexLib.printReport(System.out, report);
            System.exit(1);
        } catch (Throwable t) {
            System.out.println("ERROR " + t.getClass().getSimpleName() + ": " + t.getMessage());
            t.printStackTrace(System.out);
            System.exit(2);
        }
    }
}
