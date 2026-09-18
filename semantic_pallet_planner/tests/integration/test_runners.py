import copy
import json
import pytest
from semantic_pallet_planner.logging.artifacts import Experiment
from semantic_pallet_planner.runners.core import FixedCaseRunner,EpisodeRunner
from semantic_pallet_planner.evaluation.replay import validate_experiment
from semantic_pallet_planner.evaluation.metrics import describe
from semantic_pallet_planner.selectors.baselines import register


def test_stage1a_120_rows_and_reproduction(cfg,repo,generator):
    methods=['random_valid','geometry_greedy','handcrafted_rule','candidate_oracle']
    hashes=[]
    for identifier in ['first','second']:
        exp=Experiment(cfg,identifier)
        FixedCaseRunner(repo,exp).run(repo.list_cases('validation'),methods)
        EpisodeRunner(repo,generator,exp).run('SCN_0051','geometry_greedy')
        exp.finish();hashes.append(exp.manifest['core_result_sha256'])
        assert len(exp.decisions)==120
        assert all(r['oracle_hit'] and r['oracle_regret']==0 for r in exp.decisions if r['method']=='candidate_oracle')
        assert all(r['hard_violations']==0 for r in exp.decisions+exp.episodes)
        assert validate_experiment(exp.root,regenerate=True)['status']=='PASS'
        grouped={}
        for r in exp.decisions:grouped.setdefault(r['decision_case_id'],set()).add(r['candidate_set_id'])
        assert all(len(s)==1 for s in grouped.values())
    assert hashes[0]==hashes[1]


def test_future_selector_plug_in_and_render_failure(cfg,repo,generator,monkeypatch):
    class DummySelector:
        name='custom_test';privileged_input=False;future_visible=False
        def select(self,request,*,rng,memories=None):
            assert not {'split','oracle_candidate_id','candidate_evaluations'}.intersection(request)
            from semantic_pallet_planner.selectors.baselines import make_selector
            return make_selector('lowest').select(request,rng=rng)
    from semantic_pallet_planner.visualization import renderer
    def fail(*args):raise RuntimeError('injected renderer failure')
    monkeypatch.setattr(renderer,'render_episode',fail)
    hashes=[]
    for identifier,render in [('off',False),('on',True)]:
        exp=Experiment(cfg,identifier)
        row=EpisodeRunner(repo,generator,exp).run('SCN_0051','custom_test',max_steps=2,render=render,selector=DummySelector())
        exp.finish();hashes.append(exp.manifest['core_result_sha256'])
        assert row['termination_reason']=='max_steps_reached'
        if render:assert (exp.root/'episodes/custom_test/SCN_0051/render_error.json').exists()
    assert hashes[0]==hashes[1]


def test_detect_tampered_results(cfg,repo,generator):
    exp=Experiment(cfg,'tamper');EpisodeRunner(repo,generator,exp).run('SCN_0051','lowest',max_steps=1);exp.finish()
    p=exp.root/'metrics/per_episode.csv';p.write_text(p.read_text()+'corruption\n')
    assert validate_experiment(exp.root)['status']=='FAIL'


def test_summary_statistics():
    d=describe([1,2,3],123)
    assert d['n']==3 and d['mean']==2 and d['median']==2 and d['std']==1
    assert d['ci95'][0]<=2<=d['ci95'][1]


def test_internal_error_is_logged_and_not_silently_successful(cfg,repo):
    class BrokenGenerator:
        def generate(self,state):raise RuntimeError('injected generator error')
    exp=Experiment(cfg,'broken')
    row=EpisodeRunner(repo,BrokenGenerator(),exp).run('SCN_0051','geometry_greedy')
    exp.finish()
    assert row['termination_reason']=='internal_error' and not row['completed']
    event=json.loads((exp.root/'steps.jsonl').read_text())
    assert 'injected generator error' in event['error']


def test_fixed_abort_keeps_failed_decision_record(cfg,repo,monkeypatch):
    from semantic_pallet_planner.selectors.baselines import REGISTRY
    class Invalid:
        name='invalid_test';privileged_input=False;future_visible=False
        def select(self,*args,**kwargs):return ['not an object']
    monkeypatch.setitem(REGISTRY,'invalid_test',lambda:Invalid())
    cfg['fallback_policy']='abort';exp=Experiment(cfg,'aborted')
    FixedCaseRunner(repo,exp).run(['DC_00151'],['invalid_test']);exp.finish()
    assert len(exp.decisions)==1 and exp.decisions[0]['invalid_selector_response']


def test_visual_selector_input_hook(cfg,repo,generator,monkeypatch):
    from semantic_pallet_planner.visualization import renderer
    from semantic_pallet_planner.selectors.baselines import make_selector
    def fake(request,directory):
        q=copy.deepcopy(request);q['visual_inputs']={'workspace_image':'generated_work','candidate_montage':'generated_candidates'}
        return q
    monkeypatch.setattr(renderer,'prepare_visual_request',fake)
    class Visual:
        name='visual_hook_test';privileged_input=False;future_visible=False;requires_images=True
        def select(self,request,*,rng,memories=None):
            assert request['visual_inputs']['workspace_image']=='generated_work'
            return make_selector('lowest').select(request,rng=rng)
    exp=Experiment(cfg,'visual_hook')
    row=EpisodeRunner(repo,generator,exp).run('SCN_0051','visual_hook_test',selector=Visual(),max_steps=1)
    assert row['fallback_count']==0 and row['placed_count']==1


def test_deterministic_font_has_latin_and_chinese():
    from semantic_pallet_planner.visualization.renderer import _font,plt
    from matplotlib import font_manager
    from matplotlib.ft2font import FT2Font
    _font()
    first=tuple(plt.rcParams['font.family'])
    _font();assert tuple(plt.rcParams['font.family'])==first
    path=font_manager.findfont(font_manager.FontProperties(family=list(first)))
    assert set(map(ord,'PALLET 0123456789码垛候选')).issubset(FT2Font(path).get_charmap())
