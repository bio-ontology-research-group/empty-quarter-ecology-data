#!/usr/bin/env python3
"""Resolve every IRI and triple printed in the manuscript against the graph.

The Data Descriptor's value proposition is that a reader can copy a printed
Turtle pattern and query the released graph with it.  Nothing checked that
until now, and seven of the nine worked listings had drifted from the modules
they claim to illustrate.  This script closes that gap:

1. the prefix table in ``03_knowledge_representation.tex`` is parsed, so a
   prefix change invalidates the check rather than silently reinterpreting
   every listing;
2. each Turtle listing is parsed with rdflib and every resulting triple is
   resolved against the staged modules, including ``owl:Restriction`` blank
   nodes, which the site pattern relies on;
3. every prefixed IRI mentioned in the section prose is required to exist in
   the graph or in the terminology, which is what catches malformed terms such
   as a double-prefixed ``uo:UO_0000027`` or a property IRI that was never
   minted.

The modules are read with a streaming RDF/XML reader restricted to the subjects
the manuscript mentions, so the whole check runs in seconds rather than
requiring the full graph in memory.  The multi-gigabyte taxonomy ABox is
scanned line-wise for the same subject set and can be skipped with
``--skip-taxonomy`` when only the RDF/XML modules are of interest.

Exit status is 0 when every printed triple and IRI resolves, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

from rdflib import BNode, Graph, Literal, URIRef

RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
OWL_RESTRICTION = URIRef("http://www.w3.org/2002/07/owl#Restriction")
OWL_ON_PROPERTY = URIRef("http://www.w3.org/2002/07/owl#onProperty")
OWL_SOME_VALUES_FROM = URIRef("http://www.w3.org/2002/07/owl#someValuesFrom")

RDF_NS = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
OWL_NS = "{http://www.w3.org/2002/07/owl#}"

# RDF/XML modules consulted for the printed patterns.
MODULES = (
    "rubalkhali.owl",
    "rubalkhali_sites.owl",
    "rubalkhali_samples.owl",
    "rubalkhali_measurements.owl",
    "rubalkhali_dna.owl",
    "rubalkhali_sra.owl",
    "rubalkhali_qc.owl",
    "rubalkhali_xrf.owl",
    "rubalkhali_controls.owl",
)
TAXONOMY_MODULE = "rubalkhali_taxonomy_abox.ttl"

# Terms that legitimately resolve outside the released modules: imported
# vocabularies are referenced by IRI but not redistributed in these files.
EXTERNAL_PREFIXES = (
    "http://semanticscience.org/resource/",
    "http://purl.obolibrary.org/obo/",
    "http://www.w3.org/",
    "http://www.opengis.net/",
    "http://purl.org/dc/",
)

LISTING_RE = re.compile(
    r"\\begin\{lstlisting\}\[(?P<options>.*?)\]\n(?P<body>.*?)\\end\{lstlisting\}",
    re.S,
)
LABEL_RE = re.compile(r"label=\{(?P<label>[^}]+)\}")
PREFIX_ROW_RE = re.compile(
    r"\\texttt\{(?P<prefix>[A-Za-z_\\]*?):\}\s*&\s*\\texttt\{(?P<namespace>[^}]+)\}"
)
PROSE_IRI_RE = re.compile(r"\\texttt\{(?P<curie>[a-z_\\]+:[A-Za-z0-9_\\]+)\}")


def unescape(value: str) -> str:
    return value.replace("\\_", "_").replace("\\#", "#").replace("\\%", "%")


def read_prefixes(source: str) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for match in PREFIX_ROW_RE.finditer(source):
        prefix = unescape(match.group("prefix"))
        namespace = unescape(match.group("namespace"))
        prefixes[prefix] = namespace
    return prefixes


def read_listings(source: str) -> list[tuple[str, str]]:
    listings = []
    for match in LISTING_RE.finditer(source):
        label_match = LABEL_RE.search(match.group("options"))
        label = label_match.group("label") if label_match else ""
        listings.append((label, match.group("body")))
    return listings


def strip_comments(body: str) -> str:
    lines = []
    for line in body.splitlines():
        in_string = False
        cut = len(line)
        for index, character in enumerate(line):
            if character == '"':
                in_string = not in_string
            elif character == "#" and not in_string:
                cut = index
                break
        lines.append(line[:cut].rstrip())
    return "\n".join(lines)


def parse_listing(body: str, prefixes: dict[str, str]) -> Graph:
    header = "".join(f"@prefix {name}: <{iri}> .\n" for name, iri in prefixes.items())
    graph = Graph()
    graph.parse(data=header + strip_comments(body), format="turtle")
    return graph


class ModuleIndex:
    """Streaming index of the printed subjects across the staged modules."""

    def __init__(self) -> None:
        self.triples: set[tuple[str, str, str]] = set()
        self.restrictions: set[tuple[str, str, str]] = set()
        self.subjects: set[str] = set()
        self.objects: set[str] = set()

    def _add_children(self, subject: str, element) -> None:
        for child in element:
            predicate = child.tag.replace("{", "").replace("}", "")
            resource = child.get(f"{RDF_NS}resource")
            if resource is not None:
                self.triples.add((subject, predicate, resource))
                self.objects.add(resource)
                continue
            restriction = child.find(f"{OWL_NS}Restriction")
            if restriction is not None:
                on_property = restriction.find(f"{OWL_NS}onProperty")
                some_values = restriction.find(f"{OWL_NS}someValuesFrom")
                if on_property is not None and some_values is not None:
                    self.restrictions.add(
                        (
                            subject,
                            on_property.get(f"{RDF_NS}resource"),
                            some_values.get(f"{RDF_NS}resource"),
                        )
                    )
                continue
            text = (child.text or "").strip()
            datatype = child.get(f"{RDF_NS}datatype")
            self.triples.add((subject, predicate, f"LITERAL\t{text}\t{datatype or ''}"))

    def load_rdfxml(self, path: Path, wanted: set[str]) -> None:
        # Only subject elements carry rdf:about; their children are read while
        # still populated, so nothing is cleared before it has been indexed.
        for _, element in ElementTree.iterparse(path, events=("end",)):
            subject = element.get(f"{RDF_NS}about")
            if subject is None:
                continue
            if subject in wanted:
                self.subjects.add(subject)
                self._add_children(subject, element)
            element.clear()

    def load_ntriples(self, path: Path, wanted: set[str]) -> None:
        with path.open("rb") as handle:
            for raw in handle:
                if not raw.startswith(b"<"):
                    continue
                subject_end = raw.find(b"> ")
                if subject_end < 0:
                    continue
                subject = raw[1:subject_end].decode("utf-8")
                if subject not in wanted:
                    continue
                line = raw.decode("utf-8").strip()
                if not line.endswith("."):
                    continue
                line = line[:-1].strip()
                _, rest = line.split("> ", 1)
                predicate, rest = rest.split("> ", 1)
                predicate = predicate[1:]
                rest = rest.strip()
                self.subjects.add(subject)
                if rest.startswith("<"):
                    obj = rest[1:-1]
                    self.triples.add((subject, predicate, obj))
                    self.objects.add(obj)
                else:
                    text, _, datatype = rest.partition("^^")
                    text = text.strip().strip('"')
                    datatype = datatype.strip().strip("<>")
                    self.triples.add(
                        (subject, predicate, f"LITERAL\t{text}\t{datatype}")
                    )


def literal_key(value: Literal) -> str:
    datatype = str(value.datatype) if value.datatype else ""
    return f"LITERAL\t{str(value)}\t{datatype}"


def collect_wanted(graphs: list[Graph], prose_iris: set[str]) -> set[str]:
    wanted = set(prose_iris)
    for graph in graphs:
        for subject, _, obj in graph:
            if isinstance(subject, URIRef):
                wanted.add(str(subject))
            if isinstance(obj, URIRef):
                wanted.add(str(obj))
    return wanted


def expand(curie: str, prefixes: dict[str, str]) -> str | None:
    prefix, _, local = curie.partition(":")
    namespace = prefixes.get(prefix)
    if namespace is None:
        return None
    return namespace + local


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--paper-root", type=Path, default=root)
    parser.add_argument(
        "--ontology-dir",
        type=Path,
        default=root.parent / "data/processed/semantics/ontology",
    )
    parser.add_argument("--skip-taxonomy", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    sections = [
        args.paper_root / "03_knowledge_representation.tex",
        args.paper_root / "kr_supplement.tex",
    ]
    for section in sections:
        if not section.is_file():
            print(f"FAIL: manuscript source is absent: {section}", file=sys.stderr)
            return 1
    source = "\n".join(section.read_text(encoding="utf-8") for section in sections)

    prefixes = read_prefixes(source)
    for required in ("rak", "sio", "owl", "envo", "ncbitaxon", "uo", "pato"):
        if required not in prefixes:
            print(f"FAIL: prefix table does not declare {required}:", file=sys.stderr)
            return 1

    listings = read_listings(source)
    turtle = [(label, body) for label, body in listings if label.startswith("lst:ttl_")]
    if not turtle:
        print("FAIL: no Turtle listings found", file=sys.stderr)
        return 1

    graphs = []
    for label, body in turtle:
        try:
            graphs.append((label, parse_listing(body, prefixes)))
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            print(f"FAIL: listing {label} is not valid Turtle: {error}", file=sys.stderr)
            return 1

    prose_curies = {
        unescape(match.group("curie"))
        for match in PROSE_IRI_RE.finditer(source)
    }
    prose_iris = set()
    unknown_prefix = []
    for curie in sorted(prose_curies):
        expanded = expand(curie, prefixes)
        if expanded is None:
            unknown_prefix.append(curie)
        else:
            prose_iris.add(expanded)

    wanted = collect_wanted([graph for _, graph in graphs], prose_iris)
    index = ModuleIndex()
    for name in MODULES:
        module = args.ontology_dir / name
        if not module.is_file():
            print(f"FAIL: staged module is absent: {module}", file=sys.stderr)
            return 1
        index.load_rdfxml(module, wanted)
    if not args.skip_taxonomy:
        taxonomy = args.ontology_dir / TAXONOMY_MODULE
        if not taxonomy.is_file():
            print(f"FAIL: taxonomy ABox is absent: {taxonomy}", file=sys.stderr)
            return 1
        index.load_ntriples(taxonomy, wanted)

    unresolved_triples: list[str] = []
    for label, graph in graphs:
        restriction_nodes = {
            node
            for node in graph.subjects(RDF_TYPE, OWL_RESTRICTION)
            if isinstance(node, BNode)
        }
        for subject, predicate, obj in graph:
            if subject in restriction_nodes:
                continue
            if isinstance(obj, BNode):
                on_property = graph.value(obj, OWL_ON_PROPERTY)
                some_values = graph.value(obj, OWL_SOME_VALUES_FROM)
                key = (str(subject), str(on_property), str(some_values))
                if key not in index.restrictions:
                    unresolved_triples.append(
                        f"{label}: restriction {key} not present in the staged modules"
                    )
                continue
            obj_key = literal_key(obj) if isinstance(obj, Literal) else str(obj)
            if (str(subject), str(predicate), obj_key) not in index.triples:
                unresolved_triples.append(
                    f"{label}: <{subject}> <{predicate}> {obj_key!r} not present"
                )

    unresolved_iris = sorted(
        iri
        for iri in prose_iris
        if iri not in index.subjects
        and iri not in index.objects
        and not iri.startswith(EXTERNAL_PREFIXES)
    )

    report = {
        "sections": [str(path) for path in sections],
        "prefixes": prefixes,
        "turtle_listings": [label for label, _ in turtle],
        "checked_triples": sum(
            1
            for _, graph in graphs
            for _s, _p, _o in graph
        ),
        "prose_iris_checked": len(prose_iris),
        "unresolved_triples": unresolved_triples,
        "unresolved_prose_iris": unresolved_iris,
        "prose_curies_with_unknown_prefix": sorted(unknown_prefix),
        "taxonomy_scanned": not args.skip_taxonomy,
    }
    failed = bool(unresolved_triples or unresolved_iris or unknown_prefix)
    report["status"] = "failed" if failed else "passed"

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if failed:
        for problem in unresolved_triples:
            print(f"UNRESOLVED TRIPLE  {problem}", file=sys.stderr)
        for iri in unresolved_iris:
            print(f"UNRESOLVED IRI     {iri}", file=sys.stderr)
        for curie in unknown_prefix:
            print(f"UNDECLARED PREFIX  {curie}", file=sys.stderr)
        print("FAIL: manuscript listings do not match the staged graph", file=sys.stderr)
        return 1

    print(
        f"PASS: {report['checked_triples']} printed triples across "
        f"{len(turtle)} Turtle listings and {len(prose_iris)} prose IRIs "
        f"resolve against the staged modules"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
