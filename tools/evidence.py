import hashlib
import json
import platform
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def provenance():
    paths=sorted([*ROOT.glob('rollout/*.py'),*ROOT.glob('tests/*.py'),*ROOT.glob('tools/*.py'),ROOT/'pyproject.toml',ROOT/'requirements.txt',ROOT/'requirements.lock'])
    files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    return {'sha256':digest,'files':files}

def environment():
    return {'os':platform.system(),'release':platform.release(),'architecture':platform.machine(),'python':platform.python_version(),'execution':os.environ.get('SHIFTSTEAD_EXECUTION','unspecified; inspect invocation context')}
