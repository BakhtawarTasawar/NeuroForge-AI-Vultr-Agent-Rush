# AGENTS.md — Development Guidelines for NeuroForge AI

These guidelines govern all future agent and engineer interactions with the NeuroForge AI repository.

## 1. Project Identity & Architecture
- **Purpose**: Autonomous scientific experimentation platform exploring high-dimensional datasets (initial focus: cancer gene-expression transcriptomics), formulating testable hypotheses, planning ML/statistical experiments, and evaluating outcomes.
- **Scope Limit**: Scientific research tool only. Never treat or market as a clinical diagnosis or treatment recommendation system.
- **Hackathon Context**: Vultr Agent Rush (Challenge 1: Blast Radius Zero).
- **Control Plane**: FastAPI (Python) backend + React (TypeScript / Vite / Tailwind) frontend.
- **Inference Requirement**: Must use Vultr Serverless Inference for LLM agent calls. Do not use OpenAI, Gemini, or other non-Vultr providers as replacements.
- **Execution Security**: Scientific code must execute inside zero-blast-radius isolated sandbox containers with resource boundaries, timeouts, and explicit audit trails.

## 2. Code Quality & Modularity Rules
- **No Premature Abstraction**: Do not create unused directories, empty placeholder files, or overly generic wrappers.
- **No Mock / Fake Data**: Do not hardcode simulated scientific discoveries or fake agent outputs. If a service or dataset is not yet connected, report its true status.
- **Documentation**: Write concise, accurate documentation. Never document unbuilt features as functioning. Avoid redundant comments that merely restate code.
- **Testing**: Every backend feature must have automated pytest test coverage. Always execute tests and verify passing exit codes before completing work.
- **Environment & Secrets**: Never commit `.env` files, actual API keys, or credentials. Use `.env.example` as the canonical reference for environment variables.

## 3. Technology Conventions
- **Backend**:
  - Python 3.11+ (tested on Python 3.14).
  - FastAPI with Pydantic v2 Settings for configuration.
  - Virtual environment inside `backend/.venv`.
  - Always run tests via `backend/.venv/Scripts/pytest`.
- **Frontend**:
  - React 18+ with TypeScript and Vite.
  - Tailwind CSS for styling.
  - Axios for HTTP communication with backend control plane.
  - Backend API URL configured via `VITE_API_BASE_URL`.
- **Git**:
  - Keep commits clean, purposeful, and verified.
  - Exclude virtual environments, `node_modules`, build outputs, test caches, and dataset files.
