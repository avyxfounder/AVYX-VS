from pathlib import Path
import shutil
import uuid


def new_job_dir(root: str) -> Path:
    path = Path(root) / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup(path: Path) -> None:
    """Remove the entire temporary job directory, even after an error."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
