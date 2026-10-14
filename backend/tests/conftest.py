import os
import sys
import tempfile
from pathlib import Path

# Isolate every test run from the real data dir / real .env BEFORE app modules import.
os.environ["AXIOM_DATA_DIR"] = tempfile.mkdtemp(prefix="axiom_tests_")
os.environ["AXIOM_TESTING"] = "1"
# Settings also reads the root .env file, so popping variables is not enough: an EMPTY environment variable
# overrides the file. Without this, any test reaching get_store() would write to the real Neon database.
for k in ("UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_ACCESS_TOKEN", "DATABASE_URL", "ANTHROPIC_API_KEY"):
    os.environ[k] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
