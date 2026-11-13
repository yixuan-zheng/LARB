"""CPU compatibility checks. No checkpoint weights, decoding, or outcome labels."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from transformers import Qwen3Config, Qwen3ForCausalLM

from probing.features import get_prefix_hidden_states
from probing.probes import train_eval_probe

REPO = Path(__file__).resolve().parents[2]
RUNS = [
    REPO / 'week6/shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix',
    REPO / 'week7/recoverable-step/results/job-6958397',
]


class FixtureTokenizer:
    """Give the upstream helper exact prompt IDs without text re-tokenization."""

    def __call__(self, *_args, **_kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(input_ids=torch.tensor([[1, 2, 3, 4]]))

    def decode(self, ids, **_kwargs):
        return 'fixture'


class CpuChecks(unittest.TestCase):
    def test_upstream_extraction_and_causal_slice(self):
        torch.manual_seed(356)
        model = Qwen3ForCausalLM(Qwen3Config(
            vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
            num_attention_heads=4, num_key_value_heads=2, head_dim=8,
        )).eval()
        gen = torch.tensor([5, 6, 7, 8, 9, 10, 11, 12])
        states = get_prefix_hidden_states(model, FixtureTokenizer(), 'fixture', gen, [0, 4, 8], 8)
        with torch.inference_mode():
            ids = torch.cat((torch.arange(1, 5), gen))[None]
            final = model.model(input_ids=ids, use_cache=False).last_hidden_state[0]
            for checkpoint in (4, 8):
                np.testing.assert_allclose(states[checkpoint]['h_t'],
                                           final[checkpoint:checkpoint+4].mean(dim=0).numpy(),
                                           rtol=1e-5, atol=1e-6)
            np.testing.assert_allclose(states[0]['h_t'], final[3].numpy(), rtol=1e-5, atol=1e-6)
            logits = model(input_ids=ids, use_cache=False, logits_to_keep=1).logits
            self.assertEqual(tuple(logits.shape), (1, 1, 64))

    def test_upstream_probe_and_grouping(self):
        rng = np.random.default_rng(356)
        labels = np.repeat([0, 1], 30)
        x = rng.normal(size=(60, 8))
        x[:, 0] += 8*labels
        self.assertGreater(train_eval_probe(x, labels, seed=356)['auc'], .9)
        questions = np.repeat(np.arange(30), 2)
        for train, test in GroupKFold(5).split(x, labels, groups=questions):
            self.assertFalse(set(questions[train]) & set(questions[test]))
            pca = PCA(n_components=min(128, x.shape[1], len(train)-1)).fit(x[train])
            np.testing.assert_allclose(pca.mean_, x[train].mean(axis=0))
        # Aggregated binomial likelihood equals eight binary rows per checkpoint.
        states = x[:4]
        counts = np.array([0, 2, 6, 8])
        options = dict(C=1.0, solver='liblinear', max_iter=1000)
        repeated = LogisticRegression(**options).fit(
            np.repeat(states, 8, axis=0), np.concatenate([np.r_[np.ones(k), np.zeros(8-k)] for k in counts]))
        weighted = LogisticRegression(**options).fit(
            np.repeat(states, 2, axis=0), np.tile([1, 0], 4),
            sample_weight=np.column_stack([counts, 8-counts]).ravel())
        np.testing.assert_allclose(repeated.predict_proba(states), weighted.predict_proba(states), atol=1e-7)

    def test_saved_inputs(self):
        for run, expected in zip(RUNS, (57, 58)):
            eligible = 0
            for path in (run / 'pairs').glob('q*-b*.json'):
                pair = json.loads(path.read_text())
                if not pair['eligible']:
                    continue
                prefix = pair['prefix_token_ids']
                self.assertEqual(len(prefix), 4096)
                digest = hashlib.sha256(json.dumps(prefix, separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(digest, pair['prefix_hash'])
                self.assertNotIn(151668, prefix)
                self.assertNotIn(151645, prefix)
                call = json.loads((run / 'calls' / f"{pair['key']}-prefix.json").read_text())
                self.assertEqual(call['input_token_ids'], pair['prompt_token_ids'])
                self.assertEqual(call['token_ids'], prefix)
                eligible += 1
            self.assertEqual(eligible, expected)


if __name__ == '__main__':
    unittest.main()
