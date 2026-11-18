"""Exact expected exception class AND code, with no blanket exception acceptance."""

def expect_rejection(label,fn,expected_type,expected_code):
    try:fn()
    except Exception as exc:
        if type(exc) is expected_type and getattr(exc,'code',None)==expected_code:
            return {'case':label,'status':'EXPECTED_REJECTION','exception_type':type(exc).__name__,'code':exc.code,'detail':str(exc)}
        exc.add_note('Unexpected rejection for '+label+'; expected '+expected_type.__name__+':'+expected_code)
        raise
    raise AssertionError('EXPECTED_REJECTION_MISSING:'+label)

def snapshot_variant(native_raw,geometry_raw,kind):
    """Positive baseline first, then exactly one native leaf type/sign change.

    Original geometry bytes retained so the changed input must be rejected.
    Does not select another field/value if the required zero/int is absent.
    """
    import copy,struct
    from semantic_pallet_planner.jev_select.geometry_runtime_contracts import decode,encode,NATIVE,same_native
    from semantic_pallet_planner.jev_select.geometry_runtime_input import validate_runtime_views_v1
    validate_runtime_views_v1(native_raw,geometry_raw)
    native=decode(native_raw);changed=copy.deepcopy(native)
    leaf=changed['current_state']['placed_items'][0]
    if kind=='type':
        before=leaf['oriented_size_mm'][0];assert type(before) is int
        after=float(before);assert int(after)==before
        leaf['oriented_size_mm'][0]=after;path='/current_state/placed_items/0/oriented_size_mm/0'
    elif kind=='sign':
        before=leaf['pose']['x_mm'];assert type(before) is float and struct.pack('>d',before)==bytes(8),'POSITIVE_FLOAT_ZERO_BASELINE_REQUIRED'
        after=-0.0;leaf['pose']['x_mm']=after;path='/current_state/placed_items/0/pose/x_mm'
        assert struct.pack('>d',before).hex()=='0000000000000000' and struct.pack('>d',after).hex()=='8000000000000000'
    else:raise ValueError('UNKNOWN_MUTATION')
    from geometry_native_assertions_r2 import same_native as exact
    differences=[]
    def walk(a,b,path=''):
        if exact(a,b):return
        if type(a) is dict and type(b) is dict and set(a)==set(b):
            for k in a:walk(a[k],b[k],path+'/'+k)
        elif type(a) is list and type(b) is list and len(a)==len(b):
            for i,(x,y) in enumerate(zip(a,b)):walk(x,y,path+'/'+str(i))
        else:differences.append(path)
    walk(native,changed);assert differences==[path],differences
    return encode(changed),{'positive_baseline':'PASS_ORIGINAL_VALIDATOR','path':path,'before_type':type(before).__name__,'after_type':type(after).__name__,'before_bits':struct.pack('>d',before).hex() if type(before) is float else None,'after_bits':struct.pack('>d',after).hex(),'only_changed_paths':differences,'geometry_bytes_unchanged':True}
