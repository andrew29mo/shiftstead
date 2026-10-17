"""Write durable process identity before replacing this process with the worker."""
import json
import os
import sys
import sqlite3
from pathlib import Path
import psutil


def main():
    path, token, *command = sys.argv[1:]
    record = Path(path)
    tmp = record.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump({'pid': os.getpid(), 'created': psutil.Process().create_time(), 'token': token}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, record)
    fd = os.open(record.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    # A superseding operation can cancel launch before the parent receives its PID.
    # Check the durable launch intent after publishing identity and before exec.
    db = sqlite3.connect(record.parent / "state.sqlite")
    state = json.loads(db.execute("SELECT value FROM snapshot WHERE id=1").fetchone()[0])
    db.close()
    worker = state["workers"].get(record.stem)
    if not worker or worker.get("stopping") or worker["token"] != token:
        return
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    main()
