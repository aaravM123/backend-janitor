"""
Direct comparison: ContextShard vs Normal (Single LLM) analysis.
"""

import asyncio
import os
import time
from pathlib import Path
from dataclasses import dataclass

# Load .env.local
env_file = Path(__file__).parent.parent / ".env.local"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")

from openai import AsyncOpenAI
from contextshard import FSDPCoordinator


@dataclass
class ComparisonResult:
    method: str
    duration_sec: float
    findings_count: int
    critical_count: int
    high_count: int
    medium_count: int
    cross_shard_count: int
    findings_list: list


def create_sample_codebase(base_path: Path):
    """Create a sample codebase with intentional vulnerabilities."""
    (base_path / "api").mkdir(parents=True, exist_ok=True)
    (base_path / "db").mkdir(exist_ok=True)
    (base_path / "services").mkdir(exist_ok=True)

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

    (base_path / "db" / "queries.py").write_text('''
"""Database queries - uses input from api/routes.py."""
from api.routes import get_user

def execute_query(query):
    # Executes raw SQL without sanitization
    return db.raw_execute(query)

def get_user_data(user_id):
    # Cross-file dependency - uses get_user which has SQL injection
    user = get_user(user_id)
    return process_user(user)
''')

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

    return base_path


async def run_normal_analysis(codebase_path: str) -> ComparisonResult:
    """Run analysis with a single LLM call (normal method)."""
    print("\n" + "=" * 60)
    print("NORMAL METHOD (Single LLM Call)")
    print("=" * 60)

    client = AsyncOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )

    # Read all code into one prompt
    all_code = ""
    for py_file in Path(codebase_path).rglob("*.py"):
        try:
            content = py_file.read_text()
            rel_path = py_file.relative_to(codebase_path)
            all_code += f"\n=== {rel_path} ===\n{content}\n"
        except Exception:
            pass

    prompt = f"""Analyze this codebase for security vulnerabilities.

For each vulnerability found, report in this exact format:
FINDING: [SEVERITY] category in file:line - description

Where SEVERITY is one of: CRITICAL, HIGH, MEDIUM, LOW

Here is the code:
{all_code}

Find ALL security issues including:
- SQL injection
- Command injection
- Hardcoded secrets
- Weak cryptography
- Cross-file data flow issues
- Missing input validation
"""

    start_time = time.time()

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a security expert. Analyze code for vulnerabilities."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=4000,
    )

    duration = time.time() - start_time
    content = response.choices[0].message.content

    # Parse findings
    findings = []
    critical = high = medium = 0

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("FINDING:") or "FINDING:" in line:
            findings.append(line)
            if "[CRITICAL]" in line.upper():
                critical += 1
            elif "[HIGH]" in line.upper():
                high += 1
            elif "[MEDIUM]" in line.upper():
                medium += 1

    print(f"\nResponse:\n{content[:2000]}...")

    return ComparisonResult(
        method="Normal (Single LLM)",
        duration_sec=duration,
        findings_count=len(findings),
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        cross_shard_count=0,  # Single LLM can't detect cross-shard
        findings_list=findings,
    )


async def run_contextshard_analysis(codebase_path: str) -> ComparisonResult:
    """Run analysis with ContextShard (distributed method)."""
    print("\n" + "=" * 60)
    print("CONTEXTSHARD METHOD (Distributed LLM)")
    print("=" * 60)

    coordinator = FSDPCoordinator(
        num_instances=2,
        model="deepseek-chat",
        sync_rounds=2,
        max_tokens_per_shard=50000,
    )

    start_time = time.time()
    result = await coordinator.analyze(
        codebase_path=codebase_path,
        task="security_vulnerability_scan",
    )
    duration = time.time() - start_time

    # Count by severity
    critical = sum(1 for f in result.findings if f.severity == "critical")
    high = sum(1 for f in result.findings if f.severity == "high")
    medium = sum(1 for f in result.findings if f.severity == "medium")

    findings_list = [
        f"[{f.severity.upper()}] {f.category} in {f.file}:{f.line} - {f.message}"
        for f in result.findings
    ]

    return ComparisonResult(
        method="ContextShard (Distributed)",
        duration_sec=duration,
        findings_count=len(result.findings),
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        cross_shard_count=len(result.cross_shard_issues),
        findings_list=findings_list,
    )


