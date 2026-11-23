"""Stage the exact final pilot overlay in a disposable directory."""
import shutil
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
repository = here.parents[2]
destination = Path(sys.argv[1]).resolve()
destination.mkdir(parents=True)
reference = here / "reference"
rig = destination / "repo/week7/scaled-serving"
source = repository / "week7/scaled-serving"
shutil.copytree(source / "configs", rig / "configs")
package = rig / "code/larb_scaled"
shutil.copytree(source / "code/larb_scaled", package, ignore=shutil.ignore_patterns("__pycache__"))
for p in reference.glob("*"):
    if p.is_file():
        shutil.copy2(p, destination / p.name)
for p in (reference / "overlay").glob("*.py"):
    shutil.copy2(p, package / p.name)
print(destination)
