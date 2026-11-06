# NeuroForge AI — System Architecture

## 1. System Overview

NeuroForge AI is an autonomous scientific experimentation platform designed to assist researchers in exploring complex scientific datasets, formulating testable hypotheses, planning machine-learning and statistical experiments, executing them in zero-blast-radius isolated environments, and evaluating evidence-backed results.

The platform targets high-dimensional cancer gene-expression transcriptomic analysis (e.g. TCGA cohorts) while maintaining a strict, non-negotiable scope boundary: **scientific hypothesis discovery and research acceleration only, never clinical diagnosis or treatment recommendation**.

```
+-----------------------------------------------------------------------------------+
|                              REACT 18 SPA (VITE / TS)                             |
|  - Real-time Autonomous Agent Steering Console                                    |
|  - Side-by-side Experiment Reproducibility Comparison                             |
|  - Evidence Lineage & Biological Traceability Drawer                              |
|  - Synthetic vs Empirical Dataset Governance & Quality Assessment                 |
+-----------------------------------------+-----------------------------------------+
                                          | REST / JSON (JWT Cookie + Bearer)
                                          v
+-----------------------------------------------------------------------------------+
|                              FASTAPI CONTROL PLANE                                |
|  - Strict RBAC: ADMIN / RESEARCHER / VIEWER                                       |
|  - Project-Scoped Multi-Tenant Isolation & Resource Ownership                     |
|  - Rate Limiting, Sanitization, CSRF Defense                                      |
+--------------------+--------------------+--------------------+--------------------+
                     |                    |                    |
                     v                    v                    v
      +----------------------+   +------------------+   +-----------------------+
      |  PostgreSQL 16 Engine|   | Vultr Serverless |   | Zero-Blast-Radius     |
      |  - Research Sessions |   | Inference        |   | Docker Sandbox        |
      |  - State Persistence |   | (deepseek-v4.1)  |   | - Non-root (UID 10001)|
      |  - Experiments & Data|   |                  |   | - Read-only root FS   |
      |  - Port 5440         |   | Strict Schema    |   | - Network NONE        |
      +----------------------+   +------------------+   +-----------------------+
```

---

## 2. Core Architectural Pillars

### 2.1 Control Plane (FastAPI)
- **Role**: API gateway, authentication authority, audit logger, and orchestration coordinator.
- **Security & Authorization**:
  - Multi-tenant data segregation: all datasets, experiments, and sessions are linked to an active `Project` and verified against `owner_id` or `ADMIN` role.
  - Multi-layer input sanitization preventing path traversal and script injection.
  - Constant-time secret validation and cryptographic access tokens.

### 2.2 LangGraph Autonomous Research Engine
- **State Machine Nodes**:
  1. `Formulate Hypotheses`: Inspects dataset statistical metrics and generates prioritized hypotheses.
  2. `Plan Experiments`: Formulates concrete statistical tests (Welch's t-test, Benjamini-Hochberg FDR correction, Hedges' g effect sizes).
  3. `Human-in-the-Loop Gateway`: Pauses state machine for investigator review and cryptographically verified approval (`sha256(plan)`).
  4. `Execute Experiments`: Dispatches code into the zero-blast-radius Docker sandbox.
  5. `Evaluate & Summarize`: Synthesizes differential expression signals, volcano coordinates, and biological caveats into actionable findings.
- **Persistence & Resiliency**:
  - High-resilience thread checkpointing backed by durable PostgreSQL `research_sessions` and `research_events` tables.
  - Handles process restarts gracefully, enabling research sessions to resume from their exact state.

### 2.3 Zero-Blast-Radius Sandbox (`neuroforge-sandbox:local`)
- Strict security controls:
  - `--network none`: Complete egress denial (no C2, exfiltration, or external network reach).
  - `--read-only`: Immutable filesystem; only `/tmp` (tmpfs 64MB) and `/workspace` (bind mount) are writable.
  - `--user 10001:10001`: Non-root execution.
  - `--cap-drop ALL`: All Linux capabilities dropped.
  - `--security-opt no-new-privileges`: Privilege escalation disabled.
  - `--memory 512m --cpus 1.0 --pids-limit 64`: Resource starvation defense.
  - 60-second process timeout with hard `SIGKILL` termination.

### 2.4 LLM Reasoning Engine (Vultr Serverless Inference)
- Dedicated integration with Vultr Serverless Inference using model `deepseek-v4.1-flash-1017`.
- Pydantic v2 structured output enforcement with automated retry and fallback parsing.
- Zero mock fallbacks: real provider connection with accurate telemetry reporting.

### 2.5 Experiment Comparison & Concordance Engine
- Side-by-side analysis of two statistical runs:
  - Dataset parity and SHA-256 integrity verification.
  - Directional concordance rate calculation (% of shared significant genes with matching fold-change sign).
  - Identification of common candidate biomarkers and run-specific unique features.

---

## 3. Data Model

- **`User`**: Account identity, hashed credentials, role (`ADMIN`, `RESEARCHER`, `VIEWER`), active status.
- **`Project`**: Scientific workspace boundary, multi-tenant container for datasets, experiments, and sessions.
- **`Dataset`**: Matrix metadata (orientation, features × samples, content SHA-256 hash, organism, tissue, condition, synthetic benchmark flag).
- **`Experiment`**: Executed statistical pipeline, execution metrics (duration, exit code), generated artifacts, reproducibility manifest.
- **`ResearchSession`**: Autonomous agent state machine run, current phase, approval state, canonical plan hash, token usage.
- **`ResearchEvent`**: Fine-grained audit trail of agent thought cycles, tool calls, and human approvals.

