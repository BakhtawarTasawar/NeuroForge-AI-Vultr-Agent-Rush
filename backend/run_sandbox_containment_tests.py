import sys
import os
import uuid
import json

sys.path.insert(0, os.path.abspath('backend'))
from app.services.sandbox import SandboxExecutionService
from app.db.models import ExperimentStatus

results = {}

# Test 1: Normal scientific Python script
t1_id = f"test_containment_normal_{uuid.uuid4().hex[:8]}"
t1_code = """
import numpy as np
import pandas as pd
arr = np.array([10.5, 20.5, 30.0])
print(f"CALCULATED_MEAN: {arr.mean():.2f}")
"""
r1 = SandboxExecutionService.execute(t1_id, t1_code, timeout_seconds=10)
results["test1_normal"] = {
    "status": r1.status.value,
    "exit_code": r1.exit_code,
    "stdout": r1.stdout.strip(),
    "passed": (r1.status == ExperimentStatus.COMPLETED and "CALCULATED_MEAN: 20.33" in r1.stdout)
}

# Test 2: Infinite loop terminated by timeout
t2_id = f"test_containment_timeout_{uuid.uuid4().hex[:8]}"
t2_code = """
import time
print("LOOP_STARTED", flush=True)
while True:
    time.sleep(0.1)
"""
r2 = SandboxExecutionService.execute(t2_id, t2_code, timeout_seconds=3)
results["test2_timeout"] = {
    "status": r2.status.value,
    "exit_code": r2.exit_code,
    "duration": round(r2.duration_seconds, 2),
    "failure_reason": r2.failure_reason,
    "passed": (r2.status == ExperimentStatus.TIMED_OUT or "timed out" in (r2.failure_reason or "").lower())
}

# Test 3: Excessive memory allocation stopped by limits
t3_id = f"test_containment_memory_{uuid.uuid4().hex[:8]}"
t3_code = """
# Attempt to allocate 2 GB of memory in container with 1GB limit
chunks = []
for _ in range(30):
    chunks.append(bytearray(100 * 1024 * 1024))
print("MEMORY_SUCCESS")
"""
r3 = SandboxExecutionService.execute(t3_id, t3_code, timeout_seconds=15)
results["test3_memory"] = {
    "status": r3.status.value,
    "exit_code": r3.exit_code,
    "failure_reason": r3.failure_reason or r3.stderr,
    "passed": (r3.status == ExperimentStatus.FAILED or r3.exit_code == 137 or "MemoryError" in r3.stderr)
}

# Test 4: Attempted network access blocked
t4_id = f"test_containment_network_{uuid.uuid4().hex[:8]}"
t4_code = """
import urllib.request
try:
    urllib.request.urlopen('http://1.1.1.1', timeout=2)
    print("NETWORK_ACCESSIBLE")
except Exception as e:
    print(f"NETWORK_BLOCKED: {type(e).__name__}")
"""
r4 = SandboxExecutionService.execute(t4_id, t4_code, timeout_seconds=10)
results["test4_network"] = {
    "status": r4.status.value,
    "exit_code": r4.exit_code,
    "stdout": r4.stdout.strip(),
    "passed": ("NETWORK_BLOCKED" in r4.stdout or "Network is unreachable" in r4.stderr or "URLError" in r4.stdout)
}

# Test 5: Attempted access outside workspace blocked
t5_id = f"test_containment_filesystem_{uuid.uuid4().hex[:8]}"
t5_code = """
try:
    with open('/etc/shadow', 'r') as f:
        print("SHADOW_READ")
except Exception as e:
    print(f"FILESYSTEM_RESTRICTED: {type(e).__name__}")
"""
r5 = SandboxExecutionService.execute(t5_id, t5_code, timeout_seconds=10)
results["test5_filesystem"] = {
    "status": r5.status.value,
    "exit_code": r5.exit_code,
    "stdout": r5.stdout.strip(),
    "passed": ("FILESYSTEM_RESTRICTED" in r5.stdout or "PermissionError" in r5.stdout)
}

# Test 6: Attempted access to sensitive environment variables blocked
t6_id = f"test_containment_secrets_{uuid.uuid4().hex[:8]}"
t6_code = """
import os
sensitive = [k for k in os.environ if any(w in k.upper() for w in ['SECRET', 'KEY', 'PASS', 'TOKEN', 'VULTR', 'JWT'])]
print(f"EXPOSED_SECRETS_COUNT: {len(sensitive)}")
"""
r6 = SandboxExecutionService.execute(t6_id, t6_code, timeout_seconds=10)
results["test6_secrets"] = {
    "status": r6.status.value,
    "exit_code": r6.exit_code,
    "stdout": r6.stdout.strip(),
    "passed": ("EXPOSED_SECRETS_COUNT: 0" in r6.stdout)
}

print("=== SANDBOX_CONTAINMENT_RESULTS ===")
print(json.dumps(results, indent=2))

