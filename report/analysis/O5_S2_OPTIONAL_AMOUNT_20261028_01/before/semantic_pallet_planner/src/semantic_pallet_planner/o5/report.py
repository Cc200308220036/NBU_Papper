"""Reports only saved committed states; never runs a planner or a model."""
import base64
import csv
import html
import io
import json
from pathlib import Path
from PIL import Image, ImageDraw
from .common import atomic, digest, new_directory, read, sha
from .visual import _scene, font
from .metrics import paired_sources


def export(experiment, output):
    root = Path(experiment).resolve()
    state = read(root/'run.json')
    plan = read(Path(state['plan'])/'plan.json')
    dest = new_directory(output)
    records = []
    sources = {}
    for job in state['jobs']:
        path = root/'jobs'/job['job_id']/'result.json'
        if not path.exists():
            continue
        result = read(path)
        sources[str(path)] = sha(path)
        frames = []
        container = plan['config']['container']
        frames.append([])
        for name in result['decisions']:
            jp = path.parent/name
            journal = read(jp)
            sources[str(jp)] = sha(jp)
            frames.append(journal['after'])
        images = []
        for index, placed in enumerate(frames):
            image = Image.new('RGB', (800, 620), 'white')
            draw = ImageDraw.Draw(image)
            draw.text((12, 10), f"{job['job_id']} | event {index} | actual committed state", fill='black', font=font(18))
            draw.text((12, 39), 'OFFLINE ENGINEERING ONLY - NOT VLM PERFORMANCE', fill='black', font=font(15))
            _scene(draw, (0, 65, 800, 510), container, placed)
            draw.text((12, 590), f'placed: {len(placed)} | all planned: {result["summary"]["planned_items"]}', fill='black', font=font(15))
            stream = io.BytesIO()
            image.save(stream, format='PNG')
            images.append('data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode())
            if index == len(frames)-1:
                (dest/(job['job_id']+'.png')).write_bytes(stream.getvalue())
        records.append({'job_id': job['job_id'], 'method': result['method'], 'summary': result['summary'],
                        'source_cluster_id': result['source_cluster_id'], 'images': images})
    rows = [{**{k: r[k] for k in ('job_id', 'method', 'source_cluster_id')}, **r['summary']} for r in records]
    with (dest/'orders.csv').open('w') as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    stats = paired_sources([{'source_cluster_id': r['source_cluster_id'], 'method': r['method'], 'summary': r['summary']}
                            for r in records]) if len(records) == len(state['jobs']) else {'status': 'PARTIAL'}
    payload = json.dumps(records, ensure_ascii=False).replace('<', '\\u003c')
    document = '''<!doctype html><meta charset="utf-8"><title>O5 S1 offline replay</title>
<style>body{font:16px sans-serif;max-width:1000px;margin:24px auto}img{max-width:100%}pre{white-space:pre-wrap}</style>
<h1>O5 S1 actual committed-state replay</h1><p>Offline engineering fixtures/results. No VLM performance or memory benefit is measured.</p>
<select id="job"></select><input id="step" type="range" min="0" value="0"><span id="label"></span>
<img id="image" alt="Actual committed pallet state"><pre id="summary"></pre>
<script>const records=PAYLOAD;
const job=document.getElementById('job'),step=document.getElementById('step');
records.forEach((r,i)=>{const o=document.createElement('option');o.value=i;o.textContent=r.job_id;job.append(o)});
function draw(){const r=records[+job.value];step.max=r.images.length-1;step.value=Math.min(+step.value,+step.max);document.getElementById('image').src=r.images[+step.value];document.getElementById('label').textContent=' event '+step.value;document.getElementById('summary').textContent=JSON.stringify(r.summary,null,2)}
job.onchange=()=>{step.value=0;draw()};step.oninput=draw;draw();</script>'''.replace('PAYLOAD', payload)
    (dest/'replay.html').write_text(document)
    manifest = {'schema_version': 'o5_report_manifest_v1', 'experiment': str(root),
                'planned_jobs': len(state['jobs']), 'recorded_jobs': len(records), 'sources': sources,
                'source_pairing': stats, 'model_performance': 'NOT_MEASURED', 'new_api_attempts': 0,
                'render_scope': 'saved committed states only; no hypothetical candidates',
                'files': {str(p.relative_to(dest)): sha(p) for p in dest.iterdir() if p.is_file()}}
    atomic(dest/'manifest.json', manifest)
    return {'status': 'PASS' if len(records) == len(state['jobs']) else 'PARTIAL', 'recorded_jobs': len(records), 'new_api_attempts': 0}
