"""Write the frozen Week 5 plan; run once, before any Week 5 inference."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
import cohort  # noqa: E402

ids = cohort.cohort()
plan = {
  "id": "week5-one-waiter-v1",
  "date": "2026-10-29",
  "question": ("Does cutting a running request at the first waiting request, instead of the "
               "second, recover fixed-2,048 congestion efficiency without losing answers?"),
  "candidate": ("Same admission start rule and same logits-only cue as Week 4 live, with the "
                "waiting threshold changed from 2 to 1 for both the admission decision and "
                "mid-generation updates ('live_one'). Week 3/4 controller files are unchanged."),
  "cohort": {
    "rule": ("SHA-256 rank of the string 'week5-one-waiter-v1:INDEX' over dataset indices "
             "0-99, excluding every index already used by Weeks 3-4"),
    "used_indices": list(cohort.USED),
    "eligible_pool_size": len(cohort.cohort(100)),
    "rank_order": ids,
    "note": ("Selection ignores answers, difficulty and observed lengths. Only the first k in "
             "rank order are run; the rest stay reserved for the continuation.")
  },
  "conditions": ["gate", "one_at_a_time", "constant_pressure", "slack_rush_recovery"],
  "coverage": {
    "constant_pressure": 6,
    "one_at_a_time": 2,
    "slack_rush_recovery": 0,
    "reason": ("The only allocation available was a 2-hour interactive H100 (job 6662944, "
               "10:27-12:27). 576 outcomes need roughly 12 GPU-hours, so coverage is reduced by "
               "rank order, never by outcome. slack_rush_recovery is not run and its claim is "
               "untested; one_at_a_time is limited to two cohort questions, which makes the premise check preliminary rather than a two-block verdict."),
    "planned_full_design": {"questions": 24, "policies": 4, "conditions": 3, "blocks": 2,
                            "measured_outcomes": 576}
  },
  "calibration": {"indices": [0, 2], "policy": "full", "per_job": True,
                  "unit": "S=max(30, max(client receipt minus scheduled arrival))",
                  "burst": "B=0.25*min(calibration client durations)",
                  "automatic_quality_driven_recalibration": False},
  "traffic": {
    "relative_deadline": "2*S for every request in every condition",
    "one_at_a_time": "offset(i)=2*S*i; no queueing expected and timing is not the point",
    "constant_pressure": "offset(i)=0.3*S*i; identical rule to Week 4 sustained_pressure",
    "slack_rush_recovery": ("slow (2*S apart), fast (B+0.05*i), a 4*S pause, then slow again; "
                            "not run this schedule"),
    "injection": "Open loop; late requests drain; no policy observes future arrivals",
    "horizon": "H=max(offset+relative deadline), fixed per condition"
  },
  "policies_measured": ["fixed2048", "fixed4096", "live", "live_one"],
  "policy_semantics": {
    "fixed2048": "2,048 thinking tokens always; load never changes the budget",
    "fixed4096": "4,096 thinking tokens always; load never changes the budget",
    "live": "Week 4 unchanged: short at admission or by live update when >=2 requests wait",
    "live_one": "Same rule and cue with the threshold at 1 waiting request",
    "full": "unrestricted thinking; calibration and gate only, never a measured policy"
  },
  "budget": {"long": 16384, "short": 2048, "answer_cap": 2048, "waiting_threshold_live": 2,
             "waiting_threshold_live_one": 1,
             "startup_seconds": 900, "phase_seconds": 900, "automatic_retries": 0,
             "allocation": "one interactive H100 80GB, 120 minutes (Slurm job 6662944)",
             "measured_cap_seconds": "frozen per condition at launch from the remaining wall clock"},
  "engine": {"model": "Qwen/Qwen3-4B",
             "model_revision": "1cfa9a7208912126459214e8b04321603b3df60c",
             "dtype": "bfloat16", "vllm": "0.11.2", "torch": "2.9.0",
             "transformers": "4.57.6", "max_model_len": 24576,
             "max_active_sequences": 2, "max_num_batched_tokens": 2048,
             "gpu_memory_utilization": 0.80, "enforce_eager": True,
             "enable_prefix_caching": False, "stock_scheduler": True,
             "temperature": 0.6, "top_p": 0.95, "top_k": 20, "seed": "6222 + dataset index",
             "cue": "unchanged Stage 3 transition_text; forced tokens additional and timed"},
  "orders": [["fixed2048", "fixed4096", "live", "live_one"],
             ["live_one", "live", "fixed4096", "fixed2048"]],
  "block_rotation": 3,
  "gate": {"indices": [1, 4, 5], "offsets_seconds": [0.0, 2.0, 2.1],
           "policies": ["live_one", "fixed2048"],
           "criteria": ["every admitted request carries a scheduler admission decision recorded "
                        "before it generates",
                        "two requests are active in the same scheduler step",
                        "a live reduction takes effect mid-thinking and the forced cue completes "
                        "with a normal final answer in live_one",
                        "fixed2048 forces a complete uncapped transition at exactly 2,048 tokens"],
           "note": "Gate requests reuse exposed indices 1/4/5 and consume no cohort question."},
  "arrival_snapshot_max_age_s": 2,
  "analysis": {
    "primary": ("correct final answer with normal completion received before the deadline, "
                "measured on the client clock from scheduled arrival"),
    "quality_guard": ("In each workload, live_one may not have more than one fewer correct "
                      "answer than fixed2048 (both correct-on-time and eventual correctness)"),
    "report": ["correct on time", "eventual correctness", "median and slowest completion",
               "queue wait", "thinking tokens", "total output tokens", "cuts that took effect",
               "cap failures", "paired per-question changes"],
    "premise_verdict": ("fixed4096 must beat fixed2048 on the same question in both blocks, "
                        "with no queue, for extra thinking to buy useful quality"),
    "fix_verdict": ("live_one matches fixed2048 on-time efficiency under pressure without losing "
                    "more than one correct answer"),
    "workloads_reported_separately": True,
    "changes_after_results": "none; failures and truncated coverage stay visible"
  },
  "scope": {"no_new_controller": True, "no_scheduler_change": True,
            "no_validation_cohort_use": True,
            "untouched_pool": "376 remaining dataset indices stay unused"}
}
(HERE / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
print('plan.json', hashlib.sha256((HERE / 'plan.json').read_bytes()).hexdigest())
print('cohort run order:', ids[:8], '| one_at_a_time:', ids[:3])
