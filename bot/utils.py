from pathlib import Path
import shutil
import time
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
    """Remove a temporary job directory, even after an error."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def cleanup_stale_jobs(root: str, max_age_hours: int = 6) -> None:
    """Remove abandoned temporary jobs left by crashes/restarts."""
    base = Path(root)
    if not base.exists():
        return

    cutoff = time.time() - max_age_hours * 3600
    for path in base.iterdir():
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                cleanup(path)
        except OSError:
            pass
