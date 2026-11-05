"""只追加的决策证据、可复现性清单、指标与汇总结果。"""
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
from datetime import datetime, timezone
from ..validation import validate


def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def dataset_checksums(root):
    root=Path(root)
    folders=('tasks','candidates','annotations','splits','streams','schemas','configs','catalog','provenance')
    return {str(p.relative_to(root)):file_hash(p) for folder in folders for p in sorted((root/folder).rglob('*.json'))}

def source_checksums():
    root=Path(__file__).resolve().parents[3]
    files=[*root.glob('src/**/*.py'),*root.glob('src/**/*.json'),*root.glob('configs/*.yaml'),*root.glob('tests/**/*.py'),root/'pyproject.toml']
    return {str(p.relative_to(root)):file_hash(p) for p in sorted(files)}

def environment_info():
    versions={}
    for name in ('numpy','matplotlib','Pillow','jsonschema','PyYAML','pytest'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='not installed'
    cpu=platform.processor()
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),cpu)
    return dict(python=platform.python_version(),platform=platform.platform(),cpu=cpu,cpu_count=os.cpu_count(),dependencies=versions,code_state='source SHA256 snapshot; workspace has no usable Git metadata')

def core_event(event):
    # 只保留数值决策，排除耗时、渲染路径和实验标识。
    return {k:event[k] for k in ('track','method','scenario_id','step_index','state_hash','candidate_id','fallback','committed','termination_reason','after')}

class Experiment:
    def __init__(self,cfg,identifier=None):
        self.cfg=cfg
        self.identifier=identifier or 'EXP_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f')
        if not self.identifier or Path(self.identifier).name!=self.identifier or self.identifier in ('.','..'):
            raise ValueError('experiment ID must be a single directory name')
        self.root=Path(cfg['output_root'])/self.identifier
        data=Path(cfg['dataset']).resolve()
        if self.root.resolve().is_relative_to(data) or data.is_relative_to(self.root.resolve()):
            raise ValueError('experiment outputs must be separate from dataset')
        self.root.mkdir(parents=True,exist_ok=False)
        (self.root/'memory').mkdir()
        (self.root/'metrics').mkdir()
        (self.root/'steps.jsonl').touch()
        dump(self.root/'config.snapshot.json',cfg)
        self.events=[]; self.decisions=[];self.episodes=[]
        self.manifest=dict(schema_version='pallet_manifest_v1',experiment_id=self.identifier,
            config_sha256=digest(cfg),source_checksums=source_checksums(),dataset_checksums=dataset_checksums(cfg['dataset']),
            environment=environment_info(),created_utc=datetime.now(timezone.utc).isoformat(),core_result_sha256='',result_file_checksums={})
        dump(self.root/'manifest.json',self.manifest)

    def append(self,event,episode_dir=None):
        validate('step',event)
        self.events.append(core_event(event))
        line=json.dumps(event,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n'
        with (self.root/'steps.jsonl').open('a') as f:f.write(line)
        if episode_dir:
            with (episode_dir/'steps.jsonl').open('a') as f:f.write(line)

    def metric(self,row):
        validate('metric',row)
        (self.decisions if row['track']=='fixed' else self.episodes).append(row)

    def finish(self):
        from ..evaluation.metrics import aggregate
        for name,rows in [('per_decision',self.decisions),('per_episode',self.episodes)]:
            write_csv(self.root/'metrics'/f'{name}.csv',rows)
        summary=aggregate(self.decisions,self.episodes,self.cfg['seed'])
        dump(self.root/'metrics/summary.json',summary)
        self.manifest['core_result_sha256']=digest(self.events)
        self.manifest['result_file_checksums']={str(p.relative_to(self.root)):file_hash(p) for p in sorted(self.root.rglob('*')) if p.is_file() and p.name!='manifest.json'}
        validate('manifest',self.manifest)
        dump(self.root/'manifest.json',self.manifest)
        return summary


def write_csv(path,rows):
    fields=sorted({k for row in rows for k in row}) or ['experiment_id','track','method','scenario_id','split']
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
