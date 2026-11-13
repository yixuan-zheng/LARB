"""Frozen configuration loading and hashing for the scaled rig."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SCALED_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = SCALED_ROOT / "configs"
DATA_DIR = SCALED_ROOT / "data"
ARTIFACTS_DIR = SCALED_ROOT / "artifacts"
LOGS_DIR = SCALED_ROOT / "logs"
RESULTS_DIR = SCALED_ROOT / "results"
REPORTS_DIR = SCALED_ROOT / "reports"

REQUIRED_ARMS = ("fixed4k", "fixed8k", "arrival", "live")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_protocol():
    return read_json(CONFIG_DIR / "protocol.json")


def load_datasets():
    return read_json(CONFIG_DIR / "datasets.json")


def load_p1_gates():
    return read_json(CONFIG_DIR / "p1_gates.json")


def load_p2_main():
    return read_json(CONFIG_DIR / "p2_main.json")


def load_cohort():
    return read_json(ARTIFACTS_DIR / "cohort.json")


def load_questions():
    path = DATA_DIR / "processed/questions.jsonl"
    rows = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def validate_protocol(protocol):
    if protocol.get("schema_version") != 1:
        raise ValueError("unsupported protocol schema")
    engine = protocol["engine"]
    if engine["max_num_batched_tokens"] < engine["max_num_seqs"]:
        raise ValueError("max_num_batched_tokens must be >= max_num_seqs")
    budgets = protocol["budgets"]
    if not 0 < budgets["short"] < budgets["long"] <= budgets["safety"]:
        raise ValueError("invalid budget ordering")
    if budgets["cut_target"] >= budgets["long"]:
        raise ValueError("cut target must be below the long budget")
    if engine["max_model_len"] < budgets["long"] + protocol["answer_contracts"]["legacy"]["answer_cap"] + 16:
        raise ValueError("max_model_len is too small for long budget + legacy answer cap")
    for arm in REQUIRED_ARMS:
        if arm not in protocol["policy"]["arms"]:
            raise ValueError(f"missing arm {arm}")
    pressure = protocol["policy"]["pressure"]
    threshold = max(pressure["threshold_minimum"],
                    int(-(-pressure["threshold_fraction"] * engine["max_num_seqs"] // 1)))
    if threshold not in pressure["threshold_grid"]:
        raise ValueError("default pressure threshold is not in the pre-declared grid")
    if protocol["workload"]["seeds_per_question"] < 2:
        raise ValueError("at least two seeds are required for pairing")
    return True


def validate_all():
    protocol = load_protocol()
    validate_protocol(protocol)
    p1 = load_p1_gates()
    p2 = load_p2_main()
    if set(p2["arms"]) != set(REQUIRED_ARMS):
        raise ValueError("p2 arms must match the protocol arms")
    if p2["signal_questions"] > protocol["workload"]["signal_questions_max"]:
        raise ValueError("p2 signal_questions exceeds the protocol maximum")
    return protocol, p1, p2


def config_hashes():
    return {str(path.relative_to(SCALED_ROOT)): digest(path)
            for path in sorted(CONFIG_DIR.glob("*.json"))}


def code_hashes():
    files = sorted((SCALED_ROOT / "code").rglob("*.py"))
    return {str(path.relative_to(SCALED_ROOT)): digest(path) for path in files}


def artifact_hashes():
    paths = []
    for folder in (DATA_DIR / "processed", ARTIFACTS_DIR / "traces"):
        if folder.exists():
            paths.extend(sorted(path for path in folder.glob("*") if path.is_file()))
    cohort = ARTIFACTS_DIR / "cohort.json"
    if cohort.exists():
        paths.append(cohort)
    return {str(path.relative_to(SCALED_ROOT)): digest(path) for path in paths}


def freeze_manifest(extra=None):
    manifest = {
        "created_at": utc_now(),
        "configs": config_hashes(),
        "code": code_hashes(),
        "artifacts": artifact_hashes(),
    }
    if extra:
        manifest.update(extra)
    write_json(ARTIFACTS_DIR / "freeze.json", manifest)
    return manifest
