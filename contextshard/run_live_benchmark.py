"""
Live benchmark of ContextShard on a real codebase with actual LLM calls.
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
    # Create directories
    (base_path / "api").mkdir(parents=True, exist_ok=True)
    (base_path / "db").mkdir(exist_ok=True)
    (base_path / "services").mkdir(exist_ok=True)

    # API layer with SQL injection
    (base_path / "api" / "routes.py").write_text('''
"""API routes with SQL injection vulnerability."""
from db.queries import execute_query

def get_user(user_id):
    # SQL INJECTION - user_id not sanitized
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return execute_query(query)

def search_users(name):
    # Another SQL injection
    query = "SELECT * FROM items WHERE name LIKE \'%" + name + "%\'"
    return execute_query(query)
''')

    # Auth with hardcoded secret
    (base_path / "api" / "auth.py").write_text('''
"""Authentication with hardcoded secret."""
import hashlib

# HARDCODED SECRET
SECRET_KEY = "super_secret_key_12345"
API_TOKEN = "tok_live_abc123xyz"

def login(username, password):
    hashed = hashlib.md5(password.encode()).hexdigest()  # WEAK HASH
    return check_credentials(username, hashed)
''')

    # Database layer
    (base_path / "db" / "queries.py").write_text('''
"""Database queries - uses input from api/routes.py."""
from api.routes import get_user

def execute_query(query):
    # Executes raw SQL without sanitization
    return db.raw_execute(query)

def get_user_data(user_id):
    # Cross-shard dependency - uses get_user which has SQL injection
    user = get_user(user_id)
    return process_user(user)
''')

    # Services layer
    (base_path / "services" / "user_service.py").write_text('''
"""User service - depends on db layer."""
from db.queries import execute_query, get_user_data
import subprocess

class UserService:
    def get_profile(self, user_id):
        # Uses potentially tainted data
        query = f"SELECT * FROM profiles WHERE user_id = {user_id}"
        return execute_query(query)

    def run_report(self, report_name):
        # COMMAND INJECTION
        cmd = f"generate_report.sh {report_name}"
        return subprocess.call(cmd, shell=True)
''')

    print(f"Created sample codebase at {base_path}")
    return base_path


async def run_live_benchmark():
    """Run a live benchmark with actual LLM calls."""
    print("=" * 60)
    print("CONTEXTSHARD LIVE BENCHMARK")
    print("=" * 60)

    # Create temporary sample codebase
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        codebase_path = create_sample_codebase(Path(tmp_dir))

        print(f"\nAnalyzing codebase: {codebase_path}")
        print(f"Using model: deepseek-chat")
        print(f"Instances: 2 (small codebase)")
        print(f"Sync rounds: 2")
        print()

        # Create coordinator with fewer instances for small codebase
        coordinator = FSDPCoordinator(
            num_instances=2,
            model="deepseek-chat",
            sync_rounds=2,
            max_tokens_per_shard=50000,
        )

        # Run analysis
        start_time = time.time()
        try:
            result = await coordinator.analyze(
                codebase_path=str(codebase_path),
                task="security_vulnerability_scan",
            )
            duration = time.time() - start_time

            # Print results
            print("\n" + "=" * 60)
            print("RESULTS")
            print("=" * 60)
            print(result.summary())

            print("\n" + "-" * 60)
            print("DETAILED FINDINGS:")
            print("-" * 60)
            for i, finding in enumerate(result.findings, 1):
                print(f"\n{i}. [{finding.severity.upper()}] {finding.category}")
                print(f"   File: {finding.file}:{finding.line}")
                print(f"   Message: {finding.message}")
                if finding.cross_shard_context:
                    print(f"   Cross-shard: {finding.cross_shard_context}")

            if result.cross_shard_issues:
                print("\n" + "-" * 60)
                print("CROSS-SHARD ISSUES:")
                print("-" * 60)
                for issue in result.cross_shard_issues:
                    print(f"\n[{issue.severity.upper()}] {issue.title}")
                    print(f"   Shards: {issue.involved_shards}")
                    print(f"   {issue.description}")

            print("\n" + "-" * 60)
            print("BENCHMARK METRICS:")
            print("-" * 60)
            print(f"Total duration: {duration:.2f} seconds")
            print(f"Files analyzed: {result.total_files_analyzed}")
            print(f"Tokens processed: {result.total_tokens_processed}")
            print(f"Shards used: {result.num_shards}")
            print(f"Sync rounds: {result.num_rounds}")
            print(f"Total findings: {len(result.findings)}")
            print(f"Cross-shard issues: {len(result.cross_shard_issues)}")

            return result

        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
            return None


if __name__ == "__main__":
    asyncio.run(run_live_benchmark())
