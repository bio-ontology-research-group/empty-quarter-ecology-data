"""Refresh the lat/lon columns of batch_meta.tsv from the pinned geodata.

The 7 Sep 2026 batch_meta.tsv was built before the Site 52 correction (data
repository a3f1c21): Trip 1 and Trip 3 rows of Site 52 carried the Site 53
position. This rewrites lat/lon from data/metadata/geodata/trip{N}_geodata.tsv
(row = trip, Site) and leaves every other column unchanged. It fails if any
coordinate other than the expected Site 52 rows would change.
"""
import csv, sys

META, GEO_DIR = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(META), delimiter="\t"))
fields = list(rows[0].keys())
geo = {}
for trip in sorted({r["trip"] for r in rows}):
    for g in csv.DictReader(open(f"{GEO_DIR}/trip{trip}_geodata.tsv"), delimiter="\t"):
        if g["Site"] and g["Latitude"] and g["Longitude"]:
            geo[(trip, g["Site"])] = (g["Latitude"], g["Longitude"])
changed = []
for r in rows:
    key = (r["trip"], r["site"])
    if key not in geo:
        if r["lat"] or r["lon"]:
            sys.exit(f"no geodata for {key} but batch_meta has coordinates")
        continue
    lat, lon = geo[key]
    if abs(float(r["lat"]) - float(lat)) > 1e-9 or abs(float(r["lon"]) - float(lon)) > 1e-9:
        changed.append((r["profile"], r["trip"], r["site"], r["lat"], r["lon"], lat, lon))
        r["lat"], r["lon"] = lat, lon
bad = [c for c in changed if not (c[2] == "52" and c[1] in ("1", "3"))]
if bad:
    sys.exit(f"unexpected coordinate changes: {bad[:5]}")
with open(META, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
    w.writeheader(); w.writerows(rows)
print(f"{len(changed)} profiles updated")
for c in changed:
    print("\t".join(c))
