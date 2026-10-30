"""Declared tasks and hand-derived gold values; never import runtime interpreters."""
import copy
from .common import O4Error
from .observation import build_observation,rebind

CONTAINER={'container_id':'O4_GOLD','length_mm':1000,'width_mm':1000,'max_height_mm':1000,
           'max_payload_kg':1000,'coordinate_frame':'container_bottom_center'}
ALL={'all':True}

def eq(field,value):return {'eq':{'field':field,'value':value}}
def rule(identifier='r1',kind='max_top_load',target=None,limit=2.,priority=20,overrides=()):
    r={'rule_id':identifier,'type':kind,'priority':priority,'overrides':list(overrides)}
    if kind=='forbidden_contact':r.update(left=eq('cargo_category','food'),right=eq('cargo_category','household_cleaner'))
    else:r['target']=copy.deepcopy(target if target is not None else ALL)
    if kind=='max_top_load':r['limit']={'field':'labels.max_top_load_kg'} if limit=='label' else {'constant_kg':float(limit)}
    return r

def policy(rules):return {'schema_version':'o4_policy_v1','rules':copy.deepcopy(rules)}

def task_policy(index):
    """Six independent declarative task specifications (private reference)."""
    a=rule(limit='label')
    b=rule('r2','no_top_load',eq('labels.no_top_load',True),priority=10,overrides=('r1',))
    c=rule('r3',target={'and':[eq('cargo_category','glassware'),eq('packaging.reinforced',True),eq('labels.no_top_load',False)]},limit=2,priority=0,overrides=('r1',))
    d=rule('r4','forbidden_contact')
    options=[[a],[a,b],[d],[rule(target={'and':[eq('cargo_category','glassware'),eq('fragile',True)]},limit=1)], [a,b,c],[a,b,c,d]]
    return policy(options[index])


def render_selector(s,reverse=False):
    """Independent text producer using documented controlled grammar."""
    names={'cargo_category':'货物类别','packaging.reinforced':'包装加固','labels.no_top_load':'禁压标记',
           'labels.max_top_load_kg':'标签限载','physical_top_load_limit_kg':'物理限载','mass_kg':'质量','fragile':'易碎','weight_class':'重量等级'}
    words={'food':'食品','glassware':'玻璃制品','electronics':'电子产品','household_cleaner':'清洁用品','general':'其他',
           'light':'轻','medium':'中','heavy':'重'}
    op,v=next(iter(s.items()))
    if op=='all':return '全部箱体'
    if op=='object_ids':return '对象（'+','.join(v)+'）'
    if op in ('and','or'):
        children=list(reversed(v)) if reverse else v
        return ('同时满足' if op=='and' else '任一满足')+'（'+'，'.join(render_selector(c,reverse) for c in children)+'）'
    if op=='not':return '不满足（'+render_selector(v,reverse)+'）'
    value=v['value']
    if isinstance(value,bool):value='是' if value else '否'
    elif isinstance(value,(float,int)):value=f'{value:g}kg'
    else:value=words[value]
    return names[v['field']]+{'eq':'等于','lt':'小于','le':'不大于','gt':'大于','ge':'不小于'}[op]+value


def render_policy(ast,paraphrase=False):
    if not ast['rules']:return '无额外业务硬约束。'
    lines=[]
    for r in (list(reversed(ast['rules'])) if paraphrase else ast['rules']):
        if r['type']=='forbidden_contact':
            left,right=(r['right'],r['left']) if paraphrase else (r['left'],r['right'])
            body='禁止（'+render_selector(left,paraphrase)+'）与（'+render_selector(right,paraphrase)+'）直接面接触'
        else:
            action='禁止顶部加载' if r['type']=='no_top_load' else ('累计顶部限载按标签' if 'field' in r['limit'] else f"累计顶部限载为{r['limit']['constant_kg']:g}kg")
            body='对（'+render_selector(r['target'],paraphrase)+'），'+action
        lines.append(f"规则{r['rule_id']}：{body}；优先级{r['priority']}；覆盖{','.join(r['overrides']) or '无'}。")
    return ('\n ' if paraphrase else '').join(lines)


def item(identifier,category='general',no_top=False,label=5.,reinforced=False,mass=1.,x=0,z=0,size=(100,100,100)):
    return {'item_id':identifier,'mass_kg':mass,'dimensions_mm':dict(zip(('length','width','height'),size)),
            'stackable':True,'fragile':category=='glassware','weight_class':'light','top_load_limit_kg_synthetic':100.,
            'product_category':'electronics' if category=='electronics' else 'general',
            'pose':{'x_mm':x,'y_mm':0.,'z_base_mm':z,'yaw_deg':0},'oriented_size_mm':list(size),
            '_attributes':{'object_id':identifier,'cargo_category':category,'packaging':{'reinforced':reinforced},
                'labels':{'no_top_load':no_top,'max_top_load_kg':label},'physical_top_load_limit_kg':100.}}


def fixture_request(placed,available,ast,identifier='gold'):
    attributes={i['item_id']:i['_attributes'] for i in [*placed,available]}
    req=build_observation({'request_id':identifier,'container':CONTAINER,'placed_items':placed,'available_items':[available]},attributes,render_policy(ast))
    return req


def candidate(identifier='TOP',pick='top',x=0,y=0,z=100,size=(100,100,100)):
    return {'candidate_id':identifier,'pick_item_id':pick,'pose':{'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':0},'oriented_size_mm':list(size)}


