import os
import re
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


def save_upload_file(content: bytes, original_filename: str) -> Tuple[str, Path]:
    """
    Store uploaded file safely using a UUID-prefixed filename in the upload directory.
    Returns (stored_filename, full_file_path).
    """
    upload_dir = get_upload_dir()
    _, ext = os.path.splitext(original_filename.lower())
    clean_ext = re.sub(r"[^a-z0-9.]", "", ext)

    stored_filename = f"dataset_{uuid.uuid4().hex}{clean_ext}"
    target_path = resolve_safe_path(upload_dir, stored_filename)

    with open(target_path, "wb") as f:
        f.write(content)

    return stored_filename, target_path

