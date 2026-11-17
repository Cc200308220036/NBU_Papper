"""Read-only GP2 byte-manifest validation; no experiments or output rewrite."""
import hashlib
import json
from pathlib import Path
root=Path.cwd()
folder=Path(__file__).resolve().parent
manifest=json.loads((folder/'delivery_manifest.json').read_text())
for row in manifest['files']:
    p=root/row['path']
    assert p.is_file(),str(p)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],str(p)
source=json.loads((folder/'source_manifest.json').read_text())
for path,sha in source['files'].items():
    p=root/source['package_root']/path
    assert hashlib.sha256(p.read_bytes()).hexdigest()==sha,str(p)
print('PASS byte identities:',len(manifest['files']),'delivery files;',len(source['files']),'production sources')
