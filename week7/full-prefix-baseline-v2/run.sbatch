#!/bin/bash
set -euo pipefail
cd "${1:?}"
python=${2:?}
snapshot=${3:?}
out="$PWD/job-${SLURM_JOB_ID:?}"
mode=${4:-smoke}
[[ "$mode" = smoke || "$mode" = full ]]
reader_args=()
if [[ "$mode" = smoke ]]; then
    reader_args+=(--smoke-only)
else
    "$python" - "${5:?verified smoke output directory required}" <<'PY_CHECK'
import hashlib
import json
import sys
from pathlib import Path
smoke = Path(sys.argv[1])
proof = json.loads((smoke/'smoke-pass.json').read_text())
assert proof['cases'] == 8
for name, path in {
    'smoke': smoke/'smoke.jsonl', 'config': Path('reader-config.json'),
    'prompt': Path('PROMPT.txt'), 'runner': Path('read_forecasts.py'),
}.items():
    assert hashlib.sha256(path.read_bytes()).hexdigest() == proof[name+'_sha256']
PY_CHECK
fi
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
"$python" - "$snapshot" <<'PY'
import importlib.metadata
import json
import sys
from pathlib import Path
config=json.loads(Path('reader-config.json').read_text())
assert Path(sys.argv[1]).name==config['revision']
for package in ('vllm','torch','transformers'):
    assert importlib.metadata.version(package).split('+')[0]==config[package]
import torch
assert torch.cuda.mem_get_info()[1] >= 75*1024**3
PY
config_args=$("$python" -c 'import json; c=json.load(open("reader-config.json")); print(c["dtype"],c["max_model_len"],c["max_num_seqs"],c["model"])')
read -r dtype context batch model <<< "$config_args"
port=$((20000 + SLURM_JOB_ID % 20000))
"$python" -m vllm.entrypoints.openai.api_server --model "$snapshot" --served-model-name "$model" \
    --host 127.0.0.1 --port "$port" --dtype "$dtype" --max-model-len "$context" \
    --max-num-seqs "$batch" --language-model-only --enforce-eager --reasoning-parser qwen3 --reasoning-config '{"reasoning_parser":"qwen3"}' > "$out-server.log" 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
ready=0
for ((n=0; n<180; n++)); do
    if curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then ready=1; break; fi
    kill -0 "$server"
    sleep 5
done
test "$ready" -eq 1
"$python" -B -u read_forecasts.py "http://127.0.0.1:$port/v1/chat/completions" "$out" "${reader_args[@]}"
