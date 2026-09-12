#!/usr/bin/env python3
"""Export exact site coordinates and corrected PCR-NTC role identities."""
import argparse
import csv
import json
import hashlib
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS
import yaml


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--modules", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    b = Namespace("https://rubalkhali.science/kb/")
    geo = Namespace("http://www.opengis.net/ont/geosparql#")
    sites = Graph().parse(a.modules / "rubalkhali_sites.owl", format="xml")
    rows = []
    for site in sites.subjects(RDF.type, b.RAK_0000002):
        labels = list(sites.objects(site, RDFS.label))
        coords = list(sites.objects(site, geo.asWKT))
        assert len(labels) == len(coords) == 1
        rows.append(dict(site=str(site), siteLabel=str(labels[0]), wkt=str(coords[0])))
    assert len(rows) == 70
    with (a.output / "sites70.tsv").open("w", newline="") as h:
        writer = csv.DictWriter(h, ["site", "siteLabel", "wkt"], delimiter="\t")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["site"]))
    with (a.modules / "control_metadata/control_entity_registry.tsv").open() as h:
        registry = list(csv.DictReader(h, delimiter="\t"))
    with (a.modules / "control_metadata/control_roles.tsv").open() as h:
        roles = list(csv.DictReader(h, delimiter="\t"))
    selected = []
    for row in registry:
        if row["entity_kind"] != "control_material" or row["primary_identifier"] not in ["Negative1", "Negative2", "Negative4", "Negative5", "Negative6", "Negative7"]:
            continue
        expected_roles = [r for r in roles if r["bearer_material_id"] == row["entity_id"]]
        assert len(expected_roles) == 1 and expected_roles[0]["role_type"] == "pcr_blank"
        role = expected_roles[0]
        selected.append(dict(material=row["entity_id"], identifier=row["primary_identifier"], label=row["primary_label"], role=role["role_id"], roleClass=str(b.RAK_0000307), forbiddenRoleClass=str(b.RAK_0000306), realizedIn=role["realized_in_process_id"]))
    assert len(selected) == 6
    (a.output / "six_pcr_ntcs.json").write_text(json.dumps(sorted(selected, key=lambda r: r["identifier"]), indent=2) + "\n")
    # Field-XRF expected values come from the audited source table, not an
    # executed RDF query. Labels follow the curated analyte class catalogue.
    source_table = a.source / "data/processed/geochemistry/xrf_field_table.tsv"
    chemical_map = a.source / "config/codes/xrf_chemical_mapping.yml"
    chemical_names = yaml.safe_load(chemical_map.read_text())["mappings"]
    tbox = Graph().parse(a.modules / "rubalkhali.owl", format="xml")
    labels = {}
    number = 100
    for name in chemical_names:
        if name == "LE":
            continue
        labels[name] = list(tbox.objects(b[f"RAK_0{number:06d}"], RDFS.label))
        number += 1
    xrf_rows = []
    with source_table.open() as h:
        for row in csv.DictReader(h, delimiter="\t"):
            if row["SiteID"] != "10":
                continue
            for name in labels:
                if name not in row or float(row[name]) == 0:
                    continue
                for label in labels[name]:
                    xrf_rows.append(dict(processLabel=f'Field XRF analysis (Test {row["TestID"]}) for Site 10 (Trip5)', siteLabel="Site 10", analyte=str(label), concentration=float(row[name])))
    assert len(xrf_rows) == 46
    with (a.output / "field_xrf_site10.tsv").open("w", newline="") as h:
        writer = csv.DictWriter(h, ["processLabel", "siteLabel", "analyte", "concentration"], delimiter="\t")
        writer.writeheader()
        writer.writerows(sorted(xrf_rows, key=lambda r: (r["processLabel"], r["analyte"])))
    paths = [a.modules / "rubalkhali_sites.owl", a.modules / "rubalkhali.owl", source_table, chemical_map,
             a.modules / "control_metadata/control_entity_registry.tsv", a.modules / "control_metadata/control_roles.tsv"]
    evidence = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size} for path in paths]
    (a.output / "small_expectations_manifest.json").write_text(json.dumps({"method": __doc__, "site_rows": 70, "corrected_pcr_ntcs": 6, "field_xrf_site10_rows": 46, "inputs": evidence}, indent=2) + "\n")


if __name__ == "__main__":
    main()
