# NeuroForge AI

> **From Scientific Data to Autonomous Discovery.**

NeuroForge AI is an autonomous scientific experimentation platform designed to assist researchers in exploring complex scientific datasets, formulating testable hypotheses, planning machine-learning and statistical experiments, executing them in isolated execution environments, and evaluating evidence-backed results.

Initial research domain: **Cancer gene-expression transcriptomic analysis**.

*Disclaimer: NeuroForge AI is a scientific research and discovery tool, not a clinical diagnostic system or medical treatment recommendation tool.*

---

## Technology Stack

- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, Axios, Lucide Icons.
- **Backend / Control Plane**: Python 3, FastAPI, Pydantic v2, Uvicorn, Pytest, HTTPX.
- **Target Platform & Cloud**: Vultr Agent Rush (Challenge 1: Blast Radius Zero), Vultr Serverless Inference.

---

## Prerequisites

- **Node.js**: v18.0.0 or later (tested on v24.21.0) and npm (v11.19.0).
- **Python**: 3.11 or later (tested on Python 3.14.7).
- **Git**: Installed and initialized.

---

## Project Structure

```
NeuroForge_AI/
├── AGENTS.md             # Project-specific development rules
├── README.md             # Project documentation
├── .gitignore            # Git exclusion rules
├── .env.example          # Environment variable template
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       └── services/
│           └── api.ts
├── infrastructure/
│   └── sandbox/
│       ├── Dockerfile
│       └── requirements.txt
└── backend/
    ├── requirements.txt
    ├── pytest.ini
    ├── app/
    │   ├── __init__.py
    │   ├── main.py
    │   └── core/
    │       ├── __init__.py
    │       └── config.py
    └── tests/
        └── test_health.py
```

---

## Environment Variables

Copy `.env.example` to `.env` in the root (or configure as environment variables):

```bash
cp .env.example .env
```

Key variables:
- `VITE_API_BASE_URL`: Base URL of the backend API (default: `http://localhost:8020`).
- `ENVIRONMENT`: Backend runtime environment (`development` / `production`).
- `HOST`: Backend host interface (`0.0.0.0`).
- `PORT`: Backend port (`8020`).
- `CORS_ORIGINS`: JSON list or comma-separated allowed origins (e.g., `["http://localhost:5173"]`).
- `VULTR_INFERENCE_API_KEY`: API key for Vultr Serverless Inference (future phase).
- `VULTR_INFERENCE_BASE_URL`: Endpoint for Vultr Serverless Inference.

---

## Getting Started

### 1. Backend Setup & Run

1. Navigate to the backend directory and create a virtual environment:
   ```bash
   cd backend
   python -m venv .venv
   ```

2. Activate the virtual environment:
   - **Windows (PowerShell)**:
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - **Linux / macOS**:
     ```bash
     source .venv/bin/activate
     ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Start the backend development server:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8020
   ```

5. Verify backend health endpoint:
   - URL: [http://localhost:8020/health](http://localhost:8020/health)
   - Interactive OpenAPI Docs: [http://localhost:8020/docs](http://localhost:8020/docs)

### 2. Frontend Setup & Run

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the Vite development server:
   ```bash
   npm run dev
   ```

4. Access the web interface at [http://localhost:5173](http://localhost:5173).

---

## Running Automated Tests

Run backend pytest suite from the `backend/` directory:

```bash
cd backend
.\.venv\Scripts\pytest -v
```

All health and system verification tests will run against the FastAPI application.

---

---

## Docker Sandbox Execution (Blast Radius Zero)

The isolated Docker sandbox executes statistical and machine-learning code in zero-blast-radius isolation:

### 1. Build Sandbox Image
```bash
docker build -t neuroforge-sandbox:local -f infrastructure/sandbox/Dockerfile infrastructure/sandbox
```

### 2. Run Smoke Test with Restrictive Isolation Settings
```bash
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 512m \
  --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --user 10001:10001 \
  neuroforge-sandbox:local \
  python3 -c "import numpy as np, pandas as pd, scipy, sklearn; print('Sandbox operational. User:', 10001)"
```

### 3. Isolation & Security Limitations Notice
> [!WARNING]
> While Docker sandbox isolation drops Linux capabilities, restricts process limits, denies network egress, and enforces a read-only root filesystem, standard Docker containers share the host Linux kernel. For untrusted, production multi-tenant code execution, stronger isolation technologies (such as gVisor `runsc`, Kata Containers, or dedicated ephemeral VMs) should be evaluated prior to general deployment.

---

## Documentation Links

- [System Architecture](file:///docs/ARCHITECTURE.md)
- [Deployment & Setup Guide](file:///docs/DEPLOYMENT.md)
- [Operations & Disaster Recovery](file:///docs/OPERATIONS.md)
- [Milestone 6 Final Report](file:///artifacts/reports/MILESTONE_6_FINAL_REPORT.md)

---

## Current Implemented Capabilities

- **Autonomous Scientific Agent**: LangGraph-powered 5-stage research state machine with automated hypothesis formulation, experiment planning, human approval gateway, and evaluation summary.
- **LLM Reasoning**: Direct integration with Vultr Serverless Inference (`deepseek-v4.1-flash-1017`) using strict Pydantic schemas.
- **Zero-Blast-Radius Docker Sandbox**: Isolated container execution with dropped capabilities (`--cap-drop ALL`), disabled networking (`--network none`), read-only root FS, and non-root user (`UID 10001`).
- **PostgreSQL 16 Persistence**: Dedicated container on host port `5440` storing research sessions, audit event trails, datasets, and experiment metadata.
- **Cross-Experiment Comparison & Concordance**: Side-by-side run comparison calculating directional concordance rates, shared candidate biomarkers, and run-specific unique features.
- **Evidence Lineage & Biological Traceability**: Interactive drawer displaying p-values, FDR adjusted q-values, Hedges' g effect sizes, and scientific limitation caveats.
- **Synthetic vs Empirical Dataset Governance**: Automatic detection and labeling of synthetic benchmark cohorts vs empirical clinical observational studies.
- **Automated Test Coverage**: Comprehensive pytest suite covering auth, sandbox isolation, statistical pipelines, and cross-experiment comparison.
- **Polished Web Experience**: React 18 / TypeScript SPA with real-time agent console, interactive matrix preview, volcano plots, and CSV export.
