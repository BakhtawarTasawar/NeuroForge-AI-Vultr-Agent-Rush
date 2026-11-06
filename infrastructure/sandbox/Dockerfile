# NeuroForge AI — Blast Radius Zero Sandbox Image
# Target: Isolated execution of scientific statistical and machine learning experiment code

FROM python:3.11-slim

# Prevent byte code generation and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/sandboxuser

# Create non-root unprivileged execution user
RUN groupadd -g 10001 sandbox && \
    useradd -u 10001 -g sandbox -s /bin/bash -m -d /home/sandboxuser sandboxuser

WORKDIR /workspace

# Install scientific dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt && \
    chown -R sandboxuser:sandbox /workspace /home/sandboxuser

# Switch to non-root user
USER 10001:10001

CMD ["python3"]
