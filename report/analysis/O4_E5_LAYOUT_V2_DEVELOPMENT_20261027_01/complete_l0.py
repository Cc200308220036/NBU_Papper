"""Complete third-family L0 comparisons on eight saved public states only."""
from pathlib import Path
from semantic_pallet_planner.o4.common import read, write, digest
from semantic_pallet_planner.o4.extensions.e5.planning import choose
from semantic_pallet_planner.o4.extensions.e5.layout_v2.quality import measure
from semantic_pallet_planner.o4.extensions.e2.candidates import key

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]
OUT = ROOT/'semantic_pallet_planner/outputs'
P0 = OUT/'EXP_O4_E5_LAYOUT_V2_P0_20261027_01'
PLAN = OUT/'PLAN_O4_E5_LAYOUT_V2_20261027_01'
plan = read(PLAN/'plan.json'); records = []
for method in ('single','buffer_fifo','buffer_heuristic','buffer_search'):
    files = sorted((P0/'cases').glob(f'rollback_{method}_*.json'))
    for phase, path in [('early',files[0]),('terminal',files[-1])]:
        saved = read(path); state=saved['public_state']; req=saved['request']; ast=saved['ast']
        groups = {}
        for group in ('A','D'):
            selected, pool, trace, reason = choose(state,req,ast,plan['group_configurations'][group],method)
            detailed=[]
            for g in pool:
                original = next(x for x in saved['groups'] if x['pick_item_id']==g['pick_item_id'])
                returned = {key(c):c for c in g['candidates']}
                assert set(returned) <= {key(r['candidate']) for r in original['rows']}
                rows=[]
                for old in original['rows']:
                    c=returned.get(key(old['candidate'])); retained=c is not None
                    eligible=c['candidate_id'] in g['trace']['eligible_labels'] if retained else None
                    layer='compression' if not retained else 'hard_filter' if not old['business_allowed'] else 'soft_budget' if not eligible else 'eligible_for_position_and_search'
                    rows.append({'pose':old['candidate']['pose'],'sources':old['sources'],
                                 'bounds_mm':old['quality']['bounds_mm'],'geometry_score_components':old['candidate']['geometry_score_components'],
                                 'support':old['candidate']['support'],'physics':'PASS',
                                 'retained':retained,'business_allowed':old['business_allowed'],
                                 'business_rejection_codes':old['business_rejection_codes'],
                                 'soft_budget_eligible':eligible,'decision_stage':layer,
                                 'new_quality':measure(state,old['candidate']),
                                 'first_differing_position_rank_component':g['trace'].get('first_differing_rank_component',{}).get(c['candidate_id']) if retained else None})
                detailed.append({'pick_item_id':g['pick_item_id'],'rows':rows,'actual_generation':g['generation'],
                                 'position_trace':g['trace'],'selected_for_group':g['selected'],
                                 'counts':{'sampled_physical':len(rows),'topk':len(returned),
                                           'sampled_business_allowed':sum(r['business_allowed'] for r in rows),
                                           'topk_business_allowed':len(g['evaluation']['allowed_ids']),
                                           'soft_eligible':len(g['trace']['eligible_labels'])}})
            groups[group]={'selected':selected,'groups':detailed,'search_trace':trace,'reason':reason}
        if phase=='terminal':
            assert groups['A']['selected'] is None and groups['D']['selected'] is None
        records.append({'method':method,'phase':phase,'original_event_index':saved['event_index'],
                        'p0_case_path':str(path.relative_to(ROOT)),'state_digest':digest(state),
                        'request':req,'ast':ast,'results':groups,
                        'scope':'fixed current public state; no future arrival, branch continuation or full order replay'})
        print(method,phase,'recorded',flush=True)
write(HERE/'l0_rollback_fixed_states.json',{'records':records,'fixed_states':8,'new_api_attempts':0,
      'source_module':choose.__module__,'global_infeasibility':'NOT_PROVEN'})
