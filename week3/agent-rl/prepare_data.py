"""Reconstruct saved source rows; requires datasets, not a network download."""
import json,sys,hashlib
from pathlib import Path
from datasets import Dataset,load_from_disk
root=Path(__file__).resolve().parent;dest=Path(sys.argv[1]).resolve()
manifest=json.loads((root/'results/pilot/dataset-manifest.json').read_text())
for split in ['train','test']:
 rows=[dict(messages=[dict(role='user',content=r['question']+'\nPlease put your final answer within \\boxed{}.')],answer=r['answer']) for r in manifest[split]]
 target=dest/('data-'+split)
 if target.exists():raise SystemExit(f'Refusing to overwrite {target}')
 Dataset.from_list(rows).save_to_disk(str(target))
# Check transformation against the exact latest-run fixture before claiming reproduction.
source=load_from_disk(str(dest/'data-train'))
fixture=json.loads((root/'results/comparison/raw/profiles/tirgatecompare/manifest.json').read_text())
suffix='\nBefore giving the answer, you must check your arithmetic using the calculator tool. Call it exactly like <calculator>15 + 27</calculator>, with the expression for this problem. Wait for its output, then continue your reasoning. Use the calculator again if another calculation is needed. Do not write Python. End with the final numeric answer inside \\boxed{}.'
for rows in fixture.values():
 for row in rows:
  original=source[row['source_id']]
  assert original['messages'][0]['content']+suffix==row['messages'][0]['content']
  assert original['answer'].split('####')[-1].strip()==row['answer']
print('PASS: reconstructed source data matches all comparison prompts and answers')
