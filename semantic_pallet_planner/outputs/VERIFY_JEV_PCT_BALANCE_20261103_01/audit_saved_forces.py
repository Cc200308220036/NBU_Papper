"""Independent arithmetic audit of saved forces, without calling the solver."""
from pathlib import Path
import json
import math
import sys
out=Path(sys.argv[1]);rows=[]
for path in sorted((out/'fixtures_v2').glob('*.json')):
    if path.name=='index.json':continue
    f=json.loads(path.read_text());r=f['result']
    kind='accepted_conservative_network' if r['status']=='STABLE' else 'physical_witness_only_not_stable_acceptance'
    reaction=r['diagnostics'].get('reactions') if r['status']=='STABLE' else r['diagnostics'].get('physical_feasibility_witness',{}).get('reactions')
    if not reaction:continue  # geometry precheck / certified infeasibility has no accepted force vector
    boxes=[*f['state']['placed'],f['candidate']]
    container=f['state']['container_mm']
    centers={b['item_id']:[b['bottom_center_mm'][0]+container[0]/2,b['bottom_center_mm'][1]+container[1]/2] for b in boxes}
    local=[]
    for b in boxes:
        outgoing=[e for e in reaction if e['upper']==b['item_id']]
        incoming=[e for e in reaction if e['lower']==b['item_id']]
        mr=math.fsum(e['mass_kg'] for e in outgoing)-b['mass_kg']-math.fsum(e['mass_kg'] for e in incoming)
        mom=[math.fsum(e['mass_kg']*e['point_mm'][d] for e in outgoing)-b['mass_kg']*centers[b['item_id']][d]-math.fsum(e['mass_kg']*e['point_mm'][d] for e in incoming) for d in (0,1)]
        assert abs(mr)<1e-8 and max(abs(v) for v in mom)<1e-6,(f['fixture'],b['item_id'],mr,mom)
        local.append(dict(item_id=b['item_id'],mass_residual_kg=mr,moment_residual_kg_mm=mom))
    ground=[e for e in reaction if e['lower'] is None]
    mass=math.fsum(e['mass_kg'] for e in ground)-sum(b['mass_kg'] for b in boxes)
    moment=[math.fsum(e['mass_kg']*e['point_mm'][d] for e in ground)-math.fsum(b['mass_kg']*centers[b['item_id']][d] for b in boxes) for d in (0,1)]
    assert abs(mass)<1e-8 and max(abs(v) for v in moment)<1e-6
    assert min(e['mass_kg'] for e in reaction)>=0
    rows.append(dict(fixture=f['fixture'],role=kind,local=local,global_mass_residual_kg=mass,global_moment_residual_kg_mm=moment,nonnegative=True))
record=dict(method='independent arithmetic over saved input own masses/centers and physical force points; no production solver/residual helper called',checks=rows,tolerances=dict(mass_kg=1e-8,moment_kg_mm=1e-6),analytic_triangle_center_witness_kg=[5/6,5/6,4/3])
(out/'independent_physical_audit.json').write_text(json.dumps(record,indent=2)+'\n')
print('independent audited force sets',len(rows))
