"""Plot the saved result table; never select or alter experimental outcomes."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args()
out=args.root/'analysis';result=json.loads((out/'summary.json').read_text())
assert result['complete'] and result['validation_passed']
policies=['full','arrival','admission','live']
labels=['Full','Arrival-only','Admission-only','Live']
fig,axes=plt.subplots(1,2,figsize=(10,4.6),sharey=True)
colors=['#287e80','#b8dcdc','#e1a36f']
for block,ax in enumerate(axes):
    for x,mode in enumerate(policies):
        row=next(r for r in result['summary'] if r['block']==block and r['policy']==mode)
        counts=[row['correct_on_time'],row['completed_correct']-row['correct_on_time'],row['n']-row['completed_correct']]
        assert all(v>=0 for v in counts) and sum(counts)==12
        bottom=0
        for count,color in zip(counts,colors):
            ax.bar(x,count,bottom=bottom,width=.62,color=color,edgecolor='white',linewidth=.7)
            if count:
                ax.text(x,bottom+count/2,str(count),ha='center',va='center',fontsize=10,
                        color='white' if color==colors[0] else '#1d3034',fontweight='bold')
            bottom+=count
    ax.set_title('Block 1: full → live' if block==0 else 'Block 2: reverse order',fontsize=11,fontweight='bold')
    ax.set_xticks(range(4),labels,rotation=12)
    ax.set_ylim(0,12.4);ax.set_yticks(range(0,13,2));ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
axes[0].set_ylabel('Requests (12 per policy in each block)')
trace=result['trace']
fig.suptitle('Controlled admission/live comparison',fontsize=14,fontweight='bold',y=.98)
fig.text(.5,.895,f"Frozen burst {trace['burst_at_seconds']:.2f}s · deadline {trace['relative_deadline_seconds']:.2f}s · two active slots",ha='center',fontsize=10)
fig.legend(handles=[Patch(color=c,label=l) for c,l in zip(colors,
    ['Correct by deadline','Correct after deadline','Wrong / capped / failed'])],
    loc='lower center',ncol=3,frameon=False,bbox_to_anchor=(.5,.045),fontsize=10)
fig.text(.5,.02,'Same 12 development problems repeated: 12 unique accuracy examples, not 24 independent examples.',ha='center',fontsize=8.5,color='#4d5960')
fig.subplots_adjust(left=.07,right=.99,top=.80,bottom=.23,wspace=.12)
fig.savefig(out/'controlled-outcomes.png',dpi=200)
fig.savefig(out/'controlled-outcomes.pdf')
plt.close(fig)
(out/'figure-manifest.json').write_text(json.dumps(dict(
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    summary_sha256=hashlib.sha256((out/'summary.json').read_bytes()).hexdigest(),
    matplotlib=matplotlib.__version__),indent=2)+'\n')
