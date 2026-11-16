"""Read-only selected delivery verification, no production imports."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent

def main():
    count=0
    for name in ('input_manifest.json','source_manifest.json','delivery_manifest.json'):
        for row in json.loads((OUT/name).read_text())['files']:
            path=ROOT/row['path']
            assert path.resolve().is_relative_to(ROOT)
            data=path.read_bytes()
            assert hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
            assert len(data)==row['bytes'],row['path']
            count+=1
    for row in json.loads((OUT/'saved_state_coverage.json').read_text())['rows']:
        result=json.loads((ROOT/row['result']['path']).read_text())
        sem=result['semantic']
        payload={k:v for k,v in sem.items() if k not in ('input_sha256','cost','semantic_digest')}
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
        assert hashlib.sha256(raw).hexdigest()==sem['semantic_digest']
        assert sem['contrast']['direction']=='UNKNOWN' or sem['contrast']['status']=='VALUE'
    print('PASS_SELECTED_IDENTITIES_AND_10_RESULT_SEALS',count)

if __name__=='__main__':main()
