"""Validate the serving loop's forward/cache logic with the real model on **CPU**.

Why this exists
---------------
The riskiest part of the harness is not the schedule, it is the KV-cache handling
that lets several requests with different context lengths be decoded in one batch:
each row's cache is left-padded to the batch maximum, the pad positions are hidden
by the attention mask, and ``position_ids`` restores each row's own logical
position.  If any of that is wrong, every latency number the harness reports is
attached to the wrong computation.

A GPU is not needed to check it.  This script loads the pinned Gemma 3n E4B
(checkpoint already in the local HF cache), runs a short trace through the real
executor on CPU, and compares the batched decode path against the single-row
reference path, and both against a plain one-shot greedy continuation of the same
prompt:

* ``batched == single_row`` per request, and both equal the one-shot continuation;
* the widths recorded per generated step match the configured policy.

Latency numbers from this script are meaningless (CPU, tiny trace) and are
deliberately not reported: it is a *correctness* check.

    python code/smoke_cpu_model.py --requests 3 --output-tokens 3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
WEEK1 = ROOT.parent.parent / "week1" / "latency-baselines"
sys.path.insert(0, str(WEEK1))

import latency_lib as lib  # noqa: E402
import policies  # noqa: E402
import serving_core as core  # noqa: E402
import serving_lib as serving  # noqa: E402
import slo as slo_mod  # noqa: E402
import workload  # noqa: E402


def load_model(dtype, device: str = "cpu"):
    from transformers import AutoTokenizer, Gemma3nForCausalLM

    model = Gemma3nForCausalLM.from_pretrained(
        lib.MODEL, revision=lib.REVISION, dtype=dtype, local_files_only=True).eval()
    if str(device).startswith("cuda"):
        model = model.to(device)
    tokenizer = AutoTokenizer.from_pretrained(lib.MODEL, revision=lib.REVISION,
                                              local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return model, tokenizer


def make_trace(prompt_lengths, output_tokens, spacing_s=0.0):
    doc = workload.canonical_trace(
        "smoke", [i * spacing_s for i in range(len(prompt_lengths))],
        list(prompt_lengths), [output_tokens] * len(prompt_lengths),
        source={"kind": "smoke"}, generator={"kind": "smoke"})
    return workload.Trace(doc["trace_id"], doc["requests"], {})


def one_shot_reference(model, tokenizer, prompt_len, output_tokens, offset,
                       apply_width=None, widths=None):
    """Greedy continuation of the same prompt with plain HF calls (no padding).

    ``widths[0]`` is applied before the prefill and ``widths[k]`` before decode step
    k, so the reference reproduces the *schedule* a policy would run -- the frozen
    quality convention (step 0 is the prefill).  For ``static_large`` that is all
    ``large``; for ``phase_hybrid`` it is ``['small', 'large', ...]``, i.e. ``SL_early``.
    """
    ids, _ = lib.build_prompt_ids(tokenizer, prompt_len, offset=offset)
    widths = list(widths or ["large"] * output_tokens)
    tokens = []
    with torch.inference_mode():
        if apply_width is not None:
            apply_width(widths[0])
        prefill = model(input_ids=ids, use_cache=True)
        cache = prefill.past_key_values
        logits = prefill.logits[:, -1, :]
        for step_index in range(output_tokens):
            token = int(logits.argmax(-1))
            tokens.append(token)
            if step_index + 1 >= output_tokens:
                break
            if apply_width is not None:
                apply_width(widths[min(step_index + 1, len(widths) - 1)])
            step = torch.tensor([[token]], dtype=torch.long)
            res = model(input_ids=step, past_key_values=cache, use_cache=True,
                        logits_to_keep=1)
            cache = res.past_key_values
            logits = res.logits[:, -1, :]
    return tokens


def schedule_widths(policy_name: str, output_tokens: int) -> list:
    """The per-step width schedule a policy implies (step 0 = prefill)."""
    if policy_name == "static_large":
        return ["large"] * output_tokens
    if policy_name == "static_small":
        return ["small"] * output_tokens
    if policy_name == "phase_hybrid":
        return ["small"] + ["large"] * max(0, output_tokens - 1)
    raise ValueError(f"no reference schedule defined for {policy_name!r}")


def diagnose_divergence(model, tokenizer, executor, prompt_len: int, out_tokens: int = 3,
                        request_id: str = "diag000000") -> dict:
    """Localize a token divergence: is it the cache rebuild, or my decode arguments?

    Three decodes of the same prompt, differing in exactly one thing each:

    ``stock``      plain HF calls, no cache surgery, no explicit mask/positions
    ``rebuilt``    the cache is dismantled and rebuilt by ``pair_to_cache`` (as the loop does)
    ``my_args``    rebuilt *and* fed the loop's explicit attention mask and position_ids

    If ``rebuilt`` diverges, the cache rebuild is lossy; if only ``my_args`` diverges,
    the mask/position_ids the loop passes are wrong; if none diverge, the divergence
    lives somewhere else (width, prompt content, or the loop's own state).
    """
    ids, _ = lib.build_prompt_ids(tokenizer, prompt_len,
                                  offset=serving.prompt_offset(request_id))
    out = {"prompt_len": prompt_len, "modes": {}}
    with torch.inference_mode():
        prefill = model(input_ids=ids, use_cache=True, logits_to_keep=1)
        cache = prefill.past_key_values
        first = int(prefill.logits[:, -1, :].argmax(-1))
        pairs = serving.cache_pairs(cache)
        out["cache_layers"] = len(pairs)
        out["cache_seq_len_dim"] = {
            "shape": list(pairs[0][0].shape),
            "shape[-2]": serving.cache_seq_len(pairs[0][0]),
            "get_seq_length": int(cache.get_seq_length()),
        }
        out["first_token"] = first
        for mode in ("stock", "rebuilt", "my_args"):
            pairs = serving.cache_pairs(cache)
            tokens, past_state = [first], None
            step = torch.tensor([[first]], dtype=torch.long)
            for _ in range(out_tokens - 1):
                if mode == "stock":
                    res = model(input_ids=step, past_key_values=(past_state if past_state
                                                                 else cache),
                                use_cache=True, logits_to_keep=1)
                else:
                    rebuilt = serving.pair_to_cache(serving.cache_pairs(
                        past_state if past_state else cache))
                    if mode == "my_args":
                        length = serving.cache_seq_len(serving.cache_pairs(
                            past_state if past_state else cache)[0][0])
                        mask = torch.ones(1, length + 1, dtype=torch.long)
                        positions = torch.tensor([[length]], dtype=torch.long)
                        res = model(input_ids=step, attention_mask=mask,
                                    position_ids=positions, past_key_values=rebuilt,
                                    use_cache=True, logits_to_keep=1)
                    else:
                        res = model(input_ids=step, past_key_values=rebuilt,
                                    use_cache=True, logits_to_keep=1)
                past_state = res.past_key_values
                token = int(res.logits[:, -1, :].argmax(-1))
                tokens.append(token)
                step = torch.tensor([[token]], dtype=torch.long)
            out["modes"][mode] = tokens
    return out


def run_once(model, controller, tokenizer, trace, policy_name, decode_mode, dtype,
             device="cpu"):
    config = core.EngineConfig(token_budget=64, prefill_token_budget=4096,
                               decode_batch_cap=8, max_running=8, max_seq_len=8192)
    executor = serving.GpuExecutor(model, controller, tokenizer, config, device=device,
                                   dtype=dtype, decode_mode=decode_mode,
                                   vram_budget_bytes=None)
    contract = slo_mod.SLOContract(ttft_s=1e6, itl_gate_s=1e6)
    state, report = serving.measured_run(
        trace, config, policies.build_policy(policy_name), contract, executor)
    return state, report, executor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requests", type=int, default=3)
    parser.add_argument("--output-tokens", type=int, default=3)
    parser.add_argument("--prompt-lengths", default="24,32,48")
    parser.add_argument("--dtype", default="float32")
    parser.add_argument("--out", default=str(ROOT / "results" / "smoke_cpu_model.json"))
    parser.add_argument("--device", default="cpu",
                        help="cpu (thorough, slow) or cuda (fast; use --prompt-lengths "
                             "700,900 to exercise the 512-token sliding window)")
    args = parser.parse_args()

    if str(args.device).startswith("cuda") and args.dtype == "float32":
        args.dtype = "bfloat16"  # bf16 is the serving precision and is far faster on GPU
    dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16}[args.dtype]
    lengths = [int(x) for x in args.prompt_lengths.split(",")][:args.requests]
    print(f"[smoke] loading {lib.MODEL}@{lib.REVISION[:8]} dtype={args.dtype} on CPU ...",
          flush=True)
    t0 = time.time()
    model, tokenizer = load_model(dtype, args.device)
    print(f"[smoke] loaded in {time.time() - t0:.1f}s", flush=True)

    trace = make_trace(lengths, args.output_tokens)
    verdict = {"checks": [], "requests": len(trace.requests),
               "output_tokens": args.output_tokens, "prompt_lengths": lengths,
               "device": "cpu", "dtype": args.dtype,
               "note": "correctness only: CPU latency numbers are meaningless"}
    failures = []

    def check(name, ok, detail):
        verdict["checks"].append({"check": name, "passed": bool(ok), "detail": str(detail)})
        if not ok:
            failures.append(name)
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {detail}", flush=True)

    # Per-request, per-policy reference: a hand-run of the *same width schedule* with
    # plain HF calls, so the check is "the loop reproduces the schedule it claims",
    # not "the loop matches an unrelated full-width run".
    plans = {name: serving.sched.WidthPlan.from_preset(name) for name in ("large", "small")}
    ctrl_ref = _controller(model)

    def apply_width(name):
        ctrl_ref.apply(plans[name])

    reference, reference_steps = {}, {}
    for i, length in enumerate(lengths):
        rid = f"req{i:06d}"
        for policy_name in ("static_large", "phase_hybrid"):
            key = f"{rid}|{policy_name}"
            reference[key] = one_shot_reference(
                model, tokenizer, length, args.output_tokens,
                offset=serving.prompt_offset(rid), apply_width=apply_width,
                widths=schedule_widths(policy_name, args.output_tokens))
            reference_steps[key] = schedule_widths(policy_name, args.output_tokens)
    check("one_shot_reference_ran",
          all(len(v) == args.output_tokens for v in reference.values()),
          "plain unbatched greedy continuation produced the requested token counts")

    results = {}
    steps = {}
    ctrl_ref.apply(plans["large"])
    executor_plain = run_once(model, _controller(model), tokenizer, trace, "static_large",
                              "single_row", dtype, device=args.device)[2]
    verdict["diagnostic"] = diagnose_divergence(model, tokenizer, executor_plain,
                                                lengths[0], args.output_tokens,
                                                trace.requests[0]["request_id"])
    print("[smoke] diagnostic:", json.dumps(verdict["diagnostic"]), flush=True)
    for decode_mode in ("single_row", "batched"):
        for policy_name in ("static_large", "phase_hybrid"):
            controller = _controller(model)
            state, report, executor = run_once(model, controller, tokenizer, trace,
                                               policy_name, decode_mode, dtype,
                                               device=args.device)
            key = f"{decode_mode}/{policy_name}"
            check(f"{key}_completed", len(state.completed) == len(trace.requests),
                  f"{len(state.completed)}/{len(trace.requests)} requests completed")
            tokens = {rid: list(t) for rid, t in executor.retired_tokens.items()}
            steps[key] = _step_widths(state)
            mismatches = {}
            for r in state.completed:
                got = tokens[r.request_id][:args.output_tokens]
                want = reference[f"{r.request_id}|{policy_name}"][:args.output_tokens]
                if got != want:
                    mismatches[r.request_id] = {
                        "first_token_matches": bool(got and want and got[0] == want[0]),
                        "got": got, "reference": want}
            check(f"{key}_matches_one_shot_greedy", not mismatches,
                  "generated tokens equal the unbatched one-shot greedy continuation"
                  if not mismatches else json.dumps(mismatches)[:400])
            results[key] = tokens

    for policy_name in ("static_large", "phase_hybrid"):
        check(f"batched_equals_single_row_{policy_name}",
              steps[f"batched/{policy_name}"] == steps[f"single_row/{policy_name}"],
              "the padded batched decode reproduces the per-row reference tokens")
    check("static_large_widths_all_large",
          all(set(w) == {"large"} for w in steps["batched/static_large"].values()),
          "static_large recorded large at every step")
    check("phase_hybrid_widths_are_sl_early",
          all(w[0] == "small" and set(w[1:]) == {"large"}
              for w in steps["batched/phase_hybrid"].values()),
          "phase_hybrid recorded exactly SL_early (narrow prefill, wide decode)")

    verdict["passed"] = not failures
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdict, indent=2) + "\n")
    print(f"[smoke] wrote {out}")
    print("PASS smoke_cpu_model" if verdict["passed"] else f"FAIL smoke_cpu_model {failures}")
    sys.exit(0 if verdict["passed"] else 1)


def _controller(model):
    import dynamic_lib

    return dynamic_lib.SwitchController(model, slice_mode="view", verbose=False)


def _tokens(executor, state):
    """Generated tokens per request, read from the executor's retired rows."""
    return {rid: list(tokens) for rid, tokens in executor.retired_tokens.items()}


def _step_widths(state):
    return {r.request_id: r.step_widths() for r in state.completed}


if __name__ == "__main__":
    main()
