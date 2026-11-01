"""Print the Week 5 comparison tables from saved analysis files (CPU only)."""
import argparse
import json
from pathlib import Path

POLICIES = ['fixed2048', 'fixed4096', 'live', 'live_one']


def load(path):
    return json.loads(Path(path).read_text())


def main(root):
    root = Path(root)
    for summary_path in sorted(root.glob('results/*/analysis/summary.json')):
        data = load(summary_path)
        print(f"== {summary_path.parent.parent.name} | condition={data['condition']} "
              f"| outcomes={data['measured_outcomes']} | questions={data['unique_questions']} "
              f"| deadline={data['relative_deadline_seconds']:.1f}s")
        print(f"{'policy':>10} {'n':>3} {'on-time':>8} {'eventual':>9} {'median_s':>9} "
              f"{'slowest_s':>10} {'queue_s':>8} {'think':>7} {'out':>7} {'cuts':>5} {'bind':>5} "
              f"{'failures':>22}")
        for s in data['summary']:
            if not s['n']:
                continue
            print(f"{s['policy']:>10} {s['n']:>3} {s['correct_on_time']:>8} "
                  f"{s['completed_correct']:>9} "
                  f"{(s['median_client_seconds'] or 0):>9.1f} "
                  f"{(s['p95_client_seconds'] or 0):>10.1f} "
                  f"{(s['mean_queue_seconds'] or 0):>8.1f} {s['thinking_tokens']:>7} "
                  f"{s['output_tokens']:>7} {s['live_reductions']:>5} "
                  f"{s['binding_live_cutoffs']:>5} {json.dumps(s['failures']):>22}")
        cuts = data['binding_cut_to_finish_seconds']
        if cuts:
            print('cut->finish seconds:', [round(c, 1) for c in cuts])
        after = data['reduction_after_short_tokens']
        if after:
            print('tokens already past 2,048 when cut:', after)
        pairs = data['paired']
        if pairs:
            print(f"{'blk':>3} {'idx':>4} {'on-time 2048/4096/live/one':>28} "
                  f"{'eventual 2048/4096/live/one':>28} {'one-2048':>8}")
            for p in pairs:
                on = '/'.join(str(int(p['on_time'][k])) for k in POLICIES)
                ev = '/'.join(str(int(p['eventual'][k])) for k in POLICIES)
                print(f"{p['block']:>3} {p['index']:>4} {on:>28} {ev:>28} "
                      f"{p['live_one_minus_fixed2048']:>8}")
        print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    main(parser.parse_args().root)
