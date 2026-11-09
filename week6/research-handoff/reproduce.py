"""Reproduce the Week 6 CPU results from the bundled evidence."""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args, cwd=None):
    return subprocess.check_output([sys.executable, "-B", *map(str, args)], cwd=cwd, text=True)


def reproduce_files(directory, filenames, command):
    expected = {name: (directory / name).read_bytes() for name in filenames}
    command()
    for name, content in expected.items():
        assert (directory / name).read_bytes() == content, directory / name


def verify_sources(repository, folder, expected_lock):
    lock = folder / "source-lock.json"
    assert digest(lock) == expected_lock, lock
    for name, expected in read(lock).items():
        assert digest(repository / name) == expected, name
    run("-m", "unittest", "discover", "-s", folder, "-p", "test_*.py")


def rebuild_packets(study, prefix, question_prefix):
    questions = {row["id"]: row["problem"] for row in read(prefix / "questions.json")}
    rows = {row["key"]: row for row in read(prefix / "graded-pairs.json")}
    mapping = read(study / "private-mapping.json")
    plan = read(study / "PLAN.json")
    frozen = read(study / "freeze-sha256.json")
    for reader, cases in mapping.items():
        question_only = question_prefix and reader.startswith("q")
        folder = study / reader / "cases"
        folder.mkdir()
        for case_id, item in cases.items():
            question_id = item if question_only else rows[item]["id"]
            packet = {"case_id": case_id}
            if question_prefix:
                packet["condition"] = "question" if question_only else "prefix"
            packet["question"] = questions[question_id]
            if not question_only:
                call = read(prefix / "calls" / f"{item}-prefix.json")
                packet["prefix"] = call["raw_output"]
            path = folder / f"{case_id}.json"
            path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
            original = Path(plan["packet_roots"][reader]) / "cases" / path.name
            assert digest(path) == frozen[str(original)], original


def main():
    results = read(HERE / "results.json")
    archive = HERE / "evidence.tar.gz"
    assert digest(archive) == results["archive_sha256"]
    with tempfile.TemporaryDirectory(prefix="larb-reproduce-") as temp:
        repository = Path(temp)
        with tarfile.open(archive, "r:gz") as handle:
            for member in handle.getmembers():
                name = Path(member.name)
                assert not name.is_absolute() and ".." not in name.parts
                assert name.parts[0] == "week6" and (member.isdir() or member.isfile())
            handle.extractall(repository)
        week = repository / "week6"
        shutil.copytree(HERE / "code", week, dirs_exist_ok=True)
        engine_code = week / "engine-entry-pilot"
        prefix_code = week / "shared-prefix-study"
        verify_sources(repository, engine_code, results["engine_entry"]["source_lock_sha256"])
        verify_sources(repository, prefix_code, results["shared_prefix"]["source_lock_sha256"])

        engine = next(week.glob("engine-entry-results/*/job-6827065-engine-entry"))
        for index in range(2):
            block = engine / f"block{index}"
            reproduce_files(block, ["summary.json", "review-queue.json"],
                             lambda: run(engine_code / "analyze.py", "--root", block))
            probe = """import json
import sys
from pathlib import Path
from gate import verify
print(json.dumps(verify(Path(sys.argv[1]))))
"""
            assert json.loads(run("-c", probe, block, cwd=engine_code)) == read(block / "queue-gate.json")
        reproduce_files(engine, ["h1-decision.json"], lambda: run(engine_code / "evaluate.py", engine))
        assert read(engine / "h1-decision.json") == results["engine_entry"]["result"]
        print("Engine entry: 86 responses, both gates, frozen H1 decision")

        prefix = next(week.glob("shared-prefix-results/*/job-6878140-shared-prefix"))
        reproduce_files(prefix, ["decision.json", "graded-pairs.json", "extraction-review.json"],
                         lambda: run(prefix_code / "analyze.py", prefix))
        assert read(prefix / "decision.json") == results["shared_prefix"]["result"]
        (prefix / "sources").symlink_to(repository, target_is_directory=True)
        reproduce_files(prefix.parent, ["AUDIT.json"], lambda: run(prefix.parent / "audit.py"))
        print("Shared prefixes: 60 instances, 183 calls, frozen decision and token audit")

        diagnosis = week / "exploratory-signal-diagnosis"

        def diagnose():
            run(diagnosis / "diagnose.py")
            run(diagnosis / "supplement.py")

        reproduce_files(diagnosis, ["summary.json"], diagnose)
        assert read(diagnosis / "summary.json") == results["diagnosis"]
        print("Signal diagnosis: 57 eligible prefixes and paid readout analysis")

        for name, key, question_prefix in [
            ("blinded-prefix-annotation", "blinded_annotation", False),
            ("question-prefix-comparison", "question_prefix", True),
        ]:
            study = week / name
            for filename, expected in read(study / "analysis-code-sha256.json").items():
                assert digest(study / filename) == expected
            rebuild_packets(study, prefix, question_prefix)
            reproduce_files(study, ["RESULTS.json"], lambda: run(study / "evaluate.py"))
            assert read(study / "RESULTS.json") == results[key]
            if not question_prefix:
                reproduce_files(study, ["SUPPLEMENT.json"], lambda: run(study / "supplement.py"))
            print(f"{name}: sealed judgments and frozen decision reproduced")


if __name__ == "__main__":
    main()
