"""Small side-by-side 3D O3 evidence GIFs; never used for selection."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from .primitives import plt, draw_pallet
from ..vlm.pilot_protocol_v2 import digest


def render_comparison(root, source_scenario, policy_id='P0', methods=('geometry_greedy','public_parser')):
    root = Path(root)
    episode_id = f'O3_{source_scenario}_{policy_id}'
    episodes = []
    for method in methods:
        directory = root/'episodes'/method/episode_id
        info = json.loads((directory/'episode.json').read_text())
        events = [json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines() if line]
        episodes.append((info,events))
    output = root/'visualization'/episode_id
    output.mkdir(parents=True, exist_ok=True)
    total = max(len(events) for _,events in episodes)
    images, frame_links = [], []
    for frame_index in range(total):
        fig = plt.figure(figsize=(11,5), dpi=100, facecolor='white')
        refs = []
        for side,(method,(info,events)) in enumerate(zip(methods,episodes)):
            event = events[min(frame_index,len(events)-1)]
            state = event['after_placed']
            container = info['task']['scenario_container'] if 'scenario_container' in info['task'] else None
            if container is None:
                # Every step's public request includes the same public container.
                req = json.loads((root/'episodes'/method/episode_id/'selector_inputs'/event['request_id']/'public_request.json').read_text())
                container = req['container']
            ax = fig.add_axes([.03 + side*.5,.14,.45,.78],projection='3d')
            draw_pallet(ax,container,state)
            ax.set_title(f'{method} | step {event["step_index"]} | {event["status"]}',fontsize=10)
            refs.append({'method': method, 'episode_id': episode_id,
                         'step_index': event['step_index'], 'request_id': event['request_id'],
                         'status': event['status']})
        fig.text(.03,.04, f'{source_scenario} / {policy_id}  |  O3 online trajectory', fontsize=11)
        path = output/f'frame_{frame_index:03d}.png'
        fig.savefig(path)
        plt.close(fig)
        with Image.open(path) as frame:
            images.append(frame.convert('RGB').quantize(colors=128))
        frame_links.append(refs)
    target = output/'comparison.gif'
    images[0].save(target,save_all=True,append_images=images[1:],duration=700,loop=0,optimize=False)
    for frame in images: frame.close()
    (output/'manifest.json').write_text(json.dumps({'source_scenario': source_scenario,
        'policy_id': policy_id, 'methods': list(methods), 'frames': frame_links,
        'episode_digests': [info['core_result_sha256'] for info,_ in episodes],
        'render_digest': digest(frame_links)}, ensure_ascii=False,indent=2)+'\n')
    return target
