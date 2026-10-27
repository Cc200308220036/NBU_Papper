"""Cold/hot costs in three independent processes; no historical latency reuse."""
import json
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent


def percentile(values,p):
    values=sorted(values);pos=(len(values)-1)*p;i=int(pos)
    return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(pos-i)


processes=[json.loads((HERE/f'timing_process_{i}.json').read_text()) for i in (1,2,3)]
# Sandboxed execs can have different PID namespaces and repeat numeric pids;
# process identity is distinct invocation/output, not solely os.getpid().
assert all(len(p['rows'])==24 and not p['new_api_attempts'] for p in processes)
rows=[r for p in processes for r in p['rows']]
assert len(rows)==72 and all(r['hot_root_hit'] and r['logical_evaluations']<=256 for r in rows)
aggregates=[];passed=True
for method in ('single','buffer_search'):
    for field in ('seconds','hot_seconds'):
        groups={g:[r[field] for r in rows if r['method']==method and r['group']==g] for g in ('A','F')}
        stats={g:{'n':len(v),'median':statistics.median(v),'p95':percentile(v,.95),'min':min(v),'max':max(v)} for g,v in groups.items()}
        ratios={k:stats['F'][k]/max(.001,stats['A'][k]) for k in ('median','p95')}
        ok=ratios['median']<=2 and ratios['p95']<=3;passed &= ok
        aggregates.append({'method':method,'cache':'cold' if field=='seconds' else 'hot','stats':stats,'ratios':ratios,'pass':ok})
result={'status':'PASS' if passed else 'HOLD_COST','valid_process_invocations':3,'aborted_instrumentation_processes':1,'total_started_processes':4,'cold_calls':72,'hot_calls':72,
        'sample_scope':'six frozen core tasks x two methods x A/F x three processes; same saved fourth decision',
        'T0_calls_added':0,'performance_orders_added':0,'minimum_denominator_seconds':.001,'aggregates':aggregates,
        'cost_gate':'both cold/hot: median<=2x, p95<=3x; no V2-D timing reused',
        'component_scope':'root candidate sampling includes full quality; isolated quality remeasurement is a separate metadata-only diagnostic, AST/placement work=0',
        'new_api_attempts':0}
with (HERE/'cost_audit.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
