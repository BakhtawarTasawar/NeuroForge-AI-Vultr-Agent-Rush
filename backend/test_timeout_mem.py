import sys
import os
sys.path.insert(0, os.path.abspath('backend'))
from app.services.sandbox import SandboxExecutionService
from app.db.models import ExperimentStatus

# Test 2: Infinite loop timeout
res2 = SandboxExecutionService.execute(
    'test_timeout_containment',
    'import time\nprint("START")\nwhile True:\n    time.sleep(0.1)',
    timeout_seconds=3
)
print("TEST 2 STATUS:", res2.status)
print("TEST 2 DURATION:", round(res2.duration_seconds, 2))
print("TEST 2 REASON:", res2.failure_reason)

# Test 3: Excessive memory limit (allocate > 1024m)
res3 = SandboxExecutionService.execute(
    'test_memory_containment',
    'import sys\nprint("ALLOCATING")\nchunks = [bytearray(100 * 1024 * 1024) for _ in range(15)]\nprint("DONE")',
    timeout_seconds=15
)
print("TEST 3 STATUS:", res3.status)
print("TEST 3 EXIT CODE:", res3.exit_code)
print("TEST 3 STDERR:", res3.stderr)
print("TEST 3 REASON:", res3.failure_reason)

