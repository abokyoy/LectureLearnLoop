import py_compile
import sys

files = [
    "routes_knowledge.py", "routes_bridge.py", "routes_memory.py",
    "knowledge_management.py", "app.py", "services/fsrs_service.py",
    "database/schema_postgres.py", "tools/apply_fsrs_schema.py",
]
bad = 0
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print("OK  ", f)
    except Exception as e:
        bad += 1
        print("FAIL", f, repr(e))
print("COMPILE_RESULT:", "ALL_OK" if bad == 0 else f"{bad}_FAILED")
sys.exit(0 if bad == 0 else 1)
