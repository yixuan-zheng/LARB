"""Explicit freeze before deployment; run is read-only against this lock."""
from protocol import HERE, REPO, atomic, sha

if __name__=='__main__':
    files=[p for p in HERE.rglob('*') if p.is_file()
           and '__pycache__' not in p.parts and p.name!='source-lock.json']
    files.append(REPO/'week6/aime-budget-screen/common.py')
    atomic(HERE/'source-lock.json',{str(p.relative_to(REPO)):sha(p) for p in sorted(files)})
