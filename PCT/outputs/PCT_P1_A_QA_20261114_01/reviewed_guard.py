import sys,unittest
violations=[]
def profile(frame,event,arg):
    if event!='call':return
    module=frame.f_globals.get('__name__','');name=frame.f_code.co_name
    forbidden=(module.startswith('semantic_pallet_planner') and (
        name in ('run_episode','_run_episode_v2','commit_physical','assess_candidate','monitor_selected_action') or
        (name in ('generate','_generate') and ('.planner.' in module or '.o4.' in module)) or
        '.transport' in module)) or (module.startswith('scipy.optimize') and name=='linprog')
    if forbidden:
        violations.append([module,name]);raise AssertionError('unauthorized business dispatch '+str(violations[-1]))
sys.setprofile(profile)
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('PCT/tests'))
sys.setprofile(None)
assert result.wasSuccessful() and not result.skipped and result.testsRun==20,(result.testsRun,result.skipped)
assert not violations,violations
print('20 passed, zero skips; order/candidate-generation/LP/monitor/transport call violations:',violations)
