import sys
import os
sys.path.insert(0, os.path.abspath('backend'))
from app.services.sandbox import SandboxExecutionService

res1 = SandboxExecutionService.execute('test_debug_1', 'print("HELLO FROM CONTAINER")')
print('TEST 1 STATUS:', res1.status)
print('TEST 1 STDOUT:', res1.stdout)
print('TEST 1 STDERR:', res1.stderr)
print('TEST 1 REASON:', res1.failure_reason)

res6 = SandboxExecutionService.execute('test_debug_6', 'import os\nprint("ALL_KEYS:", sorted(list(os.environ.keys())))')
print('TEST 6 STDOUT:', res6.stdout)

