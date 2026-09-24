"""Download the pinned gated E4B checkpoint to the caller's HF_HOME."""
import os
from pathlib import Path

from huggingface_hub import get_token, snapshot_download

REVISION = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"
MODEL = "google/gemma-3n-E4B"

hf_home = os.environ.get("HF_HOME")
if not hf_home:
    raise SystemExit("Set HF_HOME to your own project/scratch cache first.")
Path(hf_home).mkdir(parents=True, exist_ok=True)
if not get_token():
    raise SystemExit("Accept the model terms and run `hf auth login` in this environment first.")

snapshot_download(
    MODEL,
    revision=REVISION,
    allow_patterns=[
        "*.safetensors", "*.json", "tokenizer.model",
    ],
)
print("Pinned Gemma 3n E4B snapshot is available in HF_HOME.")
