"""PACE gated-access check: fetch config/tokenizer only, never model weights."""
import hashlib
import json
import os
from pathlib import Path

from huggingface_hub import HfApi, get_token, hf_hub_download
from transformers import AutoConfig, AutoTokenizer

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT.parent / "run-output"
OUTPUT_DIR.mkdir(exist_ok=True)
expected = json.loads((ROOT / "access_status.json").read_text())
repo, revision = expected["model"], expected["revision"]
hf_home = Path(os.environ["HF_HOME"]).resolve()
assert hf_home.is_dir(), "Set HF_HOME to a writable cache directory before running this check"
assert get_token(), "PACE Hugging Face login missing"
info = HfApi().model_info(repo_id=repo, revision=revision)
assert info.sha == revision
files = {}
for name, record in expected["files"].items():
    path = Path(hf_hub_download(repo, name, revision=revision))
    assert path.resolve().is_relative_to(hf_home), (name, path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == record["sha256"], name
    files[name] = {"bytes": path.stat().st_size, "sha256": actual}
config = AutoConfig.from_pretrained(repo, revision=revision, local_files_only=True)
assert config.text_config.num_hidden_layers == 35
assert list(config.text_config.intermediate_size) == [16384] * 35
tokenizer = AutoTokenizer.from_pretrained(repo, revision=revision, local_files_only=True)
ids = tokenizer("Gemma width smoke test", return_tensors="pt")["input_ids"]
assert ids.shape[1] >= 3
status = {
    "model": repo, "revision": revision, "authenticated": True,
    "config_and_tokenizer_access": True,
    "downloaded_weight_files": False, "files": files,
    "tokenizer_sample_tokens": int(ids.shape[1]),
}
(OUTPUT_DIR / "pace_access_status.json").write_text(json.dumps(status, indent=2) + "\n")
print("PASS: authenticated PACE access to pinned Gemma 3n E4B config and tokenizer")
print("revision", revision,
      "metadata_bytes", sum(item["bytes"] for item in files.values()))
