"""Read immutable experiments and project ONLY their public request/state fields."""
import json
from pathlib import Path
from ..common import read,digest


def public_records(ab,c,f):
    data=read(Path(ab)/'private/data.json')
    for name in ('gold','pairs'):
        for row in data[name]:yield f'AB/{name}/{row["case_id"]}',row['request']
    for path in sorted((Path(c)/'episodes').glob('*/*/steps.jsonl')):
        for i,line in enumerate(path.open()):
            event=json.loads(line);yield f'C/{path.parent.parent.name}/{path.parent.name}/{i}',event['request']
    for path in sorted((Path(f)/'episodes').glob('*/*/events.jsonl')):
        for i,line in enumerate(path.open()):
            event=json.loads(line)
            # Cover EVERY event's before/after public state, including arrivals, EOS,
            # empty queue and failed termination. No private trajectory fields cross.
            for key in ('public_state','after_public_state'):
                yield f'F/{path.parent.parent.name}/{path.parent.name}/{i}/{key}',event[key]


def load_corpus(ab,c,f,limit=None):
    unique={};references=[]
    for origin,public in public_records(ab,c,f):
        key=digest(public)
        if limit is not None and key not in unique and len(unique)>=limit:continue
        unique.setdefault(key,public);references.append({'origin':origin,'public_source_digest':key})
    return unique,references
