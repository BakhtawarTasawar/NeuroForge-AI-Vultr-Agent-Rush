import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Tuple

from app.core.config import settings


def get_base_data_dir() -> Path:
    # Resolve relative to backend root or repository root
    data_path = Path(settings.UPLOAD_DIR).parent.resolve()
    data_path.mkdir(parents=True, exist_ok=True)
    return data_path


def get_upload_dir() -> Path:
    path = Path(settings.UPLOAD_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_temp_upload_dir() -> Path:
    """Secure staging directory on the same filesystem to support atomic moves."""
    temp_path = (get_upload_dir() / ".tmp").resolve()
    temp_path.mkdir(parents=True, exist_ok=True)
    return temp_path


def get_artifact_dir(experiment_id: str) -> Path:
    # Sanitize experiment_id
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", experiment_id)
    path = (Path(settings.ARTIFACT_DIR) / safe_id).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_safe_path(base_dir: Path, filename: str) -> Path:
    """
    Ensure the target path is strictly within base_dir.
    Rejects any path traversal attempt (e.g. '../', '/etc/passwd').
    """
    # Disallow absolute paths in filename or path traversal sequences
    clean_name = os.path.basename(filename.strip().replace("\\", "/"))
    target = (base_dir / clean_name).resolve()

    base_resolved = base_dir.resolve()
    try:
        target.relative_to(base_resolved)
    except ValueError:
        raise PermissionError(f"Access denied: path traversal detected for filename '{filename}'.")

    return target


def get_dataset_file_path(filename: str) -> Path:
    """Resolve and validate a dataset's absolute filesystem path within secure upload storage."""
    upload_dir = get_upload_dir()
    return resolve_safe_path(upload_dir, filename)


def save_upload_from_file(source_path: Path, original_filename: str) -> Tuple[str, Path]:
    """
    Atomically persist an already uploaded temporary file into the secure storage directory.
    Guarantees no partial files are visible in the upload directory.
    Returns (stored_filename, full_file_path).
    """
    upload_dir = get_upload_dir()
    _, ext = os.path.splitext(original_filename.lower())
    clean_ext = re.sub(r"[^a-z0-9.]", "", ext)

    stored_filename = f"dataset_{uuid.uuid4().hex}{clean_ext}"
    target_path = resolve_safe_path(upload_dir, stored_filename)

    # Perform atomic replace
    try:
        os.replace(source_path, target_path)
    except OSError:
        # Cross-filesystem or boundary fallback: stage inside target filesystem then atomic replace
        temp_dir = get_temp_upload_dir()
        staging_path = resolve_safe_path(temp_dir, f"stage_{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(source_path, staging_path)
            os.replace(staging_path, target_path)
            try:
                source_path.unlink()
            except OSError:
                pass
        except Exception:
            if staging_path.exists():
                try:
                    staging_path.unlink()
                except OSError:
                    pass
            raise

    return stored_filename, target_path


def save_upload_file(content: bytes, original_filename: str) -> Tuple[str, Path]:
    """
    Store uploaded file bytes safely using atomic staging to prevent partial files.
    Preserves backward compatibility for callers passing raw bytes.
    Returns (stored_filename, full_file_path).
    """
    upload_dir = get_upload_dir()
    _, ext = os.path.splitext(original_filename.lower())
    clean_ext = re.sub(r"[^a-z0-9.]", "", ext)

    stored_filename = f"dataset_{uuid.uuid4().hex}{clean_ext}"
    target_path = resolve_safe_path(upload_dir, stored_filename)

    temp_dir = get_temp_upload_dir()
    temp_target = resolve_safe_path(temp_dir, f"part_{uuid.uuid4().hex}.tmp")

    try:
        with open(temp_target, "wb") as f:
            f.write(content)
        os.replace(temp_target, target_path)
    except Exception:
        if temp_target.exists():
            try:
                temp_target.unlink()
            except OSError:
                pass
        raise

    return stored_filename, target_path

