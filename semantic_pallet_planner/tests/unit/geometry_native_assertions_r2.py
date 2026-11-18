"""Test-layer assertions only. No production imports or state transitions."""
import math
import struct


def same_native(a,b):
    if type(a) is not type(b):return False
    if type(a) is float:return struct.pack('>d',a)==struct.pack('>d',b)
    if type(a) is list:return len(a)==len(b) and all(same_native(x,y) for x,y in zip(a,b))
    if type(a) is dict:return set(a)==set(b) and all(same_native(a[k],b[k]) for k in a)
    return a==b


def assert_event_shape(event):
    """Resolve the selected candidate and its actual public pending source item."""
    selected=event['selection']['selected_candidate_id']
    matches=[c for c in event['bundle']['physical_candidates'] if c['candidate_id']==selected]
    assert len(matches)==1,'selected candidate missing or ambiguous'
    candidate=matches[0];pick=candidate['pick_item_id']
    sources=[p['item'] for p in event['before']['pending_items'] if p['item']['item_id']==pick]
    assert len(sources)==1,'selected pending source missing or ambiguous'
    source=sources[0];yaw=candidate['pose']['yaw_deg']
    assert type(yaw) is int and yaw in (0,90),'invalid native yaw'
    axes=('length','width','height') if yaw==0 else ('width','length','height')
    expected=[source['dimensions_mm'][k] for k in axes]
    assert all(type(x) in (int,float) and x>0 and math.isfinite(x) for x in expected),'invalid source sizes'
    assert same_native(candidate['oriented_size_mm'],expected),'selected candidate size/type/bit mismatch'
    if event.get('event')=='PLACE':
        after=[x for x in event['after']['placed_items'] if x['item_id']==pick]
        assert len(after)==1,'committed selected item missing or ambiguous'
        assert same_native(after[0]['oriented_size_mm'],expected),'committed size/type/bit mismatch'
        assert same_native(after[0]['dimensions_mm'],source['dimensions_mm']),'source dimensions changed'
        assert same_native(after[0]['pose'],candidate['pose']),'exact selected pose changed'
        assert same_native(event['action'],event['proposed_action']),'action drift'
    return {'candidate_id':selected,'pick_item_id':pick,'yaw':yaw,'source_dimensions_mm':source['dimensions_mm'],'expected_oriented_size_mm':expected,'native_types':[type(x).__name__ for x in expected],
            'float_bits':[struct.pack('>d',x).hex() if type(x) is float else None for x in expected]}


def assert_episode_shapes(episode):
    return [assert_event_shape(e) for e in episode['events'] if e.get('event')=='PLACE']
