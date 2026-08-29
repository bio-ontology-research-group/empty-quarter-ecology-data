/**
 * Negative ShEx fixtures for the released shapes.
 *
 * `tests/measurement_pattern/run_tests.groovy` proves the canonical
 * measurement pattern against a self-contained toy schema.  This suite is the
 * complement declared in NEXT_ANALYSES_AND_SUBMISSION_ITEMS.md item 6: it runs
 * the *released* shapes in `data/processed/semantics/shex/` against small
 * hand-built graphs and requires each declared defect to be rejected.
 *
 * Covered defects: missing coordinates, invalid datatypes, missing process
 * inputs, reversed measurement links, wrong control stage, and missing
 * control-specification provenance. Each negative fixture differs from its
 * positive counterpart in exactly one respect, so a passing negative test
 * localises the constraint that caught it.
 *
 * Exits 0 when every positive fixture conforms and every negative fixture is
 * rejected, 1 otherwise.  Needs java and the Jena ShEx classpath primed by
 * scripts/validation/shexvalidate.sh; no docker or Virtuoso.
 */

def FIXTURES = new File("tests/shex_negatives")
def SHAPES = new File("data/processed/semantics/shex")
def SHIM = new File("scripts/validation/shexvalidate.sh")
def RAK = "https://rubalkhali.science/kb/"

def MEASUREMENT_TARGETS = [
    [node: RAK + "P000001", shape: "MeasurementProcessShape"],
    [node: RAK + "V4000001", shape: "MeasurementValueShape"],
    [node: RAK + "Q5000001", shape: "QualityShape"],
]
def XRF_TARGETS = [
    [node: RAK + "RAK_P300001", shape: "XRFProcessShape"],
    [node: RAK + "RAK_4300001", shape: "XRFValueShape"],
    [node: RAK + "RAK_5300001", shape: "XRFQualityShape"],
]
def CONTROL_TARGETS = [
    [node: RAK + "fixture_material", shape: "ControlMaterialShape"],
    [node: RAK + "fixture_extraction_role", shape: "AnyControlRoleShape"],
    [node: RAK + "fixture_extraction_role", shape: "ExtractionBlankRoleShape"],
    [node: RAK + "fixture_extraction_process", shape: "ExtractionProcessShape"],
    [node: RAK + "fixture_batch", shape: "LaboratoryBatchShape"],
    [node: RAK + "fixture_fastq", shape: "ControlFASTQShape"],
    [node: RAK + "fixture_specification", shape: "CompositionSpecificationShape"],
    [node: RAK + "fixture_expected_taxon_assertion", shape: "ControlAssertionShape"],
    [node: RAK + "fixture_expected_taxon_assertion", shape: "ExpectedTaxonAssertionShape"],
]

def CASES = [
    [
        name: "sampling site with coordinates",
        graph: "site_positive.ttl",
        shapes: "sites.shex",
        expect: "CONFORM",
        targets: [[node: RAK + "RAK_1099901", shape: "SamplingSiteShape"]],
    ],
    [
        name: "sampling site missing coordinates",
        graph: "negative_missing_coordinates.ttl",
        shapes: "sites.shex",
        expect: "REJECT",
        targets: [[node: RAK + "RAK_1099902", shape: "SamplingSiteShape"]],
    ],
    [
        name: "canonical climate measurement",
        graph: "positive.ttl",
        shapes: "measurements.shex",
        expect: "CONFORM",
        targets: MEASUREMENT_TARGETS,
    ],
    [
        name: "measurement payload with an invalid datatype",
        graph: "negative_invalid_datatype.ttl",
        shapes: "measurements.shex",
        expect: "REJECT",
        targets: MEASUREMENT_TARGETS,
    ],
    [
        name: "reversed measurement link (quality subject of SIO_000215)",
        graph: "negative_reversed_measurement_link.ttl",
        shapes: "measurements.shex",
        expect: "REJECT",
        targets: MEASUREMENT_TARGETS,
    ],
    [
        name: "laboratory XRF process with an input",
        graph: "xrf_positive.ttl",
        shapes: "xrf.shex",
        expect: "CONFORM",
        targets: XRF_TARGETS,
    ],
    [
        name: "XRF process missing both input and target",
        graph: "negative_missing_process_input.ttl",
        shapes: "xrf.shex",
        expect: "REJECT",
        targets: XRF_TARGETS,
    ],
    [
        name: "complete laboratory-control pattern",
        graph: "control_positive.ttl",
        shapes: "controls.shex",
        expect: "CONFORM",
        targets: CONTROL_TARGETS,
    ],
    [
        name: "extraction blank realized in a PCR process",
        graph: "control_negative_wrong_blank_stage.ttl",
        shapes: "controls.shex",
        expect: "REJECT",
        targets: [[node: RAK + "wrong_stage_role", shape: "ExtractionBlankRoleShape"]],
    ],
    [
        name: "expected-taxon assertion with source-less specification",
        graph: "control_negative_missing_specification_source.ttl",
        shapes: "controls.shex",
        expect: "REJECT",
        targets: [[
            node: RAK + "source_less_expected_taxon_assertion",
            shape: "ExpectedTaxonAssertionShape",
        ]],
    ],
]

println "============================================================"
println "  Released-shape negative fixtures"
println "============================================================"

SHIM.setExecutable(true)
def failures = []

CASES.each { testCase ->
    def graph = new File(FIXTURES, testCase.graph)
    def shapes = new File(SHAPES, testCase.shapes)
    if (!graph.exists()) {
        failures << "${testCase.name}: missing fixture ${graph}"
        return
    }
    def shapeUri = shapes.toURI().toString()
    def shapeMap = File.createTempFile("shexmap", ".shexmap")
    shapeMap.text = testCase.targets.collect {
        "<${it.node}>@<${shapeUri}#${it.shape}>"
    }.join(",\n")

    def process = [
        "bash",
        SHIM.absolutePath,
        graph.absolutePath,
        shapes.absolutePath,
        shapeMap.absolutePath,
    ].execute()
    def out = process.in.text
    def err = process.err.text
    process.waitFor()
    def code = process.exitValue()
    shapeMap.delete()

    if (code == 2) {
        failures << "${testCase.name}: validator error (exit 2): ${err.trim()}"
        println "  ❌ ${testCase.name} — validator error"
        return
    }
    def conformed = code == 0 && out.startsWith("CONFORM")
    def wanted = testCase.expect == "CONFORM"
    if (conformed == wanted) {
        println "  ✅ ${testCase.name} — ${testCase.expect}"
    } else {
        failures << (
            "${testCase.name}: expected ${testCase.expect}, "
            + "got ${conformed ? 'CONFORM' : 'REJECT'}"
        )
        println "  ❌ ${testCase.name} — expected ${testCase.expect}"
        println out
    }
}

println "\n============================================================"
if (failures) {
    println "  ${failures.size()} FAILURE(S)"
    failures.each { println "   - ${it}" }
    println "============================================================"
    System.exit(1)
}
println "  ALL ${CASES.size()} SHAPE FIXTURES BEHAVED AS DECLARED"
println "============================================================"
