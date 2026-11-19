"""Independent expected timing derived from returned recovery events, test only."""
import copy,math

def expected_timings(events):
    samples=[e.get('timings',{}) for e in events if e.get('decision_id') or e.get('timings')]
    groups={key:[s.get(key) for s in samples] for key in {k for s in samples for k in s if k.endswith('_s')}}
    monitors=[e['monitor'] for e in events if e.get('monitor')]
    groups['monitor_result_duration_s']=[(m.get('result') or {}).get('duration_s') for m in monitors]
    expected={};partial=[]
    for key,values in groups.items():
        numbers=[v for v in values if v is not None]
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in numbers):raise AssertionError('INVALID_TIMING_SAMPLE')
        if not numbers:continue
        name=key if len(numbers)==len(values) else 'measured_partial/'+key
        expected[name]=sum(numbers)
        if name!=key:partial.append(key)
    return expected,partial

def assert_recovery_timing(events,summary,*,phase):
    before=copy.deepcopy(events);expected,partial=expected_timings(events)
    rows=summary['timings'];actual={r['segment']:r['seconds'] for r in rows}
    assert len(actual)==len(rows),'DUPLICATE_TIMING_SEGMENT'
    # invocation_wall_s is an independently measured outer driver duration.
    relevant={k:v for k,v in actual.items() if k!='invocation_wall_s'}
    assert relevant==expected,'EVENT_DERIVED_TIMING_MISMATCH'
    for key in partial:assert key not in actual,'PARTIAL_REPORTED_AS_COMPLETE'
    decision_samples=[e.get('timings',{}).get('decision_wall_s') for e in events if e.get('decision_id') or e.get('timings')]
    if phase=='COMMITTED':
        assert any(type(v) in (int,float) for v in decision_samples) and None in decision_samples,'COMMITTED_REGRESSION_FIXTURE_MUST_BE_MIXED'
        assert 'decision_wall_s' not in actual and actual['measured_partial/decision_wall_s']==sum(v for v in decision_samples if v is not None),'COMMITTED_PARTIAL_TIMING_REQUIRED'
    assert events==before,'EVENT_TIMING_MUTATED'
    return {'phase':phase,'expected_from_events':expected,'partial_segments':partial,'status':'PASS','events_unchanged':True,'complete_wall_unavailable':phase=='COMMITTED'}
