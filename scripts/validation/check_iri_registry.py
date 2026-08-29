#!/usr/bin/env python3
"""
Static IRI registry / collision detector for the Rub al-Khali generators.

Scans every Groovy and Python generator under scripts/rdf/ for RAK_ IRIs and
records:
  - which IRI is declared (defineClass / defineDataProp / defineObjectProp)
  - which IRI is referenced (OWL API getters or Python ``BASE.RAK_*`` access)
  - the literal label string passed to defineClass/defineDataProp/defineObjectProp.

Then reports failures for any of:
  1. Same IRI declared with different labels in two locations.
  2. Same IRI declared as both class AND property (kind mismatch).
  3. Same IRI used as a class in one file and as a property in another.
  4. IRI referenced (getOWLClass etc.) but never declared anywhere.

Exits 1 if any violation is found.

Run via:
    python3 scripts/validation/check_iri_registry.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field

REPO_ROOT = Path(__file__).resolve().parents[2]
GROOVY_DIR = REPO_ROOT / "scripts" / "rdf"

IRI_PATTERN = re.compile(r"\bRAK_[0-9A-Z]\d{6}\b")
DEFINE_CLASS = re.compile(r'defineClass\s*\(\s*"(RAK_\w+)"\s*,\s*"([^"]+)"')
DEFINE_DATA_PROP = re.compile(r'defineDataProp\s*\(\s*"(RAK_\w+)"\s*,\s*"([^"]+)"')
DEFINE_OBJECT_PROP = re.compile(r'defineObjectProp\s*\(\s*"(RAK_\w+)"\s*,\s*"([^"]+)"')

USE_CLASS = re.compile(
    r'getOWL(?:Class|AnnotationProperty)\s*\(\s*IRI\.create\s*\(\s*BASE\s*\+\s*"(RAK_\w+)"'
)
USE_DATA_PROP = re.compile(
    r'getOWLDataProperty\s*\(\s*IRI\.create\s*\(\s*BASE\s*\+\s*"(RAK_\w+)"'
)
USE_OBJECT_PROP = re.compile(
    r'getOWLObjectProperty\s*\(\s*IRI\.create\s*\(\s*BASE\s*\+\s*"(RAK_\w+)"'
)
USE_INDIVIDUAL = re.compile(
    r'getOWLNamedIndividual\s*\(\s*IRI\.create\s*\(\s*BASE\s*\+\s*"(RAK_\w+)"'
)
PYTHON_REFERENCE = re.compile(r"\bBASE\.(RAK_[02]\d{6})\b")


@dataclass
class Decl:
    iri: str
    label: str
    kind: str           # "class" | "data_prop" | "object_prop"
    file: str
    line: int


@dataclass
class Use:
    iri: str
    kind: str           # "class" | "data_prop" | "object_prop" | "individual"
    file: str
    line: int


@dataclass
class Registry:
    decls: list[Decl] = field(default_factory=list)
    uses: list[Use] = field(default_factory=list)


def scan(root: Path) -> Registry:
    reg = Registry()
    files = sorted(
        list(root.rglob("*.groovy")) + list(root.rglob("*.py"))
    )
    for f in files:
        rel = str(f.relative_to(REPO_ROOT))
        for line_no, line in enumerate(f.read_text().splitlines(), start=1):
            for pat, kind in (
                (DEFINE_CLASS, "class"),
                (DEFINE_DATA_PROP, "data_prop"),
                (DEFINE_OBJECT_PROP, "object_prop"),
            ):
                for m in pat.finditer(line):
                    reg.decls.append(Decl(m.group(1), m.group(2), kind, rel, line_no))
            for pat, kind in (
                (USE_CLASS, "class"),
                (USE_DATA_PROP, "data_prop"),
                (USE_OBJECT_PROP, "object_prop"),
                (USE_INDIVIDUAL, "individual"),
            ):
                for m in pat.finditer(line):
                    reg.uses.append(Use(m.group(1), kind, rel, line_no))
            if f.suffix == ".py":
                for m in PYTHON_REFERENCE.finditer(line):
                    reg.uses.append(
                        Use(m.group(1), "python_reference", rel, line_no)
                    )
    return reg


def report_violations(reg: Registry) -> list[str]:
    errors: list[str] = []

    decls_by_iri: dict[str, list[Decl]] = defaultdict(list)
    for d in reg.decls:
        decls_by_iri[d.iri].append(d)

    # 1. Conflicting labels for the same IRI
    for iri, decls in decls_by_iri.items():
        labels = {d.label for d in decls}
        if len(labels) > 1:
            locs = "; ".join(f"{d.file}:{d.line} -> '{d.label}'" for d in decls)
            errors.append(
                f"[label-conflict] {iri} declared with {len(labels)} different labels: {locs}"
            )

    # 2. Same IRI declared with different kinds (class vs property)
    for iri, decls in decls_by_iri.items():
        kinds = {d.kind for d in decls}
        if len(kinds) > 1:
            locs = "; ".join(f"{d.file}:{d.line} as {d.kind}" for d in decls)
            errors.append(f"[kind-conflict] {iri} declared as multiple kinds: {locs}")

    # 3. Use as a class in one file and as a property in another
    use_kinds_by_iri: dict[str, dict[str, list[Use]]] = defaultdict(lambda: defaultdict(list))
    for u in reg.uses:
        if u.kind in {"individual", "python_reference"}:
            continue
        use_kinds_by_iri[u.iri][u.kind].append(u)
    for iri, by_kind in use_kinds_by_iri.items():
        if len(by_kind) > 1:
            locs = []
            for kind, uses in by_kind.items():
                for u in uses:
                    locs.append(f"{u.file}:{u.line} as {kind}")
            errors.append(
                f"[use-kind-conflict] {iri} used as different kinds across scripts: {'; '.join(locs)}"
            )

    # 4. Used but never declared. Python references are deliberately
    # kind-neutral here because rdflib Namespace attribute access does not
    # distinguish classes from object/data properties.
    declared_iris = set(decls_by_iri.keys())
    use_undeclared: dict[str, list[Use]] = defaultdict(list)
    for u in reg.uses:
        if u.kind == "individual":
            continue
        if u.iri in declared_iris:
            continue
        use_undeclared[u.iri].append(u)
    for iri, uses in sorted(use_undeclared.items()):
        # Only flag class/property IRIs we expect to have TBox declarations.
        # (Anything starting with RAK_0 is a TBox class; RAK_2 is a property — both must be declared.)
        prefix = iri[:5] if len(iri) >= 5 else iri
        if not (iri.startswith("RAK_0") or iri.startswith("RAK_2")):
            continue
        locs = "; ".join(f"{u.file}:{u.line} ({u.kind})" for u in uses)
        errors.append(f"[undeclared] {iri} used but never declared in any defineX call: {locs}")

    return errors


def main() -> int:
    if not GROOVY_DIR.exists():
        print(f"ERROR: groovy directory not found: {GROOVY_DIR}", file=sys.stderr)
        return 1
    reg = scan(GROOVY_DIR)
    errors = report_violations(reg)

    decl_count = len(reg.decls)
    use_count = len(reg.uses)
    iri_count = len({d.iri for d in reg.decls})
    source_files = list(GROOVY_DIR.rglob("*.groovy")) + list(
        GROOVY_DIR.rglob("*.py")
    )
    print(
        f"Scanned {len(source_files)} Groovy/Python generator files, "
        f"{iri_count} unique RAK IRIs declared, {decl_count} declarations, {use_count} uses."
    )

    if errors:
        print(f"\n❌ FAILED: {len(errors)} IRI registry violation(s):\n")
        for e in errors:
            print(f"  {e}")
        return 1
    print("✅ IRI registry: no conflicts, no undeclared class/property IRIs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
