"""Layout-only wrapper; frozen plot data/rules stay unchanged. Same five files."""
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from unittest.mock import patch
from gp4_plots import plots

def layout(fig,*a,**kw):fig.subplots_adjust(left=.08,right=.98,bottom=.18,top=.91,hspace=.40,wspace=.22)
with patch.object(Figure,'tight_layout',layout):plots()
