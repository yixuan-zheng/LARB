"""Server-clock diagnostic timeline for the passing real 1C run."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
root=args.root
worker=[json.loads(l) for l in (root/'worker.jsonl').read_text().splitlines()]
scheduler=[json.loads(l) for l in (root/'scheduler.jsonl').read_text().splitlines()]
admit={e['key']:e for e in scheduler if e['event']=='admission_decision'}
modes=['full','arrival','admission','live']
fig,axes=plt.subplots(1,4,figsize=(13,4.5),sharex=True,sharey=True)
max_end=0
for ax,mode,title in zip(axes,modes,['Full thinking','Arrival-only','Admission-only','Live updates']):
    records=[json.loads((root/'requests'/f'{mode}-{i:02d}.json').read_text()) for i in range(6)]
    epoch=min(r['received'] for r in records)
    for i,r in enumerate(records):
        key=r['key'];start=r['received']-epoch;execution=admit[key]['monotonic']-epoch;end=r['monotonic']-epoch
        max_end=max(max_end,end)
        ax.barh(i,execution-start,left=start,color='#d3d9e0',height=.56)
        ax.barh(i,end-execution,left=execution,color='#3477a8',height=.56)
        for e in worker:
            if e.get('key')==key and e['event']=='live_reduction':
                ax.plot(e['monotonic']-epoch,i,marker='v',color='#17212b',ms=6)
            if e.get('key')==key and e['event']=='cue_started':
                ax.plot(e['monotonic']-epoch,i,marker='x',color='#d65a18',ms=8,mew=2)
    burst=records[2]['received']-epoch
    ax.axvline(burst,color='#89919b',ls=':',lw=1)
    ax.set_title(title,fontsize=11,fontweight='bold')
    ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    ax.set_yticks(range(6))
for ax in axes:
    ax.set_xlim(0,max_end*1.04)
axes[0].set_ylabel('Development problem index')
axes[0].invert_yaxis()
fig.supxlabel('Seconds from first server receipt in each phase (diagnostic)',y=.12,fontsize=10)
fig.suptitle('Week 4 admission/live mechanism: 24 real requests, all 176 checks passed',fontsize=13,fontweight='bold')
fig.legend(handles=[Patch(color='#d3d9e0',label='Queue'),Patch(color='#3477a8',label='Execution through final answer'),
    Line2D([],[],color='#17212b',marker='v',ls='',label='Budget reduced during generation'),
    Line2D([],[],color='#d65a18',marker='x',ls='',label='Forced cue starts')],
    loc='lower center',ncol=4,frameon=False,fontsize=9,bbox_to_anchor=(.5,.015))
fig.subplots_adjust(left=.06,right=.99,top=.84,bottom=.25,wspace=.12)
out=root/'analysis';out.mkdir(exist_ok=True)
fig.savefig(out/'mechanism-timeline.png',dpi=180)
fig.savefig(out/'mechanism-timeline.pdf')
plt.close(fig)