def gold_cases():
    """Expected target/load/threshold values are arithmetic declarations, not interpreter outputs."""
    out=[]
    def add(group,index,placed,top,ast,c,loads,limits,targets,active,contacts=()):
        expected={'loads_kg':loads,'limits_kg':limits,'applicable_objects':targets,'active_rules':active,
                  'contact_pairs':[list(p) for p in contacts]}
        bad=sorted([f'load:{i}' for i,v in limits.items() if loads[i]>v+1e-6]+['contact:'+':'.join(p) for p in contacts])
        expected['violations']=bad
        out.append({'case_id':f'{group}_{index}','group':group,'request':fixture_request(placed,top,ast,f'O4_GOLD_{len(out)+1:03d}'),
                    'reference_policy':ast,'candidates':[c],'expected_after':expected,'expected_allowed_ids':[] if bad else [c['candidate_id']],
                    'manual_review_status':'PENDING_HUMAN_REVIEW'})
    for i,mass in enumerate((1.,0.,1e-6,2e-6,2.,1.),1):
        base=item('base');top=item('top',mass=mass)
        c=candidate(z=0,x=300) if i==5 else candidate()
        placed=[base];loads={'base':0. if i==5 else mass,'top':0.};active={'base':['r1'],'top':[]}
        if i==6:
            mid=item('mid',z=100,mass=0.)
            placed.append(mid);loads['mid']=mass;active['mid']=[];c=candidate(z=200)
        ast=policy([rule(kind='no_top_load',target={'object_ids':['base']})])
        add('no_top_load',i,placed,top,ast,c,loads,{'base':0.},{'r1':['base']},active)
    for i,mass in enumerate((1.,2.,2.0000005,2.000002,3.,4.),1):
        base=item('base');top=item('top',mass=mass);placed=[base];c=candidate();loads={'base':mass,'top':0.}
        target={'object_ids':['base']};limits={'base':2.};active={'base':['r1'],'top':[]};targets={'r1':['base']}
        if i==5:
            placed.append(item('mid',mass=1.,z=100));c=candidate(z=200)
            loads={'base':4.,'mid':3.,'top':0.};active['mid']=[]
        if i==6:
            placed=[item('base',x=-50),item('right',x=50)];top=item('top',mass=4.,size=(200,100,100));c=candidate(size=(200,100,100))
            loads={'base':2.,'right':2.,'top':0.};active['right']=[]
        add('max_top_load',i,placed,top,policy([rule(target=target)]),c,loads,limits,targets,active)
    for i in range(1,7):
        reverse=i==6;base=item('base',category='household_cleaner' if reverse else 'food');top=item('top',category='food' if reverse else 'household_cleaner')
        c=[candidate(x=100,z=0),candidate(x=100,y=100,z=0),candidate(x=100,y=50,z=0),candidate(),candidate(x=101,z=0),candidate(x=100,z=0)][i-1]
        contacts=[('base','top')] if i in (1,3,4,6) else []
        targets={'r1':{'left':['top'] if reverse else ['base'],'right':['base'] if reverse else ['top']}}
        add('forbidden_contact',i,[base],top,policy([rule(kind='forbidden_contact')]),c,{'base':1. if i==4 else 0.,'top':0.},{},targets,{'base':[],'top':[]},contacts)
    selectors=[ALL,{'object_ids':['base']},{'or':[eq('cargo_category','food'),eq('cargo_category','glassware')]},
        {'not':eq('cargo_category','food')},{'and':[eq('cargo_category','glassware'),eq('fragile',True)]},{'object_ids':['top']}]
    for i,selector in enumerate(selectors,1):
        targets=['base','top'] if i==1 else (['top'] if i==6 else ['base'] if i in (2,3,5) else ['base','top'])
        limits={k:2. for k in targets};active={k:['r1'] if k in targets else [] for k in ('base','top')}
        add('sets',i,[item('base',category='glassware')],item('top',mass=3.),policy([rule(target=selector)]),candidate(),{'base':3.,'top':0.},limits,{'r1':targets},active)
    conditions=[{'lt':{'field':'mass_kg','value':1}}, {'le':{'field':'mass_kg','value':1}},
        {'gt':{'field':'mass_kg','value':1}}, {'ge':{'field':'mass_kg','value':1}},
        {'and':[eq('packaging.reinforced',True),{'not':eq('labels.no_top_load',True)}]},eq('labels.no_top_load',True)]
    for i,selector in enumerate(conditions,1):
        targets={1:[],2:['base'],3:['top'],4:['base','top'],5:['base'],6:[]}[i]
        add('conditions',i,[item('base',reinforced=True)],item('top',mass=3.),policy([rule(target=selector)]),candidate(),
            {'base':3.,'top':0.},{k:2. for k in targets},{'r1':targets},{k:['r1'] if k in targets else [] for k in ('base','top')})
    portraits=[('food',True,0,False,0),('glassware',False,1,False,1),('glassware',False,5,True,2),
               ('glassware',True,0,True,0),('electronics',False,8,True,8),('household_cleaner',False,6,False,6)]
    for i,(cat,nt,label,reinforced,limit) in enumerate(portraits,1):
        ast=task_policy(5);active_base=['r2'] if nt else ['r3'] if i==3 else ['r1']
        targets={'r1':['base','top'],'r2':['base'] if nt else [],'r3':['base'] if i==3 else [],
                 'r4':{'left':['base'] if cat=='food' else [],'right':['base'] if cat=='household_cleaner' else []}}
        add('overrides',i,[item('base',cat,nt,label,reinforced)],item('top',mass=3.),ast,candidate(),
            {'base':3.,'top':0.},{'base':float(limit),'top':5.},targets,{'base':active_base,'top':['r1']})
    return out
