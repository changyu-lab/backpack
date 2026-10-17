import os,sys,json,subprocess,argparse,csv
from pathlib import Path
os.environ['MPLCONFIGDIR']='I:/vvenc-LFNST/.worktrees/sibrc300-mplconfig'
sys.dont_write_bytecode=True
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010/metrics360')
SKILL=Path('I:/vvenc-LFNST/.codex/skills/scipilot-figure-skill/scripts');sys.path.insert(0,str(SKILL))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from setup_style import setup_style
from visual_qa import render_preview,audit_layout
from export_figure import export_figure
from PIL import Image,ImageOps
import numpy as np
parser=argparse.ArgumentParser();parser.add_argument('--export',action='store_true');parser.add_argument('--bitrate-only',action='store_true');args=parser.parse_args()
if args.bitrate_only:
 rows=list(csv.DictReader((D/'bitrate_eda.csv').open()));points=[]
 for target in sorted({int(r['target_bps']) for r in rows}):
  for method,token in [('Anchor','anchor'),('SIBRC','full')]:
   matching=[r for r in rows if int(r['target_bps'])==target and r['method']==method];assert len(matching)==300
   points.append({'name':'rc300_'+token+'_R','target_bps':target,'picture_bitrate_bps':[int(r['bits'])*30 for r in matching]})
else:points=json.loads((D/'assessment.json').read_text())['points']
targets=sorted({q['target_bps'] for q in points})
if not args.export:
 with (D/'frame_data_profile.txt').open('w',encoding='utf8') as f:subprocess.run([sys.executable,str(SKILL/'profile_data.py'),str(D/('bitrate_eda.csv' if args.bitrate_only else 'frames.csv')),'--group','method','--group','target_bps'],stdout=f,stderr=subprocess.STDOUT,check=True)
style=setup_style(journal='ieee',lang='en',constrained_layout=False)
plt.rcParams.update({'savefig.bbox':None,'font.size':9,'axes.labelsize':9,'axes.titlesize':9,'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':9})
audits={}
metrics=[('picture_bitrate_bps','Frame bitrate (Mbps)','frame_bitrate'),('picture_y_spsnr','Y-S-PSNR-NN (dB)','frame_spsnr')]
for metric,label,base in (metrics[:1] if args.bitrate_only else metrics):
 fig,axes=plt.subplots(2,2,figsize=(7.16,4.9));fig.subplots_adjust(left=.095,right=.98,bottom=.10,top=.89,wspace=.27,hspace=.39)
 for index,(ax,target) in enumerate(zip(axes.flat,targets)):
  for token,name,color,ls in [('_anchor_','VTM-RC@VVenC anchor','#D55E00',':'),('_full_','SIBRC','#0072B2','-')]:
   q=next(q for q in points if q['target_bps']==target and token in q['name']);ys=np.asarray(q[metric]);ys=ys/1e6 if metric=='picture_bitrate_bps' else ys
   assert len(ys)==300 and np.all(np.isfinite(ys))
   ax.plot(np.arange(300),ys,color=color,linestyle=ls,marker='.',markersize=1.8,linewidth=.65,label=name)
  if metric=='picture_bitrate_bps':ax.set_yscale('log')
  ax.set_xlim(0,300);ax.set_xticks([0,50,100,150,200,250,300]);ax.set_xlabel('Frame');ax.set_ylabel(label)
  ax.set_title('('+chr(97+index)+') Target '+f'{target/1e6:.3f}'+' Mbps',loc='left')
  ax.grid(True,which='major',color='.88',linewidth=.5);ax.spines['top'].set_visible(False);ax.spines['right'].set_visible(False)
 fig.legend(*axes.flat[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.53,.995),ncol=2,frameon=False)
 audits[base]=audit_layout(fig);print(base,audits[base]);assert not any(level=='FAIL' for level,msg in audits[base])
 render_preview(fig,str(D/(base+'_preview.png')),dpi=180)
 if args.export:
  export_figure(fig,str(D/base),formats=['pdf','svg','png'],dpi=600,size_inches=(7.16,4.9),grayscale_preview=False,tight=False)
  with Image.open(D/(base+'.png')) as im:ImageOps.grayscale(im).save(D/(base+'_grayscale.png'),dpi=(600,600))
 plt.close(fig)
if args.export:
 (D/'frame_caption.txt').write_text('AerialCity ERP, 3840x1920, 300 frames, LDP, VVenC 1.12.0 faster. Red dotted: VTM-RC@VVenC anchor; blue solid: SIBRC full I/P. Four targets derived from CQP 37/32/27/22. Frame bitrate is encoder POC bits multiplied by 30 fps and shown on a logarithmic ordinate to retain the complete first-I-frame peak and P-frame fluctuations. S-PSNR-NN is luma quality using the original 360Lib and 655362 standard spherical samples. Both plots include every frame 0..299, with no smoothing, clipping or interpolation between missing data.',encoding='utf8')
(D/'frame_layout_audit.json').write_text(json.dumps({'style':style,'audits':audits},indent=2),encoding='utf8')