async def main():
    """Run comparison benchmark."""
    import tempfile

    print("=" * 60)
    print("CONTEXTSHARD vs NORMAL LLM - DIRECT COMPARISON")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        codebase_path = create_sample_codebase(Path(tmp_dir))
        print(f"\nTest codebase: {codebase_path}")
        print(f"Files: 4 Python files with intentional vulnerabilities")

        # Run both methods
        normal_result = await run_normal_analysis(str(codebase_path))
        cs_result = await run_contextshard_analysis(str(codebase_path))

        # Print comparison
        print("\n" + "=" * 60)
        print("COMPARISON RESULTS")
        print("=" * 60)

        print(f"\n{'Metric':<30} {'Normal':<20} {'ContextShard':<20}")
        print("-" * 70)
        print(f"{'Duration (seconds)':<30} {normal_result.duration_sec:<20.2f} {cs_result.duration_sec:<20.2f}")
        print(f"{'Total Findings':<30} {normal_result.findings_count:<20} {cs_result.findings_count:<20}")
        print(f"{'Critical Issues':<30} {normal_result.critical_count:<20} {cs_result.critical_count:<20}")
        print(f"{'High Issues':<30} {normal_result.high_count:<20} {cs_result.high_count:<20}")
        print(f"{'Medium Issues':<30} {normal_result.medium_count:<20} {cs_result.medium_count:<20}")
        print(f"{'Cross-File Issues Detected':<30} {'N/A':<20} {cs_result.cross_shard_count:<20}")

        print("\n" + "-" * 70)
        print("ANALYSIS:")
        print("-" * 70)

        # Speed comparison
        if cs_result.duration_sec < normal_result.duration_sec:
            speedup = normal_result.duration_sec / cs_result.duration_sec
            print(f"Speed: ContextShard was {speedup:.1f}x FASTER")
        else:
            slowdown = cs_result.duration_sec / normal_result.duration_sec
            print(f"Speed: ContextShard was {slowdown:.1f}x SLOWER (expected for small codebases due to sync overhead)")

        # Finding comparison
        if cs_result.findings_count > normal_result.findings_count:
            print(f"Coverage: ContextShard found {cs_result.findings_count - normal_result.findings_count} MORE issues")
        elif cs_result.findings_count < normal_result.findings_count:
            print(f"Coverage: Normal found {normal_result.findings_count - cs_result.findings_count} more issues")
        else:
            print("Coverage: Both found same number of issues")

        # Critical findings
        if cs_result.critical_count > normal_result.critical_count:
            print(f"Critical Issues: ContextShard found {cs_result.critical_count - normal_result.critical_count} MORE critical issues")

        print("\n" + "-" * 70)
        print("DETAILED FINDINGS COMPARISON:")
        print("-" * 70)

        print("\nNormal Method Findings:")
        for f in normal_result.findings_list[:10]:
            print(f"  - {f[:80]}")

        print("\nContextShard Findings:")
        for f in cs_result.findings_list[:10]:
            print(f"  - {f[:80]}")

        print("\n" + "=" * 60)
        print("CONCLUSION:")
        print("=" * 60)
        print("""
For SMALL codebases (like this 4-file test):
- Normal method may be faster (no sync overhead)
- Both should find similar issues

For LARGE codebases (100+ files, >100k tokens):
- ContextShard can analyze codebases that exceed context limits
- ContextShard finds cross-file attack paths via sync rounds
- ContextShard runs analysis in parallel (faster)

The real advantage of ContextShard is for codebases that DON'T FIT
in a single LLM context window (>128k tokens for DeepSeek).
""")


if __name__ == "__main__":
    asyncio.run(main())
