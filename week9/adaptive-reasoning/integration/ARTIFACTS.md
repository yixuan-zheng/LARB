# Model artifacts and transfer

**Base:** Qwen/Qwen3-4B, snapshot `1cfa9a7208912126459214e8b04321603b3df60c`. Use the tokenizer and chat template in the same snapshot. Reference runtime was Python 3.10, PyTorch 2.9.0, Transformers 4.57.6, vLLM 0.11.2 V1, BF16, eager, prefix caching off. The HTTP harness also uses aiohttp, FastAPI and Uvicorn. Run on a CUDA-capable PACE node.

**Served adapter:** rank-16 LoRA on query/value projections, scale 16, exported from training job 7281434 step 24. The final serving job 7324648 used the same exported file as the matched control job 7301687. A CPU check compared all 144 tensors with the original step-24 tensors converted to BF16 and found exact equality. Copy both export files to an authorized project-controlled PACE share or through authenticated SCP before launch. The original PyTorch training artifact is optional and is not a vLLM adapter directory. Do not commit weights or grant broader access to an individual scratch area.

| Artifact under the source account’s PACE scratch | Bytes | SHA-256 |
|---|---:|---|
| `larb-serving-replication.g6861sld/coin-final.nXlSufPT/adapter/adapter_model.safetensors` | 11,815,760 | `6d35c4bb2f8872ccc3511380d32f17a57225a0b4cd8d14e6d3e62f3fa76b98c7` |
| Same adapter directory, `adapter_config.json` | 151 | `38b3727133e379992c9962237185b0dd4975264a01d221d3cd3fdbe2d2b67b62` |
| `larb-vllm-lora-gate.azlm1NaU/train-7281434/adapter-step-24.pt` | 23,640,911 | `7107f4f1ddf07f7dc54c464c797ce6f6257dddacedb09d886769cb5e24bfa31d` |

On PACE as the source owner, use `cp -L "$HOME/scratch/larb-serving-replication.g6861sld/coin-final.nXlSufPT/adapter/"{adapter_config.json,adapter_model.safetensors} "$APPROVED_SHARED_DIR/"`. Verify SHA-256 after copying. Set `LARB_ADAPTER` to the resulting directory and `LARB_MODEL_PATH` to the pinned base snapshot. Access to the source scratch and the target share must be arranged by the owners. No transfer or permissions change has been made.

The export config is causal-LM LoRA, rank 16, alpha 16, dropout 0, no bias, with targets `q_proj` and `v_proj`. Use the PACE-tested versions in [reference dependencies](requirements-reference.txt). The [checksum manifest](adapter.sha256) verifies the export pair:

```sh
repo="$PWD"
(cd "$LARB_ADAPTER" && sha256sum -c "$repo/week9/adaptive-reasoning/integration/adapter.sha256")
```

The source pair was rehashed on PACE for the Week 9 closeout. A course or project-owned PACE share with existing read access for the scaling accounts is the appropriate destination. No approved share for this group was identified in the accessible PACE and repository records. The project owner needs to provide the exact directory and verify read access for the team's PACE accounts. Stage and rehash the export there once that arrangement is confirmed.
