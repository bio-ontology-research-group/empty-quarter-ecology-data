#!/usr/bin/env python3
"""Derive the sole approved pH successor entry without changing its predecessor."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

OLD_FILE = "rubalkhali_ph_eq_ph_shared_v1_0_0.ttl"
NEW_FILE = "rubalkhali_ph_eq_ph_shared_v1_0_1.ttl"
OLD_SHA256 = "22a36f62d64bf38e0efc06d31f3104dd210f1518d205c7fb5032ddd8c42728cb"
NEW_SHA256 = "4c3af7c30633822e7ce86cedd54247dbaba69a598cc9014cbc2c0cfab8a14811"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--successor-module", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve existing manifest: " + str(args.output))
    previous_bytes = args.predecessor.read_bytes()
    previous = json.loads(previous_bytes)
    successor = copy.deepcopy(previous)
    records = successor["records"]
    if previous.get("version") != "3.0.0" or len(records) != 16:
        raise ValueError("Expected exactly sixteen KG 3.0.0 modules")
    targets = [record for record in records if record["file"] == OLD_FILE]
    if len(targets) != 1 or targets[0]["sha256"] != OLD_SHA256:
        raise ValueError("Predecessor pH module differs from frozen evidence")
    module_bytes = args.successor_module.read_bytes()
    if hashlib.sha256(module_bytes).hexdigest() != NEW_SHA256 or len(module_bytes) != 4233808:
        raise ValueError("Successor pH module differs from focused-regression evidence")
    target = targets[0]
    target.update(file=NEW_FILE, path=str(Path(target["path"]).with_name(NEW_FILE)),
                  sha256=NEW_SHA256, bytes=len(module_bytes),
                  derivation="fresh_source_generation_with_confirmed_trip4_specimen_reconciliation")
    successor["ph_successor"] = {
        "dataset_version": "EQ-PH-SHARED-v1.0.1",
        "predecessor_manifest_sha256": hashlib.sha256(previous_bytes).hexdigest(),
        "predecessor_module_sha256": OLD_SHA256,
        "successor_module_sha256": NEW_SHA256,
        "unchanged_module_count": 15,
        "scope": "Approved physical-specimen reconciliation; all other module records preserved exactly."
    }
    if [r for r in records if r["file"] != NEW_FILE] != [r for r in previous["records"] if r["file"] != OLD_FILE]:
        raise ValueError("Unrelated module records changed")
    with args.output.open("x") as stream:
        json.dump(successor, stream, indent=2)
        stream.write("\n")
    print("PASS: one hash-verified pH successor; fifteen module records unchanged")


if __name__ == "__main__":
    main()
