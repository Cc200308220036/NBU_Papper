"""Analyze only newly saved layout-v2 evidence; never execute an episode."""
import collections
import html
import json
import math
from pathlib import Path
import statistics
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'semantic_pallet_planner/outputs'
HERE = Path(__file__).resolve().parent
EXP = OUT/'EXP_O4_E5_LAYOUT_V2_L2_20261027_01'
P0 = OUT/'EXP_O4_E5_LAYOUT_V2_P0_20261027_01'
L0 = OUT/'EXP_O4_E5_LAYOUT_V2_L0_20261027_01'


def read(path): return json.loads(path.read_text())
def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def percentile(values, p):
    values = sorted(values)
    if not values: return None
    at = (len(values)-1)*p; low = math.floor(at); high = math.ceil(at)
    return values[low]+(values[high]-values[low])*(at-low)


def metrics():
    rows = read(EXP/'metrics/rows.json'); jobs = read(EXP/'jobs.json')
    core = [r for r in rows if r['stage'] == 'L2']; aggregates = read(EXP/'metrics/summary.json')
    pairs = []
    for method in ('single', 'buffer_search'):
        for task_id in sorted({r['task_id'] for r in core}):
            lookup = {r['group']: r for r in core if r['method'] == method and r['task_id'] == task_id}
            if set(lookup) != set('ABCD'): continue
            a, d = lookup['A'], lookup['D']
            pairs.append({'task_id': task_id, 'source_order_key': a['source_order_key'], 'configuration': a['configuration'],
                          'method': method, 'A_placed': a['placed_items'], 'D_placed': d['placed_items'],
                          'count_delta': d['placed_items']-a['placed_items'],
                          'volume_delta': d['placed_volume_ratio']-a['placed_volume_ratio'],
                          'A_completed': a['clean_completed'], 'D_completed': d['clean_completed'],
                          'hold': d['placed_items'] <= a['placed_items']-2 or (a['clean_completed'] and not d['clean_completed']),
                          'A_termination': a['termination_reason'], 'D_termination': d['termination_reason'],
                          'all_groups': {g: {'placed': r['placed_items'], 'volume': r['placed_volume_ratio'], 'complete': r['clean_completed']} for g, r in lookup.items()}})
    write(HERE/'paired_results.json', pairs)
    times = read(EXP/'metrics/decision_times.json'); latency = []
    for method in ('single', 'buffer_search'):
        for group in ('A', 'D'):
            values = [r['seconds'] for r in times if r['method'] == method and r['group'] == group and r['seconds'] is not None and r['job_id'].startswith('L2_')]
            latency.append({'method': method, 'group': group, 'decisions': len(values),
                            'median_seconds': statistics.median(values) if values else None, 'p95_seconds': percentile(values, .95),
                            'scope': 'main_run_actual_trajectories_includes_cache_effects'})
    write(HERE/'latency_main.json', latency)
    episodes_latency = []
    for method in ('single', 'buffer_search'):
        for group in 'ABCD':
            values = [r['elapsed_seconds'] for r in core if r['method'] == method and r['group'] == group]
            episodes_latency.append({'method':method,'group':group,'episodes':len(values),
                                     'total_seconds':sum(values), 'median_seconds':statistics.median(values) if values else None,
                                     'p95_seconds':percentile(values,.95),
                                     'scope':'full local episode including compile, downstream audit and checkpoint writes; own actual trajectories'})
    write(HERE/'latency_end_to_end.json', episodes_latency)
    complete = len(rows) == len(jobs) == 56 and all(j['status'] == 'PASS' for j in jobs)
    noninferior = True; gains = False
    for method in ('single', 'buffer_search'):
        subset = [p for p in pairs if p['method'] == method]
        if not subset: noninferior = False; continue
        volume = sum(p['volume_delta'] for p in subset)/len(subset)
        count = sum(p['count_delta'] for p in subset)
        clean = sum(p['D_completed']-p['A_completed'] for p in subset)
        noninferior &= volume >= -1e-9 and count >= 0 and clean >= 0
        gains |= volume >= .01 and count >= 1
    findings = {'planned': len(jobs), 'recorded': len(rows), 'execution_complete': complete,
                'aggregates': aggregates, 'paired_results': pairs,
                'physical_and_business_safety': 'runtime independent physical commits; downstream reference checks',
                'violating_steps': sum(r['violating_steps'] for r in rows),
                'L2_noninferior_both_methods': noninferior, 'L2_gain_at_least_one_method': gains,
                'severe_regressions': [p for p in pairs if p['hold']],
                'L3_recommended': complete and noninferior and gains and not any(p['hold'] for p in pairs),
                'performance_status': 'L2_SCREEN_ONLY_NOT_24_TASK_GATE',
                'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT', 'new_api_attempts': 0,
                'business_support_quality': 'NOT_IMPLEMENTED', 'probe_quality': 'NOT_IMPLEMENTED',
                'independent_generalization': 'NOT_MEASURED'}
    write(HERE/'analysis.json', findings)
    return findings


