"""End-to-end CPU tests for the Week 8 preview, calibration and grading logic.

No GPU, no vLLM, no server.  The synthetic records deliberately exercise the
failure modes the P1 transition exposed: warm-up contamination, the pressure
threshold mismatch, cut-after-close and the lossy Math-Verify parse.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import larb_week8  # noqa: E402,F401
from larb_week8 import audit, calibrate, config, preview  # noqa: E402
from larb_week8 import analyze_main  # noqa: E402
from larb_week8 import candidate, runner, traces  # noqa: E402
from larb_scaled import analysis  # noqa: E402

CLOSE = 151668
EOS = 151645
CUE = [271, 40, 686, 2936, 13295, 323, 2968, 279, 1590, 4226, 1431, 624, 151668, 271]


def _record(trace: dict, arm: str, correct: bool, answer_cap: int = 2048,
            capped: bool = False, cue_start: int = 100) -> dict:
    key = analysis.runtime_key("gate-omni-preview", arm, trace)
    reference = trace["reference"]
    body = reference if correct else "999999"
    if capped:
        answer_tokens = [1] * answer_cap
    else:
        answer_tokens = [1, 2, 3]
    token_ids = [1] * cue_start + CUE + answer_tokens + [EOS]
    raw_output = "<think>synthetic</think>\\boxed{" + body + "}"
    return {
        "key": key, "trace_id": trace["trace_id"], "phase": f"preview-{arm}",
        "condition": "gate-omni-preview", "arm": arm, "policy": arm,
        "class": "signal", "question_id": trace["question_id"], "seed": trace["seed"],
        "scored": True, "complete": True, "error": None,
        "initial_budget": 4096, "final_budget": 4096,
        "cue_start": cue_start, "cue_start_time": 1.0,
        "cue_ids": CUE, "close_id": CLOSE, "eos_id": EOS, "answer_cap": answer_cap,
        "capped": True if capped else None, "token_ids": token_ids,
        "raw_output": raw_output, "reference": reference,
        "source": trace["source"], "exposure": trace["exposure"],
        "answer_type": trace["answer_type"], "scheduler_start": 0.0,
        "finished": 1.0, "cut_events": [], "preemptions": 0,
    }


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


class PreviewTest(unittest.TestCase):
    def _build_run(self, temp: Path) -> Path:
        path = config.TRACE_DIR / "gate-omni-preview.jsonl"
        traces = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        run = temp / "preview"
        (run / "requests").mkdir(parents=True)
        phases = []
        for arm, correct_count in (("fixed4k", 6), ("fixed6k", 9), ("fixed8k", 13)):
            records = []
            for index, trace in enumerate(traces):
                capped = arm == "fixed8k" and index == 20
                record = _record(trace, arm, index < correct_count, capped=capped)
                _write_json(run / "requests" / f"{record['key']}.json", record)
                records.append({"key": record["key"]})
            phases.append({
                "name": f"preview-{arm}", "condition": "gate-omni-preview", "arm": arm,
                "trace_file": str(path), "epoch": 1000.0, "deadline_s": 1800.0,
                "drain_allowance_s": 600.0, "horizon_s": 2434.5,
                "request_count": len(traces), "client_records": records,
            })
        _write_json(run / "phases.json", phases)
        return run

    def test_preview_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._build_run(Path(folder))
            result = preview.analyse(run, 24)
            self.assertEqual(result["decision"]["decision"], "pass")
            self.assertEqual(result["arms"]["fixed8k"]["correct"], 13)
            self.assertAlmostEqual(result["paired_4k_vs_8k"]["gain"], 7 / 24)
            self.assertGreaterEqual(result["paired_4k_vs_8k"]["answer_change_fraction"], 0.10)

    def test_safe_main_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._build_run(Path(folder))
            rows, phases = analyze_main.build_rows(run)
            self.assertEqual(len(phases), 3)
            self.assertEqual(len(rows), 72)
            self.assertEqual(sum(row["good"] for row in rows if row["arm"] == "fixed8k"), 13)

    def test_decision_near_miss_and_stop(self):
        summary = {
            "fixed4k": {"planned": 24, "present": 24, "accuracy": 0.25, "cap_rate": 0.1,
                        "thinking_tokens_median": 4096},
            "fixed6k": {"planned": 24, "present": 24, "accuracy": 0.30, "cap_rate": 0.1,
                        "thinking_tokens_median": 6096},
            "fixed8k": {"planned": 24, "present": 24, "accuracy": 0.42, "cap_rate": 0.1,
                        "thinking_tokens_median": 8192},
        }
        pair = {"gain": 0.06, "answer_change_fraction": 0.20}
        self.assertEqual(preview.decide(summary, pair)["decision"], "near_miss")
        pair["gain"] = 0.02
        self.assertEqual(preview.decide(summary, pair)["decision"], "stop")

    def test_safe_grading_rejects_lossy_parse(self):
        try:
            import math_verify  # noqa: F401
        except ImportError:
            self.skipTest("math_verify not installed in this environment")
        self.assertFalse(audit.safe_math_verify_match(
            "3-2\\sqrt{2}", "3+\\sqrt{2}+\\sqrt{3}+\\sqrt{6}"))
        self.assertTrue(audit.safe_math_verify_match(
            audit.normalise_math("\\frac{5}{3}"), audit.normalise_math("\\dfrac{5}{3}")))



class CalibrationTest(unittest.TestCase):
    def _build_rate_run(self, temp: Path, rate: int, misses: int) -> tuple[Path, dict]:
        run = temp / f"cal-{rate}"
        (run / "requests").mkdir(parents=True)
        condition = f"gate-omni-cal-{rate}"
        epoch = 1000.0
        clients, scheduler = [], []
        for index in range(100):
            warm = index < 50
            offset = 100.0 + index * 5.0 if warm else 700.0 + (index - 50) * 10.0
            latency = 250.0 if (not warm and index - 50 < misses) else 200.0
            key = f"{condition}--fixed8k--signal--q{index:03d}--{800000 + index}"
            submitted = epoch + offset
            finished = submitted + latency
            clients.append({
                "key": key, "trace_id": f"{condition}--signal--q{index:03d}--{800000 + index}",
                "condition": condition, "arm": "fixed8k", "question_id": f"q{index:03d}",
                "seed": 800000 + index, "class": "signal", "scored": True,
                "scheduled": submitted, "client_submitted": submitted,
                "server_finished": finished, "latency_seconds": latency,
                "injection_lag_seconds": 0.0, "outcome": "ok", "error": None,
                "deadline": submitted + 240.0, "timely": latency <= 240.0,
            })
            _write_json(run / "requests" / f"{key}.json", {
                "key": key, "condition": condition, "arm": "fixed8k", "class": "signal",
                "scored": True, "initial_budget": 8192, "preemptions": 0,
                "scheduler_start": submitted + 0.1, "finished": finished,
                "cue_start": 100, "cut_events": [], "answer_cap": 2048,
            })
        for step in range(10):
            waiting = [f"{condition}--fixed8k--signal--warm{i}--{step}"
                       for i in range(5 if step < 5 else 9)]
            scheduler.append({"event": "step", "step": step, "waiting": waiting,
                              "active": [{"key": waiting[0]}], "running_count": 20})
        (run / "scheduler.jsonl").write_text(
            "\n".join(json.dumps(row) for row in scheduler) + "\n")
        (run / "worker.jsonl").write_text("")
        phase = {"name": f"cal-rate-{rate}", "condition": condition, "arm": "fixed8k",
                 "epoch": epoch, "deadline_s": 240.0, "drain_allowance_s": 600.0,
                 "horizon_s": 2400.0, "request_count": 100, "errors": 0,
                 "injection_valid": True, "max_injection_lag_seconds": 0.0,
                 "client_records": clients}
        _write_json(run / "phases.json", [phase])
        return run, phase

    def test_warmup_threshold_and_band(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            runs = []
            for rate, misses in ((800, 0), (900, 5), (1000, 13)):
                run, _ = self._build_rate_run(temp / str(rate), rate, misses)
                runs.append(run)
            combined = temp / "combined"
            combined.mkdir()
            phases = []
            for run in runs:
                phases.extend(json.loads((run / "phases.json").read_text()))
                for path in (run / "requests").glob("*.json"):
                    _write_json(combined / "requests" / path.name,
                                json.loads(path.read_text()))
                with (combined / "scheduler.jsonl").open("a") as handle:
                    handle.write((run / "scheduler.jsonl").read_text())
            _write_json(combined / "phases.json", phases)
            (combined / "worker.jsonl").write_text("")
            result = calibrate.summarise(combined, 240.0, 600.0, 8)
            self.assertTrue(result["band_found"])
            self.assertEqual(result["chosen_rate_per_hour"], 1000.0)
            first = result["rates"][0]
            self.assertEqual(first["measured_signal"], 50)
            self.assertAlmostEqual(first["pressure_fraction"], 0.5)
            self.assertAlmostEqual(first["pressure_fraction_threshold4"], 1.0)



    def test_live_check_cut_after_close(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "live"
            (run / "requests").mkdir(parents=True)
            condition = "gate-omni-cal-1000"
            epoch = 1000.0
            clients = []
            for index in range(20):
                key = f"{condition}--live--signal--q{index:03d}--{900000 + index}"
                submitted = epoch + 700.0 + index
                _write_json(run / "requests" / f"{key}.json", {
                    "key": key, "condition": condition, "arm": "live", "class": "signal",
                    "scored": True, "initial_budget": 4096 if index < 10 else 8192,
                    "preemptions": 0, "scheduler_start": submitted + 0.1,
                    "finished": submitted + 200.0,
                    "cue_start": 50 if index == 19 else (100 if index == 18 else None),
                    "cut_events": ([{"tokens": 100, "budget": 4096}]
                                   if index < 5 or index in (18, 19) else []),
                    "answer_cap": 2048,
                })
                clients.append({"key": key, "condition": condition, "arm": "live",
                                "class": "signal", "scheduled": submitted,
                                "client_submitted": submitted,
                                "server_finished": submitted + 200.0,
                                "latency_seconds": 200.0, "injection_lag_seconds": 0.0,
                                "outcome": "ok", "error": None})
            for step in range(10):
                waiting = [f"{condition}--live--signal--warm{i}--{step}" for i in range(0)]
                with (run / "scheduler.jsonl").open("a") as handle:
                    handle.write(json.dumps({"event": "step", "step": step,
                                             "waiting": waiting,
                                             "active": [], "running_count": 20}) + "\n")
            # A fixed8k phase with the same condition must not leak into the
            # live pressure or admission counts.
            for step in range(10):
                waiting = [f"{condition}--fixed8k--signal--warm{i}--{step}" for i in range(9)]
                with (run / "scheduler.jsonl").open("a") as handle:
                    handle.write(json.dumps({"event": "step", "step": step,
                                             "waiting": waiting,
                                             "active": [{"key": waiting[0]}],
                                             "running_count": 20}) + "\n")
            with (run / "worker.jsonl").open("a") as handle:
                for index in range(5):
                    handle.write(json.dumps({
                        "event": "live_reduction",
                        "key": f"{condition}--live--signal--q{index:03d}--{900000 + index}",
                        "tokens": 100}) + "\n")
            _write_json(run / "phases.json", [{
                "name": "live-1000", "condition": condition, "arm": "live",
                "epoch": epoch, "deadline_s": 240.0, "drain_allowance_s": 600.0,
                "horizon_s": 2400.0, "request_count": 20, "errors": 0,
                "injection_valid": True, "max_injection_lag_seconds": 0.0,
                "client_records": clients,
            }])
            result = calibrate.live_check(run, 240.0, 600.0, 8)
            self.assertEqual(result["cut_after_close"], 1)
            self.assertFalse(result["pass"])
            self.assertGreater(result["cuts"], 0)
            self.assertEqual(result["pressure_fraction"], 0.0)
            self.assertEqual(result["admission_short"], 10)
            self.assertEqual(result["admission_long"], 10)


class MainPlanTest(unittest.TestCase):
    def _frozen(self) -> dict:
        return {
            "p2_authorised": True, "conditions": ["low", "sustained", "burst"],
            "orders": {"low": ["fixed4k", "fixed8k", "arrival", "live"],
                       "sustained": ["fixed4k", "fixed8k", "arrival", "live"],
                       "burst": ["live", "arrival", "fixed8k", "fixed4k"]},
            "deadline_seconds": 240, "drain_allowance_seconds": 600,
            "max_num_seqs": 32, "pressure_threshold": 8,
            "signal_questions": 216, "seeds": 4,
        }

    def test_plan_main_matches_frozen_packet(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            trace_dir = temp / "traces"
            trace_dir.mkdir()
            original_trace_dir = config.TRACE_DIR
            config.TRACE_DIR = trace_dir
            try:
                traces.build_main(1000.0, "main", 4)
                frozen_path = temp / "p2_main_frozen.json"
                _write_json(frozen_path, self._frozen())
                with patch.object(config, "P2_FROZEN_CONFIG", frozen_path):
                    phases = runner.plan_main()
                self.assertEqual(len(phases), 12)
                self.assertEqual(phases[0]["condition"], "low")
                self.assertEqual(phases[-1]["arm"], "fixed4k")
                frozen = self._frozen()
                frozen["seeds"] = 3
                _write_json(frozen_path, frozen)
                with patch.object(config, "P2_FROZEN_CONFIG", frozen_path):
                    with self.assertRaises(RuntimeError):
                        runner.plan_main()
            finally:
                config.TRACE_DIR = original_trace_dir


class RunnerBoundaryTest(unittest.TestCase):
    """The two GPU-smoke defects found in the P2A transition (2026-11-16)."""

    def test_server_env_coerces_numeric_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            env = runner.server_env({"LARB_THRESHOLD": 8, "LARB_MAX_NUM_SEQS": 32,
                                     "LARB_FORCE_BUDGET": 64}, Path(folder), 18861)
        self.assertTrue(all(isinstance(value, str) for value in env.values()))
        self.assertEqual(env["LARB_THRESHOLD"], "8")
        self.assertEqual(env["LARB_FORCE_BUDGET"], "64")
        self.assertEqual(env["LARB_MAX_NUM_SEQS"], "32")

    def test_config_exports_code_roots(self):
        self.assertTrue(Path(config.WEEK8_CODE).is_dir())
        self.assertTrue(Path(config.WEEK7_CODE).is_dir())

    def test_smoke_env_matches_frozen_rig(self):
        self.assertEqual(runner.SMOKE_ENV["LARB_ENFORCE_EAGER"], "1")
        self.assertEqual(runner.SMOKE_ENV["LARB_CONTRACT"], "legacy")
        self.assertEqual(runner.SMOKE_ENV["LARB_THRESHOLD"], 8)
        self.assertEqual(runner.SMOKE_ENV["LARB_MAX_NUM_SEQS"], 32)
        phase = runner._phase("p", "gate-omni-preview", "fixed4k",
                              config.TRACE_DIR / "gate-omni-preview.jsonl",
                              1800.0, 600.0)
        self.assertEqual(phase["server_env"]["LARB_ENFORCE_EAGER"], "1")
        self.assertEqual(phase["server_env"]["LARB_CONTRACT"], "legacy")


class CandidatePoolTest(unittest.TestCase):
    """AIME 2025+2026 handoff plumbing: traces, plans, freeze, main plan."""

    def test_calibration_plan_and_context_margin(self):
        phases = candidate.calibration_plan([600, 1000, 1200])
        self.assertEqual([p["arm"] for p in phases], ["fixed8k"] * 3)
        self.assertTrue(all(p["deadline_s"] == 240.0 for p in phases))
        self.assertTrue(all(100 <= p["request_count"] <= 500 for p in phases))
        margin = candidate.prompt_margin()
        self.assertEqual(margin["questions"], 60)
        self.assertGreater(margin["margin_tokens"], 800)

    def test_calibration_summary_reads_rate_from_condition(self):
        tools = str(ROOT / "code" / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import candidate_phase
        result = {"band_found": True, "chosen_rate_per_hour": 1000.0,
                  "rates": [{"condition": "gate-aime-cal-1000", "signal_miss_rate": 0.2},
                            {"condition": "gate-aime-cal-1025", "signal_miss_rate": 0.95}]}
        summary = candidate_phase._calibration_summary(result)
        self.assertEqual(summary["rates"], [1000.0, 1025.0])
        self.assertTrue(summary["band_found"])
        self.assertEqual(summary["chosen_rate_per_hour"], 1000.0)
        unbanded = candidate_phase._calibration_summary(
            {"band_found": False, "chosen_rate_per_hour": None,
             "rates": [{"condition": "gate-aime-cal-750"}]})
        self.assertIsNone(unbanded["chosen_rate_per_hour"])

    def test_freeze_and_main_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            originals = (candidate.TRACE_DIR, candidate.MANIFEST_PATH,
                         candidate.FROZEN_PATH, candidate.SOURCE_LOCK_PATH)
            candidate.TRACE_DIR = temp / "traces"
            candidate.MANIFEST_PATH = temp / "traces" / "manifest.json"
            candidate.FROZEN_PATH = temp / "p2_main_frozen_aime.json"
            candidate.SOURCE_LOCK_PATH = temp / "source-lock-p2b.json"
            try:
                band = {"band_found": True, "chosen_rate_per_hour": 1000.0,
                        "chosen_miss_rate": 0.22}
                live = {"pass": True, "cuts": 9, "pressure_fraction": 0.3}
                packet = candidate.freeze(1000.0, band, live)
                self.assertEqual(packet["seeds"], 4)
                self.assertEqual(packet["signal_questions"], 60)
                self.assertLess(packet["seed_wall_time_estimates"][4]["estimated_inner_hours"], 7.0)
                phases = candidate.main_plan()
                self.assertEqual(len(phases), 12)
                by_name = {phase["name"]: phase for phase in phases}
                self.assertEqual(by_name["main-low-fixed4k"]["request_count"], 172)
                self.assertEqual(by_name["main-sustained-fixed8k"]["request_count"], 343)
                frozen = json.loads(candidate.FROZEN_PATH.read_text())
                self.assertTrue(frozen["p2_authorised"])
                frozen["seeds"] = 3
                candidate.FROZEN_PATH.write_text(json.dumps(frozen))
                with self.assertRaises(RuntimeError):
                    candidate.main_plan()
            finally:
                (candidate.TRACE_DIR, candidate.MANIFEST_PATH,
                 candidate.FROZEN_PATH, candidate.SOURCE_LOCK_PATH) = originals


if __name__ == "__main__":
    unittest.main()

