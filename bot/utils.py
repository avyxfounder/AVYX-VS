from pathlib import Path
import uuid

def new_job_dir(root: str) -> Path:
    path = Path(root) / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path

def cleanup(path: Path) -> None:
    if not path.exists():
        return
    for p in sorted(path.rglob("*"), reverse=True):
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            p.rmdir()
    path.rmdir()
