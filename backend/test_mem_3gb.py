import sys
import os
sys.path.insert(0, os.path.abspath('backend'))
from app.services.sandbox import SandboxExecutionService
from app.db.models import ExperimentStatus

res3 = SandboxExecutionService.execute(
    'test_mem_exceeded',
    'chunks = [bytearray(200 * 1024 * 1024) for _ in range(15)]\nprint("SUCCESS")',
    timeout_seconds=20
)
print("TEST 3 STATUS:", res3.status)
print("TEST 3 EXIT CODE:", res3.exit_code)
print("TEST 3 REASON:", res3.failure_reason)

