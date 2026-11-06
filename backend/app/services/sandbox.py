import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import settings
from app.db.models import ExperimentStatus
from app.services.storage import get_artifact_dir, get_upload_dir, resolve_safe_path

logger = logging.getLogger("neuroforge.sandbox")


@dataclass
class ExecutionResult:
    status: ExperimentStatus
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_seconds: float
    started_at: datetime
    completed_at: datetime
    artifacts: List[Dict[str, str]]
    result_summary: Optional[str]
    failure_reason: Optional[str]


def check_docker_available() -> bool:
    """Check if the Docker daemon is accessible and responding."""
    try:
        res = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return res.returncode == 0
    except Exception:
        return False


def sanitize_output(text: str, max_bytes: int) -> str:
    """Cap output length and sanitize host/workspace internal paths, container IDs, and sensitive tokens."""
    if not text:
        return ""
    # Truncate if larger than max_bytes
    encoded = text.encode("utf-8", errors="replace")
    truncated = False
    if len(encoded) > max_bytes:
        encoded = encoded[:max_bytes]
        truncated = True

    cleaned = encoded.decode("utf-8", errors="replace")
    # Redact common internal filesystem paths
    cleaned = re.sub(r"/(?:workspace|tmp|root|var|etc)/[^\s:\"']*", "[internal-path]", cleaned)
    cleaned = re.sub(r"/workspace/?", "", cleaned)
    cleaned = re.sub(r"[A-Za-z]:\\[^\s:\"']+", "[internal-path]", cleaned)
    # Redact container identifiers (nf_sandbox_[a-f0-9]+ or 64-char hex strings)
    cleaned = re.sub(r"nf_sandbox_[a-f0-9]+", "[sandbox-container]", cleaned)
    cleaned = re.sub(r"\b[0-9a-f]{64}\b", "[container-id]", cleaned)
    # Redact sensitive credential / secret patterns
    cleaned = re.sub(r"(?i)(secret|token|password|api[_-]?key|jwt)\s*[:=]\s*\S+", r"\1=[REDACTED]", cleaned)

    if truncated:
        cleaned += "\n\n[Output truncated: maximum display limit reached]"
    return cleaned


def get_content_type(filename: str) -> str:
    """Infer safe content type for artifacts."""
    lower = filename.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".tsv") or lower.endswith(".txt"):
        return "text/plain"
    if lower.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


