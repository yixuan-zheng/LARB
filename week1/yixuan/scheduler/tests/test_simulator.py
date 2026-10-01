import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator import (
    Latencies,
    load_quality,
    load_trace,
    make_example_latencies,
    simulate,
)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lat_path = self.root / "lat.csv"
        make_example_latencies(self.lat_path)
        self.lat = Latencies(self.lat_path, allow_nearest_example=True)
        self.config = dict(
            pressure_threshold=2,
            minimum_dwell_tokens=1,
            max_batch_size=8,
            ttft_slo_ms=None,
            itl_slo_ms=None,
            allowed_switches=[["large", "small"], ["small", "large"]],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def trace(self, rows):
        path = self.root / "trace.json"
        path.write_text(json.dumps(dict(seed=9, requests=rows)))
        return path

    def req(self, ident, arrival=0, output=3):
        return dict(
            request_id=ident,
            arrival_ms=arrival,
            prompt_tokens=128,
            output_tokens=output,
            estimated_output_tokens=4,
        )

    def test_arrival_order_and_same_replay(self):
        trace = self.trace([self.req("late", 50), self.req("early", 0)])
        _, loaded = load_trace(trace)
        self.assertEqual([r.request_id for r in loaded], ["early", "late"])
        for policy in ("static_large", "static_small", "request", "iteration"):
            results, _, _ = simulate(trace, self.lat, policy, self.config)
            self.assertEqual({r["request_id"] for r in results}, {"early", "late"})
            self.assertEqual(
                sum(r["output_tokens"] for r in results),
                sum(len(r["decode_presets"].split("|")) for r in results),
            )

    def test_transition_replaces_decode_and_cache_retained(self):
        trace = self.trace([self.req("a", 0, 8), self.req("b", 1, 3)])
        _, logs, _ = simulate(trace, self.lat, "iteration", self.config)
        for row in logs:
            self.assertGreaterEqual(row["end_ms"], row["start_ms"])
        # A transition is one logged token operation, never followed by a duplicate
        # fixed-width step for that same request and token.
        transition = [x for x in logs if x["operation"] == "transition_decode"]
        self.assertTrue(transition)
        for x in transition:
            self.assertNotEqual(x["from_preset"], x["preset"])
        results, _, _ = simulate(trace, self.lat, "iteration", self.config)
        self.assertEqual(
            sum(r["output_tokens"] for r in results),
            sum(len(r["decode_presets"].split("|")) for r in results),
        )
        self.assertFalse(any(x["operation"] == "recompute" for x in logs))

    def test_mixed_width_separate_operations(self):
        trace = self.trace([self.req("a", 0, 5), self.req("b", 1, 4)])
        _, logs, _ = simulate(trace, self.lat, "request", self.config)
        decode = [row for row in logs if row["operation"] == "decode"]
        self.assertEqual({row["preset"] for row in decode}, {"large", "small"})
        self.assertFalse(
            any(set(row["request_ids"].split("|")) == {"a", "b"} for row in decode)
        )
        self.assertTrue(
            all(
                logs[i]["end_ms"] <= logs[i + 1]["start_ms"]
                for i in range(len(logs) - 1)
            )
        )

    def test_missing_measured_cell_fails(self):
        with self.lat_path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            row["run_id"] = "REAL_RUN"
        with self.lat_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        real = Latencies(self.lat_path, allow_nearest_example=True)
        with self.assertRaisesRegex(ValueError, "Missing latency cell"):
            real.cost("decode", "large", 3, 128)

    def test_repeat_aggregation_and_transition_cost(self):
        values = [
            float(r["latency_ms"]) / int(r["tokens_timed"])
            for r in self.lat.raw
            if r["phase"] == "transition_decode"
            and r["preset"] == "small"
            and r["batch_size"] == "1"
            and r["context_tokens"] == "128"
        ]
        cost, _ = self.lat.cost("transition_decode", "small", 1, 128, "large")
        self.assertAlmostEqual(cost, sum(values) / 2)

    def test_quality_zero_based_validation(self):
        path = self.root / "quality.jsonl"
        path.write_text(
            json.dumps(dict(schedule=[dict(start_decode_token=1, preset="small")]))
            + "\n"
        )
        with self.assertRaisesRegex(ValueError, "start at zero"):
            load_quality(path)


if __name__ == "__main__":
    unittest.main()
