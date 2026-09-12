#!/usr/bin/env python3
"""Authorize only the confirmed pH successor in a preserved release manifest."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
path = root / 'expected/fresh_modules_manifest.json'
original = path.read_bytes()
manifest = json.loads(original)
old = 'rubalkhali_ph_eq_ph_shared_v1_0_0.ttl'
new = 'rubalkhali_ph_eq_ph_shared_v1_0_1.ttl'
records = [r for r in manifest['records'] if r['file'] == old]
if len(records) != 1 or len(manifest['records']) != 16:
    raise ValueError('Expected one predecessor pH module among sixteen modules')
reference = root / 'expected/ph_v1_0_1_reference.ttl'
data = reference.read_bytes()
digest = hashlib.sha256(data).hexdigest()
if digest != '4c3af7c30633822e7ce86cedd54247dbaba69a598cc9014cbc2c0cfab8a14811':
    raise ValueError('Confirmed pH reference hash mismatch')
record = records[0]
before = dict(record)
record.update(file=new, sha256=digest, bytes=len(data))
record['path'] = record.get('path', old).replace(old, new)
(root / 'expected/predecessor_fresh_modules_manifest.json').write_bytes(original)
path.write_text(json.dumps(manifest, indent=2) + '\n')
(root / 'expected/ph_successor_delta.json').write_text(json.dumps({
    'predecessor_manifest_sha256': hashlib.sha256(original).hexdigest(),
    'before': before, 'after': record,
    'other_module_expectations_unchanged': True,
    'note': 'Source package manifests must be regenerated before public packaging.'
}, indent=2) + '\n')