class SandboxExecutionService:
    @staticmethod
    def execute(
        experiment_id: str,
        code: str,
        dataset_filename: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Execute scientific Python experiment inside a restricted Docker sandbox container.
        Enforces Blast Radius Zero parameters:
        - Non-root user (10001:10001)
        - Network disabled (--network none)
        - Read-only root filesystem (--read-only)
        - Dropped Linux capabilities (--cap-drop ALL)
        - No new privileges (--security-opt no-new-privileges)
        - Strict memory (512m), CPU (1.0), and pids limit (64)
        - Ephemeral workspace cleanup
        """
        if not check_docker_available():
            now = datetime.now(timezone.utc)
            return ExecutionResult(
                status=ExperimentStatus.FAILED,
                exit_code=None,
                stdout="",
                stderr="The isolated scientific execution container service is currently unreachable.",
                duration_seconds=0.0,
                started_at=now,
                completed_at=now,
                artifacts=[],
                result_summary=None,
                failure_reason="Execution sandbox service is currently unavailable. Please verify Docker is running.",
            )

        timeout = timeout_seconds or settings.SANDBOX_TIMEOUT_SECONDS
        # Create ephemeral workspace directory
        workspace_base = Path(settings.WORKSPACE_DIR).resolve()
        workspace_base.mkdir(parents=True, exist_ok=True)
        workspace_dir = (workspace_base / f"run_{experiment_id}").resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)

        container_name = f"nf_sandbox_{uuid.uuid4().hex[:12]}"
        script_path = workspace_dir / "experiment.py"

        # Prepare experiment script
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        # Copy attached dataset if provided
        if dataset_filename:
            try:
                upload_dir = get_upload_dir()
                source_dataset = resolve_safe_path(upload_dir, dataset_filename)
                if source_dataset.exists():
                    target_dataset = workspace_dir / "dataset.csv"
                    shutil.copyfile(source_dataset, target_dataset)
                    # Protect dataset as read-only on disk
                    try:
                        os.chmod(target_dataset, 0o444)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Could not copy dataset into sandbox workspace: {e}")

        # Docker execution command
        # Note: -v workspace_dir:/workspace:rw mounts only the isolated workspace
        cmd = [
            "docker",
            "run",
            "--name",
            container_name,
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(settings.SANDBOX_PIDS_LIMIT),
            "--memory",
            settings.SANDBOX_MEMORY_LIMIT,
            "--cpus",
            settings.SANDBOX_CPU_LIMIT,
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--user",
            "10001:10001",
            "-v",
            f"{str(workspace_dir)}:/workspace:rw",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            "-w",
            "/workspace",
            settings.SANDBOX_IMAGE,
            "python3",
            "/workspace/experiment.py",
        ]

        started_at = datetime.now(timezone.utc)
        start_time = time.monotonic()
        timed_out = False
        raw_stdout = ""
        raw_stderr = ""
        exit_code: Optional[int] = None

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            raw_stdout = proc.stdout
            raw_stderr = proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as e:
            timed_out = True
            raw_stdout = e.stdout if isinstance(e.stdout, str) else ""
            raw_stderr = e.stderr if isinstance(e.stderr, str) else ""
            # Force kill container if timed out
            try:
                subprocess.run(["docker", "kill", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        except Exception as e:
            raw_stderr = f"Container execution error: {str(e)}"
            exit_code = 1
        finally:
            # Guarantee container removal in all termination paths
            try:
                subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            elapsed = round(time.monotonic() - start_time, 2)
            completed_at = datetime.now(timezone.utc)

        # Collect artifacts before cleaning up workspace
        artifacts: List[Dict[str, str]] = []
        artifact_dir = get_artifact_dir(experiment_id)

        try:
            for item in workspace_dir.iterdir():
                # Skip the input script and input dataset
                if item.name in ["experiment.py", "dataset.csv"]:
                    continue
                # Block symlink traversal attacks
                if item.is_symlink():
                    logger.warning(f"Rejecting symlink artifact in sandbox: {item.name}")
                    continue
                if item.is_file():
                    # Validate artifact destination against path traversal
                    try:
                        dest = resolve_safe_path(artifact_dir, item.name)
                    except PermissionError:
                        logger.warning(f"Path traversal blocked for artifact: {item.name}")
                        continue

                    # Reject oversized artifacts (> 50 MB)
                    if item.stat().st_size > 50 * 1024 * 1024:
                        logger.warning(f"Rejecting oversized artifact: {item.name} ({item.stat().st_size} bytes)")
                        continue

                    shutil.copyfile(item, dest)
                    size_bytes = dest.stat().st_size
                    artifacts.append({
                        "filename": item.name,
                        "size_bytes": str(size_bytes),
                        "content_type": get_content_type(item.name),
                        "download_url": f"/experiments/{experiment_id}/artifacts/{item.name}",
                    })
        except Exception as e:
            logger.warning(f"Error cataloging sandbox artifacts: {e}")

        # Always remove ephemeral workspace directory
        try:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        except Exception:
            pass

        # Sanitize outputs
        stdout = sanitize_output(raw_stdout, settings.SANDBOX_MAX_OUTPUT_BYTES)
        stderr = sanitize_output(raw_stderr, settings.SANDBOX_MAX_OUTPUT_BYTES)

        # Categorize outcome
        status: ExperimentStatus
        failure_reason: Optional[str] = None
        result_summary: Optional[str] = None

        if timed_out:
            status = ExperimentStatus.TIMED_OUT
            failure_reason = f"Experiment exceeded maximum execution time boundary of {timeout} seconds."
        elif exit_code == 137:
            status = ExperimentStatus.FAILED
            failure_reason = "Experiment exceeded the 512 MB memory boundary and was terminated."
        elif exit_code == 0:
            status = ExperimentStatus.COMPLETED
            # Check for a structured output file or summary in stdout
            summary_info = {
                "execution_state": "Completed successfully",
                "duration_seconds": elapsed,
                "artifacts_generated": len(artifacts),
            }
            result_summary = json.dumps(summary_info)
        else:
            status = ExperimentStatus.FAILED
            if "MemoryError" in stderr:
                failure_reason = "Out of memory during scientific computation."
            elif "SyntaxError" in stderr:
                failure_reason = "Scientific script contained a syntax error."
            elif "ZeroDivisionError" in stderr:
                failure_reason = "Division by zero encountered in calculation."
            elif "ModuleNotFoundError" in stderr or "ImportError" in stderr:
                failure_reason = "Script requested a package not permitted in the minimal scientific sandbox."
            else:
                failure_reason = "Execution completed with a non-zero exit status."

        return ExecutionResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=elapsed,
            started_at=started_at,
            completed_at=completed_at,
            artifacts=artifacts,
            result_summary=result_summary,
            failure_reason=failure_reason,
        )

