import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "summarize_gates", ROOT / "code/tools/summarize_gates.py")
summarize_gates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summarize_gates)

CUE = [7, 8, 9]


def raw_record(phase, condition, arm, question="q1", seed=1, tokens=None, output="\\boxed{42}",
               answer_tokens=5, capped=False, cue_start=100):
    token_ids = tokens if tokens is not None else ([1] * cue_start + CUE +
                                                   [2] * answer_tokens + [0])
    return dict(key=f"{condition}--{arm}--signal--{question}--{seed}", phase=phase,
                condition=condition, arm=arm, question_id=question, seed=seed,
                class_="signal", token_ids=token_ids, cue_ids=CUE, cue_start=cue_start,
                close_id=9, eos_id=0, answer_cap=8, complete=True, capped=capped,
                raw_output=output, reference="42", finished=10.0, received=0.0,
                initial_budget=8192, final_budget=4096, cut_events=[], preemptions=0)


def write_run(root, name, records, phases):
    folder = root / name
    (folder / "requests").mkdir(parents=True, exist_ok=True)
    (folder / "phases").mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(records):
        (folder / "requests" / f"r{index}.json").write_text(json.dumps(record))
    (folder / "phases.json").write_text(json.dumps(phases))
    for phase in phases:
        (folder / "phases" / f"{phase['name']}.json").write_text(json.dumps(phase))
    return folder


def phase(name, condition, arm, count=1):
    return dict(name=name, condition=condition, arm=arm, request_count=count,
                epoch=0.0, horizon_s=100.0, deadline_s=90.0, last_arrival_s=0.0,
                injection_valid=True)


class GateSummaryTests(unittest.TestCase):
    def test_graphs_pair_across_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tokens = [1] * 100 + CUE + [2] * 5 + [0]
            records = [raw_record("graphs-eager", "gate-graphs-eager", "fixed8k",
                                  tokens=tokens),
                       raw_record("graphs-graph", "gate-graphs-graph", "fixed8k",
                                  tokens=tokens)]
            folder = write_run(root, "graphs", records,
                               [phase("graphs-eager", "gate-graphs-eager", "fixed8k"),
                                phase("graphs-graph", "gate-graphs-graph", "fixed8k")])
            result = summarize_gates.gate_graphs(summarize_gates.load_run(folder))
            self.assertEqual(result["n"], 1)
            self.assertEqual(result["tokens_identical"], 1)
            self.assertEqual(result["cue_position_identical"], 1)
            self.assertTrue(result["pass_"])

    def test_graphs_detect_divergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [raw_record("graphs-eager", "gate-graphs-eager", "fixed8k"),
                       raw_record("graphs-graph", "gate-graphs-graph", "fixed8k",
                                  tokens=[1] * 100 + CUE + [3] * 5 + [0])]
            folder = write_run(root, "graphs", records,
                               [phase("graphs-eager", "gate-graphs-eager", "fixed8k"),
                                phase("graphs-graph", "gate-graphs-graph", "fixed8k")])
            result = summarize_gates.gate_graphs(summarize_gates.load_run(folder))
            self.assertEqual(result["tokens_identical"], 0)
            self.assertFalse(result["pass_"])

    def test_contract_pairs_by_arm_question_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [
                raw_record("contract-legacy-fixed4k", "gate-contract-legacy", "fixed4k"),
                raw_record("contract-short_boxed-fixed4k", "gate-contract-short_boxed",
                           "fixed4k", output="\\boxed{42}", answer_tokens=5),
            ]
            folder = write_run(root, "contract", records,
                               [phase("contract-legacy-fixed4k", "gate-contract-legacy",
                                      "fixed4k"),
                                phase("contract-short_boxed-fixed4k",
                                      "gate-contract-short_boxed", "fixed4k")])
            result = summarize_gates.gate_contract(summarize_gates.load_run(folder),
                                                   False)
            self.assertEqual(result["paired"]["n"], 1)
            self.assertEqual(result["paired"]["difference"], 0.0)

    def test_slope_counts_answer_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [
                raw_record("slope-gate-screen-fixed4k", "gate-screen", "fixed4k",
                           output="\\boxed{40}"),
                raw_record("slope-gate-screen-fixed6k", "gate-screen", "fixed6k",
                           output="\\boxed{42}"),
                raw_record("slope-gate-screen-fixed8k", "gate-screen", "fixed8k",
                           output="\\boxed{42}"),
            ]
            folder = write_run(root, "slope", records,
                               [phase("slope-gate-screen-fixed4k", "gate-screen", "fixed4k"),
                                phase("slope-gate-screen-fixed6k", "gate-screen", "fixed6k"),
                                phase("slope-gate-screen-fixed8k", "gate-screen", "fixed8k")])
            result = summarize_gates.gate_slope(summarize_gates.load_run(folder),
                                               False)
            self.assertEqual(result["gate-screen"]["answer_change_fraction"], 1.0)


if __name__ == "__main__":
    unittest.main()
