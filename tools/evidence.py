import hashlib
import json
import platform
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def provenance():
    paths=sorted([*ROOT.glob('rollout/**/*.py'),*ROOT.glob('tests/**/*.py'),*ROOT.glob('tools/**/*.py'),*ROOT.glob('containers/*.Dockerfile'),*ROOT.glob('.github/workflows/*.yml'),ROOT/'.dockerignore',ROOT/'pyproject.toml',ROOT/'requirements.txt',ROOT/'requirements.lock'])
    files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    return {'sha256':digest,'files':files}

def environment():
    return {'os':platform.system(),'release':platform.release(),'architecture':platform.machine(),'python':platform.python_version(),'execution':os.environ.get('SHIFTSTEAD_EXECUTION','unspecified; inspect invocation context')}


def atomic_json(path, value):
    import secrets
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with tmp.open('w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
