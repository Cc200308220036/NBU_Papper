"""Offline layout supplement. Imports only saved GP4 plotting helpers, never production."""
import sys
from pathlib import Path
from unittest.mock import patch
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
ROOT=Path('semantic_pallet_planner/outputs')
OLD=ROOT/'GEOM_CANDIDATES_GP4_20261117_01'
NEW=ROOT/'GEOM_CANDIDATES_GP5_P0_20261117_01'
sys.path.insert(0,str(OLD))
import gp4_plots
# Redirect read paths to immutable saved input while sending only PNG to new output.
class SavedRoot:
 def __truediv__(self,name):return (NEW if name=='figures' else OLD)/name
gp4_plots.OUT=SavedRoot()
read_saved=gp4_plots.read
def read_one(path):
 value=read_saved(path)
 if Path(path).name=='comparison.json':value['states']=[r for r in value['states'] if r['point_id']==sys.argv[1]]
 return value
gp4_plots.read=read_one
original=Figure.savefig
records=[]
def layout(fig,*args,**kwargs):
 fig.set_size_inches(16,13)
 fig.subplots_adjust(left=.10,right=.97,bottom=.20,top=.90,hspace=.48,wspace=.40)
def save(fig,path,*args,**kwargs):
 from matplotlib.text import Text
 for t in fig.findobj(Text):t.set_clip_on(False)
 fig.set_dpi(100)
 fig.canvas.draw()
 renderer=fig.canvas.get_renderer()
 clipped=[]
 for ax in fig.axes:
  for t in [ax.title,ax.xaxis.label,ax.yaxis.label,*ax.get_xticklabels(),*ax.get_yticklabels()]:
   if t.get_visible() and t.get_text():
    b=t.get_window_extent(renderer)
    if b.x0<0 or b.y0<0 or b.x1>fig.bbox.width or b.y1>fig.bbox.height:clipped.append(t.get_text())
 records.append({'point':Path(path).stem,'text_outside_canvas':clipped,'axes':len(fig.axes),'limits':[[list(a.get_xlim()),list(a.get_ylim())] for a in fig.axes],'aspect':[a.get_aspect() for a in fig.axes]})
 assert not clipped
 kwargs['dpi']=100
 return original(fig,path,*args,**kwargs)
with patch.object(Figure,'tight_layout',layout),patch.object(Figure,'savefig',save):gp4_plots.plots()
import json
(NEW/('layout_'+sys.argv[1]+'.json')).write_text(json.dumps(records,indent=2)+'\n')
