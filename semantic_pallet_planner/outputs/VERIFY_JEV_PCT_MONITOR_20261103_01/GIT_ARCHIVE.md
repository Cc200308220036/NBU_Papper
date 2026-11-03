# P2/P3 Git artifact archive

The user requested that this development and all experiment evidence cited in
the acceptance report be uploaded to Git after engineering acceptance.

Tracked contents include the original test reports and development failures,
constructed/recovery records, both bounded on/off smoke runs, exact actions and
stages, negative record copies, identities, source/test/document snapshots,
protected-file inventories, original acceptance/manifest/handoff, audit scripts,
installation probe/results/logs, copied build source and the tested wheel.

`git_delivery_manifest.json` lists the actual archived paths and SHA256 hashes;
it excludes itself to avoid a self-referential hash. `git_delivery_scope.json`
lists every excluded rebuildable installation/cache/intermediate file. No
experiment evidence is replaced by a summary.

The original `delivery_manifest.json` is preserved byte for byte. It describes
the complete original local acceptance environment, including the installation
venv. Its excluded rebuildable files need not exist in a fresh Git checkout.
Use the Git manifest to verify this archive. The individual smoke manifests
remain complete and their normal saved-record validator remains applicable.
The installation venv can be rebuilt using the archived wheel, logs and probe.

From the repository root, verify archived bytes without running experiments:

```bash
python - <<'PYCODE'
import hashlib, json
from pathlib import Path
root = Path('semantic_pallet_planner/outputs/VERIFY_JEV_PCT_MONITOR_20261103_01')
manifest = json.loads((root / 'git_delivery_manifest.json').read_text())
for name, expected in manifest['files_sha256'].items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
print('verified', len(manifest['files_sha256']), 'files')
PYCODE
```

The report's Git archive addendum documents the later upload authorization;
original frozen experiment snapshots retain the text recorded at acceptance.