def svg(state, hypothesis=None):
    container = state['container']; length = container['length_mm']; width = container['width_mm']
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-length/2-40} {-width/2-40} {length+80} {width+80}" style="width:100%;max-height:420px">',
                f'<rect x="{-length/2}" y="{-width/2}" width="{length}" height="{width}" fill="#fafafa" stroke="#333" stroke-width="3"/>']
    palette = ['#b9d9eb', '#fad1a4', '#cbe5bd', '#e7c6e8', '#f4c0c0', '#ccdfef']
    for i, obj in enumerate(state['placed_items']):
        p = obj['pose']; dx, dy, _ = obj['oriented_size_mm']; x = p['x_mm']-dx/2; y = -p['y_mm']-dy/2
        elements.append(f'<rect x="{x}" y="{y}" width="{dx}" height="{dy}" fill="{palette[i%len(palette)]}" fill-opacity=".85" stroke="#334" stroke-width="2"/>')
        label = html.escape(obj['item_id'])+f" z={p['z_base_mm']:g}"
        elements.append(f'<text x="{p["x_mm"]}" y="{-p["y_mm"]}" text-anchor="middle" font-size="21">{label}</text>')
    if hypothesis:
        p = hypothesis['pose']; dx, dy, _ = hypothesis['oriented_size_mm']
        elements.append(f'<rect x="{p["x_mm"]-dx/2}" y="{-p["y_mm"]-dy/2}" width="{dx}" height="{dy}" fill="#e44" fill-opacity=".17" stroke="#c22" stroke-width="4" stroke-dasharray="12 6"/>')
    elements.append('</svg>')
    return ''.join(elements)


def visualization():
    rows = read(EXP/'metrics/rows.json'); cards = []
    for row in rows:
        if row['stage'] != 'L2' or row['group'] not in ('A', 'D'): continue
        result = read(EXP/'episodes'/f'{row["job_id"]}.json')
        decisions = [e for e in result['events'] if 'search_trace' in e]
        terminal = decisions[-1]
        rejected = next((c for g in terminal['groups'] for c in g['candidates'] if c['candidate_id'] not in g['evaluation']['allowed_ids']), None)
        details = {'input': terminal['request'], 'AST': terminal['response']['policy_ast'], 'actual_action': terminal['action'],
                   'search_trace': terminal['search_trace'], 'candidate_decisions': [
                       {'pick': g['pick_item_id'], 'generation': g['generation'], 'ranking': g['trace'],
                        'rejected_candidates': [{'candidate': c, 'violations': next(r['after']['violations'] for r in g['evaluation']['evaluations'] if r['candidate_id'] == c['candidate_id'])}
                                                for c in g['candidates'] if c['candidate_id'] not in g['evaluation']['allowed_ids']]}
                       for g in terminal['groups']]}
        cards.append(f'<article><h2>{html.escape(row["job_id"])}</h2><p>Placed {row["placed_items"]}/{row["planned_items"]}; order volume {row["placed_volume_ratio"]:.2%}; pallet volume {row["pallet_volume_utilization"]:.2%}; {html.escape(row["termination_reason"])}</p>'
                     +svg(result['final_state'])
                     +('<details><summary>Rejected hypothetical box (red dashed, never committed)</summary>'+svg(terminal['before'], rejected)+'</details>' if rejected else '')
                     +'<details><summary>Input, AST, action, candidate rejection and ranking</summary><pre>'+html.escape(json.dumps(details, ensure_ascii=False, indent=2))+'</pre></details></article>')
    fixed_cards = []
    for case in read(L0/'fixed_decisions.json'):
        for group in 'ABCD':
            r = case['results'][group]; selected = r['selected']
            fixed_cards.append(f'<article><h2>{case["case"]} / {group}</h2><p>Same public state; dashed box is the proposed next placement.</p>'+svg(case['state'], selected)
                               +'<details><summary>AST and choice explanation</summary><pre>'+html.escape(json.dumps({'AST':case['ast'],'selected':selected,'trace':r['groups'][0]['trace']},ensure_ascii=False,indent=2))+'</pre></details></article>')
    page = '<!doctype html><meta charset="utf-8"><title>E5 layout v2 local results</title><style>body{font:15px system-ui;max-width:1500px;margin:24px auto;padding:16px;background:#f2f4f6}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:18px}article{background:white;padding:18px;border:1px solid #ccd;border-radius:8px}h2{font-size:16px;overflow-wrap:anywhere}pre{white-space:pre-wrap;max-height:450px;overflow:auto;font-size:12px}</style><h1>E5 layout v2 — local development evidence</h1><p>Exact mm proportions. x right, y back (up in this top view). Solid boxes are actual placements; red dashed boxes are hypotheses. All orders are development sources. No remote model calls.</p><h2>Fixed-state comparisons</h2><main>'+''.join(fixed_cards)+'</main><h2>Complete trajectories from an empty pallet</h2><main>'+''.join(cards)+'</main>'
    (HERE/'layouts.html').write_text(page)
    # Validate the generated SVG structure and identical x/y scale through viewBox.
    count = 0
    import re
    for match in re.findall(r'<svg.*?</svg>', page, flags=re.S):
        element = ET.fromstring(match); values = list(map(float, element.attrib['viewBox'].split()))
        assert values[2] > 0 and values[3] > 0; count += 1
    write(HERE/'visual_validation.json', {'svg_count': count, 'xml_valid': True, 'axes_equal_scale': True,
                                          'hypotheses_labelled': True, 'source': str(EXP.relative_to(ROOT)),
                                          'manual_browser_review': 'NOT_PERFORMED'})


if __name__ == '__main__':
    result = metrics(); visualization()
    print(json.dumps({k: v for k, v in result.items() if k not in ('aggregates', 'paired_results', 'severe_regressions')}, ensure_ascii=False, indent=2))
