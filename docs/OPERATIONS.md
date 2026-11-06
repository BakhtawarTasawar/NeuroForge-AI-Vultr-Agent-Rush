# NeuroForge AI — Operations, Monitoring & Disaster Recovery

This manual outlines operational routines, backup strategies, monitoring checks, and troubleshooting protocols for NeuroForge AI.

---

## 1. Daily Health & Status Checks

### 1.1 PostgreSQL Database Verification
Check container status and listen port:
```powershell
docker ps --filter "name=neuroforge-postgres"
Test-NetConnection -ComputerName 127.0.0.1 -Port 5440
```

### 1.2 Backend Service & Inference Telemetry
Query the health check endpoint:
```bash
curl -s http://localhost:8020/health
```
Expected response:
```json
{
  "status": "healthy",
  "service": "NeuroForge AI",
  "version": "0.1.0",
  "environment": "development",
  "database": "healthy",
  "vultr_inference_configured": true,
  "vultr_inference_model": "deepseek-v4.1-flash-1017"
}
```

---

## 2. Backup & Recovery Protocols

### 2.1 Automated PostgreSQL Backup
Create a timestamped logical dump of the `neuroforge` database:
```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
docker exec neuroforge-postgres pg_dump -U neuroforge_app -d neuroforge -F c -f "/var/lib/postgresql/data/neuroforge_backup_${timestamp}.dump"
```

### 2.2 Backup Verification
Verify dump validity:
```powershell
docker exec neuroforge-postgres pg_restore --list "/var/lib/postgresql/data/neuroforge_backup_${timestamp}.dump"
```

### 2.3 Disaster Recovery / Restore Procedure
To restore the database from a backup file:
```powershell
docker exec neuroforge-postgres pg_restore -U neuroforge_app -d neuroforge --clean --if-exists "/var/lib/postgresql/data/neuroforge_backup_<TIMESTAMP>.dump"
```

---

## 3. Storage & Artifact Management

- Uploaded matrices are stored under `backend/data/uploads/`.
- Experiment output artifacts (differential expression CSVs, volcano plots, PCA scree charts) are stored under `backend/data/artifacts/<EXPERIMENT_ID>/`.
- All file access uses path sanitization (`resolve_safe_path`) preventing directory traversal attacks.
- Do not commit large CSV files or output artifacts to source control.

---

## 4. Troubleshooting Common Issues

### 4.1 Database Connection Timeout on Port 5440
- **Symptom**: `OperationalError: connection to server at "127.0.0.1", port 5440 failed`.
- **Resolution**:
  1. Verify Docker Desktop is running.
  2. Start the container if stopped: `docker start neuroforge-postgres`.
  3. Confirm port binding: `docker port neuroforge-postgres`.

### 4.2 Sandbox Execution Timeout or Docker Error
- **Symptom**: `Experiment execution timed out (60.0s)` or `Cannot connect to the Docker daemon`.
- **Resolution**:
  1. Verify Docker daemon is responsive: `docker info`.
  2. Rebuild the sandbox image if missing:
     ```bash
     docker build -t neuroforge-sandbox:local -f infrastructure/sandbox/Dockerfile infrastructure/sandbox
     ```

### 4.3 Vultr Serverless Inference Failures
- **Symptom**: Agent formulation fails or returns 502/504 status.
- **Resolution**:
  1. Confirm `VULTR_INFERENCE_API_KEY` is present and valid.
  2. Confirm `VULTR_INFERENCE_BASE_URL` is set to `https://api.vultrinference.com/v1`.
  3. Verify model identifier is set to `deepseek-v4.1-flash-1017`.

