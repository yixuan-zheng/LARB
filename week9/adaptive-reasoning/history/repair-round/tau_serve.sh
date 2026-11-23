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
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > "$TAU_OUT/$role-device.csv"
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 2 > "$TAU_OUT/$role-gpu.csv" &
sampler=$!
if [[ "$role" == customer ]]; then
    for model_name in customer-3b customer-7b; do
        if [[ "$model_name" == customer-3b ]]; then
            model="$TAU_ROOT/simulator-model"
        else
            model="$TAU_ROOT/simulator-7b"
        fi
        host=$(hostname -i | awk '{print $1}')
        port=18784
        url="http://$host:$port/v1"
        "$base/vllm-proof-env/bin/vllm" serve "$model" --served-model-name "$model_name" \
            --host "$host" --port "$port" --api-key "$key" --enforce-eager --dtype bfloat16 \
            --max-model-len 8192 --max-num-seqs 2 --gpu-memory-utilization 0.65 > "$TAU_OUT/$model_name.log" 2>&1 &
        server=$!
        trap 'kill "$server" "$sampler" 2>/dev/null || true' EXIT
        for i in $(seq 1 120); do
            kill -0 "$server"
            if curl -fsS --max-time 4 -H "Authorization: Bearer $key" "$url/models" > "$TAU_OUT/$model_name-models.json"; then
                break
            fi
            sleep 4
        done
        grep -q "\"$model_name\"" "$TAU_OUT/$model_name-models.json"
        printf '%s\n' "$url" > "$TAU_OUT/$model_name.url.tmp"
        mv "$TAU_OUT/$model_name.url.tmp" "$TAU_OUT/$model_name.url"
        for i in $(seq 1 120); do
            [[ -f "$TAU_OUT/$model_name.done" ]] && break
            kill -0 "$server"
            sleep 4
        done
        test -f "$TAU_OUT/$model_name.done"
        kill "$server"
        wait "$server" || true
    done
    exit 0
else
    model="$AGENT_MODEL"
    port=18783
    host=127.0.0.1
    args=(--max-model-len 8192 --max-num-seqs 2 --reasoning-parser qwen3
          --enable-auto-tool-choice --tool-call-parser hermes
          --logits-processors agent_processor:ChatBudgetProcessor)
fi
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
status=0
for model_name in customer-3b customer-7b; do
    for i in $(seq 1 150); do
        [[ -s "$TAU_OUT/$model_name.url" ]] && break
        sleep 4
    done
    curl -fsS --max-time 10 -H "Authorization: Bearer $key" "$(cat "$TAU_OUT/$model_name.url")/models" > "$TAU_OUT/$model_name-cross-node.json"
    timeout 8m "$TAU_ROOT/.venv/bin/python" "$TAU_ROOT/harness/check.py" "$model_name" "$TAU_OUT/$model_name.url" || status=$?
    touch "$TAU_OUT/$model_name.done"
done
timeout 12m "$TAU_ROOT/.venv/bin/python" "$TAU_ROOT/harness/check.py" agent || status=$?
"$TAU_ROOT/.venv/bin/python" "$TAU_ROOT/repair/tau_summary.py" "$TAU_OUT" || status=$?
printf '%s\n' "$status" > "$TAU_OUT/done.tmp"
mv "$TAU_OUT/done.tmp" "$TAU_OUT/done"
