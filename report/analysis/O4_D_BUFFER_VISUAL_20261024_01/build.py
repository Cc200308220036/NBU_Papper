"""Build a self-contained viewer from frozen O4-D journals; never call the API."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'semantic_pallet_planner/outputs/EXP_O4_D_ORDERS_REAL_20261023_01'
CASES = {
    'O4_ORDER_02_2': {
        'title': '代表改善：9 箱 → 19 箱',
        'note': '按 Oracle 搜索相对单箱的放置件数增量排序，本例增量最大。四种编译来源均重现 9 / 9 / 19 / 19。它说明已到货箱的改序与选址能恢复整单完成。',
    },
    'O4_ORDER_07_0': {
        'title': '改善但未完成：7 箱 → 13 箱',
        'note': 'Oracle 下单箱 / FIFO / 启发式 / 搜索分别放置 7 / 7 / 12 / 13 箱，总计 16 箱。改善不等于整单完成；切换真实模型查看其实际轨迹。',
    },
    'O4_ORDER_00_3': {
        'title': '边界：搜索退化与协议停止',
        'note': 'Oracle 下单箱、FIFO、启发式完成 16/16，搜索因物理候选耗尽停在 15/16；Text / Image 四方法均在首次编译失败后停止，实际码放 0 箱。两类失败须分别归因。',
    },
}


def read_json(path):
    return json.loads(path.read_text())


def main():
    data = {'cases': CASES, 'episodes': [], 'overview': [], 'source': SOURCE.name}
    evidence = {}
    totals = {}
    for path in sorted((SOURCE / 'jobs').glob('*.json')):
        job = read_json(path)
        summary = job['summary']
        key = (job['backend'], job['planner'])
        total = totals.setdefault(key, {'count': 0, 'clean': 0, 'placed_ratio': 0})
        total['count'] += 1
        total['clean'] += int(summary['clean_completed'])
        total['placed_ratio'] += summary['placed_item_ratio']
        if job['task_id'] not in CASES:
            continue
        journal = SOURCE / 'episodes' / (job['job_id'] + '.jsonl')
        events = [json.loads(line) for line in journal.read_text().splitlines()]
        frames = []
        states = [events[0]['before_public_state']]
        states += [e.get('after_public_state') or e['before_public_state'] for e in events]
        arrival = []
        for event in events:
            if event.get('received_id'):
                arrival.append(event['received_id'])
        for index, state in enumerate(states):
            event = events[index - 1] if index else {}
            frames.append({
                'placed': state['observation']['placed_objects'],
                'pending': state['pending_items'],
                'arrivals': state['arrival_count'],
                'kind': event.get('kind', 'START'),
                'status': event.get('status', '初始状态'),
                'picked': (event.get('action') or {}).get('pick_item_id'),
                'compilation_id': event.get('compilation_id'),
            })
        final = frames[-1]
        assert len(final['placed']) == summary['placed_items'], job['job_id']
        sequence = [e['action']['pick_item_id'] for e in events
                    if e.get('kind') == 'PLACE' and e.get('after_public_state')
                    and e['after_public_state']['placed_count'] > e['before_public_state']['placed_count']]
        assert len(sequence) == summary['placed_items']
        data['episodes'].append({
            'id': job['job_id'], 'task': job['task_id'], 'backend': job['backend'],
            'planner': job['planner'], 'summary': summary, 'frames': frames,
            'container': states[0]['observation']['container'],
            'instruction': states[0]['observation']['instruction_text'],
            'arrival': arrival, 'sequence': sequence,
        })
        for source in (path, journal):
            evidence[str(source.relative_to(ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
    for (backend, planner), total in totals.items():
        total['placed_ratio'] /= total['count']
        data['overview'].append({'backend': backend, 'planner': planner, **total})
    assert len(data['episodes']) == 48
    (HERE / 'data.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    (HERE / 'source_hashes.json').write_text(json.dumps(evidence, indent=2))
    template = (HERE / 'template.html').read_text()
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    (HERE / 'index.html').write_text(template.replace('__EXPERIMENT_DATA__', payload))
    print(f'Built {len(data["episodes"])} episode views; {len(evidence)} frozen files hashed.')


if __name__ == '__main__':
    main()
