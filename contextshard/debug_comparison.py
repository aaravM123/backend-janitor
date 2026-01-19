"""
Debug comparison to see raw LLM responses from ContextShard.
"""

import asyncio
import os
import time
from pathlib import Path

# Load .env.local
env_file = Path(__file__).parent.parent / ".env.local"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")

from contextshard import FSDPCoordinator


def create_sample_codebase(base_path: Path):
    """Create a sample codebase with intentional vulnerabilities."""
    (base_path / "api").mkdir(parents=True, exist_ok=True)
    (base_path / "db").mkdir(exist_ok=True)

    (base_path / "api" / "routes.py").write_text('''
"""API routes with SQL injection."""

def get_user(user_id):
    # SQL INJECTION
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return query

def search(name):
    # SQL INJECTION
    query = "SELECT * FROM items WHERE name = '" + name + "'"
    return query
''')

    (base_path / "api" / "auth.py").write_text('''
"""Auth with hardcoded secret."""

SECRET_KEY = "super_secret_12345"  # HARDCODED SECRET

def login(password):
    import hashlib
    return hashlib.md5(password.encode()).hexdigest()  # WEAK HASH
''')

    return base_path


async def main():
    import tempfile

    print("DEBUG: Running ContextShard with verbose output\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        codebase_path = create_sample_codebase(Path(tmp_dir))

        coordinator = FSDPCoordinator(
            num_instances=2,
            model="deepseek-chat",
            sync_rounds=2,
        )

        result = await coordinator.analyze(str(codebase_path))

        print("\n" + "=" * 60)
        print("RAW RESPONSES FROM EACH INSTANCE:")
        print("=" * 60)

        for instance in coordinator.instances:
            print(f"\n--- Instance {instance.id} ---")
            for msg in instance.conversation_history:
                if msg.role == "assistant":
                    print(f"\nAssistant response:\n{msg.content[:3000]}")
                    print("\n[Looking for FINDING/EXPORT/SECURITY lines...]")
                    for line in msg.content.split("\n"):
                        if any(kw in line for kw in ["FINDING:", "EXPORT:", "SECURITY:", "IMPORT:"]):
                            print(f"  MATCHED: {line[:100]}")

        print("\n" + "=" * 60)
        print(f"PARSED FINDINGS: {len(result.findings)}")
        for f in result.findings:
            print(f"  - [{f.severity}] {f.category} in {f.file}:{f.line}")


if __name__ == "__main__":
    asyncio.run(main())
