"""Shared model loading, FFN-width switching, and run metadata for the quality workstream."""
import hashlib
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import torch
import torch.nn.functional as F
import transformers
from transformers import AutoTokenizer, Gemma3nForConditionalGeneration

REPO = Path(__file__).resolve().parents[3]
QUALITY = REPO / "week1" / "quality"
MANIFESTS = QUALITY / "manifests"
RESULTS = QUALITY / "results"
PRESETS_PATH = REPO / "preflight" / "code" / "presets.json"
MODEL = "google/gemma-3n-E4B"
REVISION = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"

PRESET_FILE = json.loads(PRESETS_PATH.read_text())
PRESETS = PRESET_FILE["presets"]


def load_model(dtype=torch.bfloat16):
    assert torch.cuda.is_available()
    model = Gemma3nForConditionalGeneration.from_pretrained(
        MODEL, revision=REVISION, dtype=dtype, local_files_only=True
    ).eval().to("cuda")
    tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
    return model, tok


def text_layers(model):
    # the multimodal wrapper nests the text decoder one level deeper than Gemma3nForCausalLM
    return getattr(model.model, "language_model", model.model).layers


# same sliced FFN as preflight/code/pace_bounded_research.py: the first `width`
# hidden units of each layer form the nested submodel
def width_forward(mlp, x):
    width = mlp.active_width
    gate = F.linear(x, mlp.gate_proj.weight[:width])
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    up = F.linear(x, mlp.up_proj.weight[:width])
    return F.linear(mlp.act_fn(gate) * up, mlp.down_proj.weight[:, :width])


def patch_widths(model):
    layers = text_layers(model)
    for layer in layers:
        layer.mlp.forward = types.MethodType(width_forward, layer.mlp)
    return layers


def select(layers, preset):
    dims = PRESETS[preset]["ffn_hidden_dims"]
    assert len(dims) == len(layers)
    for layer, width in zip(layers, dims):
        layer.mlp.active_width = width


def new_run_id(name):
    return f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def run_manifest(run_id, seed, dtype=None, **extra):
    """Fields the Week 1 plan requires on every artifact."""
    return {
        "run_id": run_id,
        "seed": seed,
        "command": " ".join([Path(sys.executable).name, *sys.argv]),
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "model": MODEL,
        "model_revision": REVISION,
        "presets_sha256": hashlib.sha256(PRESETS_PATH.read_bytes()).hexdigest(),
        "presets_source_revision": PRESET_FILE["source_revision"],
        "hardware": torch.cuda.get_device_name() if torch.cuda.is_available() else "cpu",
        "dtype": dtype,
        "packages": {"torch": torch.__version__, "transformers": transformers.__version__},
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **extra,
    }


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")
