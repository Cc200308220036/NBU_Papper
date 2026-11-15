"""Offline lossless gzip JSONL audit capsules, not an episode resume format.

Original source bytes and their hashes survive; existing P3 files are read-only.
Formal writer integration, WAL and optimizer transactions remain a future gate.
"""
import gzip
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
from .contracts import canonical,digest,read,require,sha,write_new


def safe_name(name):
    require(type(name) is str and bool(name),'P4A_STORAGE_PATH')
    p=PurePosixPath(name)
    require(bool(p.parts) and name != '.' and not p.is_absolute() and '..' not in p.parts
            and str(p)==name and '\\' not in name,'P4A_STORAGE_PATH')
    return name


def pack(source, names, target):
    source=Path(source);target=Path(target)
    require(not target.exists(),'P4A_STORAGE_OUTPUT_EXISTS')
    require(len(names)==len(set(names)),'P4A_STORAGE_DUPLICATE')
    entries=[]
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as output:
        with gzip.GzipFile(filename='',mode='wb',compresslevel=6,fileobj=output,mtime=0) as zipped:
            for name in names:
                safe_name(name);path=(source/name).resolve()
                require(path.is_relative_to(source.resolve()) and path.is_file(),'P4A_STORAGE_SOURCE_PATH')
                content=path.read_bytes();text=content.decode('utf-8')
                record={'path':name,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),'utf8_content':text}
                zipped.write((canonical(record)+'\n').encode())
                entries.append({k:record[k] for k in ('path','sha256','bytes')})
    index={'version':'pct_p4a_audit_shard_v1','codec':'gzip-jsonl-utf8-bytes-v1','resume_admitted':False,
           'compressed_sha256':sha(target),'compressed_bytes':target.stat().st_size,
           'uncompressed_source_bytes':sum(e['bytes'] for e in entries),'entries':entries}
    index['index_digest']=digest(index)
    return index


def unpack(archive,index,target):
    require(set(index)=={'version','codec','resume_admitted','compressed_sha256','compressed_bytes',
                        'uncompressed_source_bytes','entries','index_digest'},'P4A_STORAGE_INDEX_FIELDS')
    require(index['version']=='pct_p4a_audit_shard_v1' and index['codec']=='gzip-jsonl-utf8-bytes-v1'
            and index['resume_admitted'] is False,'P4A_STORAGE_INDEX_VERSION')
    require(index['index_digest']==digest({k:v for k,v in index.items() if k!='index_digest'})
            and sha(archive)==index['compressed_sha256'] and Path(archive).stat().st_size==index['compressed_bytes'],'P4A_STORAGE_DIGEST')
    names=[safe_name(e['path']) for e in index['entries']]
    require(len(names)==len(set(names)) and all(set(e)=={'path','sha256','bytes'} for e in index['entries']), 'P4A_STORAGE_ENTRIES')
    target=Path(target);require(not target.exists(),'P4A_RESTORE_OUTPUT_EXISTS');target.mkdir(parents=True,exist_ok=False)
    restored=[]
    with gzip.open(archive,'rb') as stream:
        for expected in index['entries']:
            line=stream.readline(64*1024*1024)
            require(line.endswith(b'\n'),'P4A_STORAGE_LINE_LIMIT_OR_TRUNCATION')
            record=json.loads(line)
            require(set(record)=={'path','sha256','bytes','utf8_content'} and
                    {k:record[k] for k in ('path','sha256','bytes')}==expected,'P4A_STORAGE_ENTRY_DRIFT')
            data=record['utf8_content'].encode('utf-8')
            require(len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256'],'P4A_STORAGE_CONTENT')
            path=target/safe_name(record['path']);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as out:out.write(data)
            restored.append(expected)
        require(stream.read(1)==b'','P4A_STORAGE_EXTRA_RECORDS')
    require(sum(e['bytes'] for e in restored)==index['uncompressed_source_bytes'],'P4A_STORAGE_TOTAL')
    return restored


def episode_facts(root):
    header=read(Path(root)/'header.json');episode=read(Path(root)/'episode.json')
    transitions=[e for e in episode['events'] if e.get('selection') is not None]
    return {'header_digest':header['header_digest'],'task_digest':digest(header['task']),
            'config_digest':digest(header['config']),'model_binding_digest':digest(header['model_binding']),
            'checkpoint_digest':digest(episode['checkpoint']),'episode_digest':digest(episode),
            'planned_items':len(header['task']['items']),'placed_items':len(episode['final_state']['placed_items']),
            'transitions':len(transitions),'transition_digests':[digest(e) for e in transitions],
            'reason':episode['checkpoint']['reason']}


def validate_saved_training(source,output):
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    before={};results=[]
    for batch in range(2):
        names=[]
        for i in range(batch*8,batch*8+8):
            attempt=f'training_{i:02d}';root=source/attempt
            paths=[root/'header.json',root/'episode.json']+list((root/'records').glob('*.json'))+list((root/'decision_rng').glob('*.json'))
            names.extend(str(p.relative_to(source)) for p in sorted(paths))
        before.update({n:sha(source/n) for n in names})
        archive=output/f'batch_{batch}.jsonl.gz';index=pack(source,names,archive)
        write_new(output/f'batch_{batch}.index.json',index)
        restore=output/f'restored_batch_{batch}';unpack(archive,index,restore)
        for i in range(batch*8,batch*8+8):
            name=f'training_{i:02d}';original=episode_facts(source/name);restored=episode_facts(restore/name)
            require(original==restored,'P4A_STORAGE_EPISODE_OR_TRANSITION_DRIFT')
            results.append({'attempt':name,'facts':original,'roundtrip':'BYTE_AND_SEMANTIC_EQUAL'})
    require(before=={n:sha(source/n) for n in before},'P4A_STORAGE_ORIGINAL_CHANGED')
    indexes=[read(output/f'batch_{i}.index.json') for i in range(2)]
    return {'version':'pct_p4a_storage_roundtrip_v1','status':'PASS_AUDIT_CAPSULE_ONLY','attempts':16,
            'transitions':sum(r['facts']['transitions'] for r in results),'source_files':len(before),
            'source_bytes':sum(x['uncompressed_source_bytes'] for x in indexes),
            'compressed_bytes':sum(x['compressed_bytes'] for x in indexes),'results':results,
            'original_hashes':before,'source_unchanged':True,'resume_admitted':False,
            'limits':'saved UTF-8 header/episode/selection/RNG JSON only; no state.pt deserialization, no journal replay, no formal transactional writer or throughput claim'}
