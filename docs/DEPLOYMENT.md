# NeuroForge AI — Deployment & Setup Guide

This guide covers setup and deployment for NeuroForge AI.

---

## 1. Prerequisites

- **Docker Desktop**: Running with Linux container support.
- **Node.js**: v18+ (tested on Node.js 24 and npm 11).
- **Python**: 3.11+ (tested on Python 3.14).
- **Vultr Serverless Inference API Key**: Configured in `.env`.

---

## 2. Infrastructure Setup

### 2.1 PostgreSQL Database Container
NeuroForge uses a dedicated PostgreSQL 16 container running on host port `5440`:

```bash
docker run -d \
  --name neuroforge-postgres \
  -e POSTGRES_DB=neuroforge \
  -e POSTGRES_USER=neuroforge_app \
  -e POSTGRES_PASSWORD=<SECURE_PASSWORD> \
  -p 127.0.0.1:5440:5432 \
  -v neuroforge_postgres_data:/var/lib/postgresql/data \
  postgres:16-alpine
```

Verify database health:
```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 5440
```

### 2.2 Docker Execution Sandbox Image
Build the local non-root execution sandbox:
```bash
docker build -t neuroforge-sandbox:local -f infrastructure/sandbox/Dockerfile infrastructure/sandbox
```

Verify sandbox smoke test:
```bash
docker run --rm --network none --read-only --cap-drop ALL --user 10001:10001 neuroforge-sandbox:local python3 -c "import numpy, scipy, pandas; print('Sandbox OK')"
```

---

## 3. Backend Setup

1. Create and activate the Python virtual environment:
   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:
   Copy `.env.example` to `backend/.env` and update variables:
   - `DATABASE_URL`: `postgresql+psycopg://neuroforge_app:<PASSWORD>@127.0.0.1:5440/neuroforge`
   - `CHECKPOINT_DATABASE_URL`: `postgresql://neuroforge_app:<PASSWORD>@127.0.0.1:5440/neuroforge`
   - `VULTR_INFERENCE_API_KEY`: Your Vultr Serverless Inference API key.
   - `VULTR_INFERENCE_MODEL`: `deepseek-v4.1-flash-1017`
   - `JWT_SECRET_KEY`: High-entropy 32+ character random string.

4. Start the backend service:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
   ```

5. Verify backend health:
   ```bash
   curl http://localhost:8020/health
   ```

---

## 4. Frontend Setup

1. Install frontend dependencies:
   ```powershell
   cd frontend
   npm install
   ```

2. Configure environment:
   Ensure `frontend/.env.local` contains:
   ```
   VITE_API_BASE_URL=http://localhost:8020
   ```

3. Run in development mode:
   ```bash
   npm run dev
   ```
   Access at `http://localhost:5173`.

4. Run production build:
   ```bash
   npm run build
   ```
   The compiled static bundle is generated in `frontend/dist`.

---

## 5. Automated Testing Verification

Execute the test suite from the backend directory:
```powershell
cd backend
.\.venv\Scripts\pytest -v
```
All tests run in isolated in-memory test environments with zero risk to PostgreSQL application data.

