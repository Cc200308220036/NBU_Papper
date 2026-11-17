"""Fixed hand-worked number illustrations; stdlib only, no project imports/API.
Not a production bridge, candidate generator, physical check or acceptance test.
"""
import hashlib,json,math,struct
from fractions import Fraction
from decimal import Decimal
from pathlib import Path
OUT=Path(__file__).parent
# Each expected target is specified by hand, not obtained from a bridge function.
rows=[('I0',[100,80,60],0,[100.0,80.0,60],[100,80,60]),
 ('I90',[100,80,60],90,[80.0,100.0,60],[80,100,60]),
 ('F0',[100.0,80.5,60.25],0,[100.0,80.5,60.25],[100.0,80.5,60.25]),
 ('F90',[100.0,80.5,60.25],90,[80.5,100.0,60.25],[80.5,100.0,60.25]),
 ('M0',[100,80.0,60],0,[100.0,80.0,60],[100,80.0,60]),
 ('M90',[100,80.0,60],90,[80.0,100.0,60],[80.0,100,60])]
examples=[]
for name,source,yaw,raw,target in rows:
 expected=source if yaw==0 else [source[1],source[0],source[2]]
 assert [type(v) for v in target]==[type(v) for v in expected]
 axes=[]
 for a,b,origin in zip(raw,target,expected):
  assert type(a) in (int,float) and type(b) in (int,float) and a>0 and b>0
  assert Fraction(a)==Fraction(b)
  assert (str(b) if type(b) is int else struct.pack('>d',b).hex())==(str(origin) if type(origin) is int else struct.pack('>d',origin).hex())
  axes.append({'raw_type':type(a).__name__,'raw_bits':struct.pack('>d',a).hex() if type(a) is float else None,
    'target_type':type(b).__name__,'target_bits':struct.pack('>d',b).hex() if type(b) is float else None,
    'raw_ratio':[str(Fraction(a).numerator),str(Fraction(a).denominator)],
    'target_ratio':[str(Fraction(b).numerator),str(Fraction(b).denominator)],'strict_value_equal':True})
 examples.append({'case':name,'source':source,'yaw':yaw,'hand_raw':raw,'hand_target':target,'axes':axes,'status':'HAND_ARITHMETIC_CHECKED_NOT_GENERATED'})
negative=[]
for name,a,b in [('near_integer',99.99999999999999,100),('binary64_adjacent',0.30000000000000004,0.3),('height_difference',2.0004,2),('large_integer_loss',9007199254740992.0,9007199254740993)]:
 assert Fraction(a)!=Fraction(b);negative.append({'case':name,'a':repr(a),'b':repr(b),'expected':'VALUE_MISMATCH_REJECT','hand_rational_inequality':True})
assert int(float(9007199254740993))!=9007199254740993
assert int(float(9007199254740994))==9007199254740994
assert Fraction(0.1)==Fraction(3602879701896397,36028797018963968)
assert Fraction(0.1)!=Fraction(1,10)
assert struct.pack('>d',-0.0)!=struct.pack('>d',0.0)
assert float(Decimal('1e-400'))==0.0 and Decimal('1e-400')!=0
assert math.isfinite(5e-324) and 5e-324>0
try:float(10**400)
except OverflowError:overflow=True
else:overflow=False
assert overflow
result={'version':'geometry_gp5_num_n0_hand_examples_v1','positive':examples,'negative':negative,
 'special':{'2^53+1':'not exactly binary64 representable','2^53+2':'exactly representable; no physical eligibility claim',
 '0.1':'exact binary ratio differs from decimal 1/10; original geometry profile unchanged',
 'signed_zero':'pose bit identity differs; dimensions nonpositive rejected by proposed design',
 'underflow':'source Decimal 1e-400 nonzero but binary64 zero; source-lexeme guard required, not recoverable from old zero',
 'subnormal':'5e-324 finite and positive; no candidate/physics eligibility claim','10^400':'binary64 overflow'},
 'local_checks':'STDLIB_FIXED_ARITHMETIC_ONLY','candidate_generation':0,'production_imports':0,
 'proposed_bridge_calls':0,'physical_checks':0,'orders_monitors_kernels':0}
(OUT/'hand_examples.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('PASS: six hand-specified type/yaw rows, four rational inequalities and fixed representability/bit/underflow examples; no production imports or calls')
