#!/bin/bash
set -euo pipefail
cd "$TAU_ROOT"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=True
base="$HOME/scratch/CS6222-qwen3-baseline"
export AGENT_MODEL="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
export PYTHONPATH="$TAU_ROOT/harness:$LARB_CODE"
role="$1"
export LARB_OUT="$TAU_OUT/$role-state"
key=$(cat "$TAU_OUT/key")
if [[ "$role" == customer ]]; then
    model="$TAU_ROOT/simulator-model"
    port=18784
    host=$(hostname -i | awk '{print $1}')
    args=(--max-model-len 8192 --max-num-seqs 2 --gpu-memory-utilization 0.55)
else
    model="$AGENT_MODEL"
    port=18783
    host=127.0.0.1
    args=(--max-model-len 8192 --max-num-seqs 2 --reasoning-parser qwen3
          --enable-auto-tool-choice --tool-call-parser hermes
          --logits-processors agent_processor:ChatBudgetProcessor)
fi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > "$TAU_OUT/$role-device.csv"
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 2 > "$TAU_OUT/$role-gpu.csv" &
sampler=$!
"$base/vllm-proof-env/bin/vllm" serve "$model" --served-model-name "$role" \
    --host "$host" --port "$port" --api-key "$key" --enforce-eager --dtype bfloat16 "${args[@]}" &
server=$!
trap 'kill "$server" "$sampler" 2>/dev/null || true' EXIT
base_url="http://$host:$port/v1"
for i in $(seq 1 120); do
    kill -0 "$server"
    if curl -fsS --max-time 4 -H "Authorization: Bearer $key" "$base_url/models" > "$TAU_OUT/$role-models.json"; then
        break
    fi
    sleep 4
done
grep -q "\"$role\"" "$TAU_OUT/$role-models.json"
if [[ "$role" == customer ]]; then
    printf '%s\n' "$base_url" > "$TAU_OUT/customer.url.tmp"
    mv "$TAU_OUT/customer.url.tmp" "$TAU_OUT/customer.url"
    wait "$server"
else
    for i in $(seq 1 120); do
        [[ -s "$TAU_OUT/customer.url" ]] && break
        sleep 4
    done
    curl -fsS --max-time 10 -H "Authorization: Bearer $key" "$(cat "$TAU_OUT/customer.url")/models" > "$TAU_OUT/customer-cross-node.json"
    status=0
    timeout 45m "$TAU_ROOT/.venv/bin/python" "$TAU_ROOT/harness/check.py" || status=$?
    printf '%s\n' "$status" > "$TAU_OUT/done.tmp"
    mv "$TAU_OUT/done.tmp" "$TAU_OUT/done"
fi
