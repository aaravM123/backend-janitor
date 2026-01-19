"""
Large Codebase Analyzer - ContextShard Integration

Automatically uses ContextShard's FSDP-style distributed analysis
when a codebase exceeds single LLM context window limits.

Usage:
    from tools.large_codebase_analyzer import analyze_codebase

    result = await analyze_codebase("./my-project", task="security_scan")
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

# Load environment from .env.local
def load_env():
    env_file = Path(__file__).parent.parent / ".env.local"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env()


# Token threshold - if codebase exceeds this, use ContextShard
SINGLE_LLM_THRESHOLD = 100_000  # tokens


def estimate_tokens(project_path: str) -> int:
    """
    Rough estimate of tokens in a codebase.
    ~4 characters per token on average.
    """
    total_chars = 0
    extensions = {'.py', '.js', '.ts', '.go', '.java', '.rs', '.rb', '.php'}

    project = Path(project_path)
    for ext in extensions:
        for file in project.rglob(f"*{ext}"):
            # Skip common non-source directories
            if any(part in file.parts for part in ['node_modules', 'venv', '.git', '__pycache__', 'dist', 'build']):
                continue
            try:
                total_chars += file.stat().st_size
            except (OSError, IOError):
                continue

    return total_chars // 4  # rough token estimate


async def analyze_codebase(
    project_path: str,
    task: str = "security_vulnerability_scan",
    model: str = "deepseek-chat",
    force_distributed: bool = False,
    num_instances: Optional[int] = None,
    sync_rounds: int = 3,
) -> dict:
    """
    Analyze a codebase - automatically uses ContextShard for large codebases.

    Args:
        project_path: Path to the codebase to analyze
        task: Analysis task (security_vulnerability_scan, tech_debt_scan, etc.)
        model: LLM model to use (deepseek-chat, gpt-4o, etc.)
        force_distributed: Force use of ContextShard even for small codebases
        num_instances: Number of LLM instances (auto-calculated if None)
        sync_rounds: Number of synchronization rounds

    Returns:
        Analysis results with findings, recommendations, and cross-shard issues
    """
    project_path = str(Path(project_path).resolve())
    token_count = estimate_tokens(project_path)

    print(f"Analyzing codebase: {project_path}")
    print(f"Estimated tokens: {token_count:,}")

    if token_count < SINGLE_LLM_THRESHOLD and not force_distributed:
        # Small codebase - use simple single-shot analysis
        print(f"Using single-LLM analysis (under {SINGLE_LLM_THRESHOLD:,} token threshold)")
        return await _single_llm_analysis(project_path, task, model)
    else:
        # Large codebase - use ContextShard distributed analysis
        print(f"Using ContextShard distributed analysis (over threshold or forced)")
        return await _distributed_analysis(
            project_path, task, model, num_instances, sync_rounds
        )


async def _single_llm_analysis(project_path: str, task: str, model: str) -> dict:
    """Simple single-LLM analysis for small codebases."""
    try:
        from contextshard.llm import get_provider, Message
    except ImportError:
        return {
            "success": False,
            "error": "contextshard not installed. Run: pip install -e ./contextshard"
        }

    provider = get_provider(model)

    # Gather code files
    code_content = []
    project = Path(project_path)
    extensions = {'.py', '.js', '.ts', '.go'}

    for ext in extensions:
        for file in project.rglob(f"*{ext}"):
            if any(part in file.parts for part in ['node_modules', 'venv', '.git', '__pycache__']):
                continue
            try:
                content = file.read_text(encoding='utf-8', errors='ignore')
                code_content.append(f"=== {file.relative_to(project)} ===\n{content}")
            except:
                continue

    full_code = "\n\n".join(code_content[:50])  # Limit files

    prompt = _build_analysis_prompt(task, full_code)
    messages = [Message(role="user", content=prompt)]

    response = await provider.chat(messages)

    return {
        "success": True,
        "mode": "single_llm",
        "model": model,
        "analysis": response.content,
        "tokens_used": response.total_tokens,
    }


async def _distributed_analysis(
    project_path: str,
    task: str,
    model: str,
    num_instances: Optional[int],
    sync_rounds: int,
) -> dict:
    """Use ContextShard for distributed large codebase analysis."""
    try:
        from contextshard import FSDPCoordinator
    except ImportError:
        return {
            "success": False,
            "error": "contextshard not installed. Run: pip install -e ./contextshard"
        }

    # Auto-calculate instances based on codebase size
    if num_instances is None:
        token_count = estimate_tokens(project_path)
        num_instances = max(2, min(8, token_count // 80_000))

    print(f"Spawning {num_instances} LLM instances with {sync_rounds} sync rounds")

    coordinator = FSDPCoordinator(
        num_instances=num_instances,
        model=model,
        sync_rounds=sync_rounds,
        max_tokens_per_shard=80_000,
    )

    result = await coordinator.analyze(
        codebase_path=project_path,
        task=task,
    )

    return {
        "success": True,
        "mode": "distributed_fsdp",
        "model": model,
        "num_instances": num_instances,
        "sync_rounds": sync_rounds,
        "summary": result.summary() if hasattr(result, 'summary') else str(result),
        "findings": [f.__dict__ for f in result.findings] if hasattr(result, 'findings') else [],
        "cross_shard_issues": [i.__dict__ for i in result.cross_shard_issues] if hasattr(result, 'cross_shard_issues') else [],
        "duration_ms": result.total_duration_ms if hasattr(result, 'total_duration_ms') else 0,
    }


def _build_analysis_prompt(task: str, code: str) -> str:
    """Build the analysis prompt based on task type."""

    task_prompts = {
        "security_vulnerability_scan": """
You are a security expert analyzing this codebase for vulnerabilities.

Find and report:
1. SQL Injection vulnerabilities
2. XSS (Cross-Site Scripting) issues
3. Hardcoded secrets/credentials
4. Path traversal vulnerabilities
5. Command injection risks
6. Insecure deserialization
7. OWASP Top 10 issues

For each issue found, provide:
- File and line number
- Severity (critical/high/medium/low)
- Description of the vulnerability
- Suggested fix with code

CODE TO ANALYZE:
""",
        "tech_debt_scan": """
You are a code quality expert analyzing this codebase for tech debt.

Find and report:
1. Unused imports and dead code
2. Code duplication
3. High cyclomatic complexity
4. Missing error handling
5. Poor naming conventions
6. Missing type hints (Python)
7. Long functions that should be split

For each issue found, provide:
- File and line number
- Category
- Description
- Suggested refactoring

CODE TO ANALYZE:
""",
        "full_scan": """
You are analyzing this codebase for both security vulnerabilities AND tech debt.

SECURITY (High Priority):
- SQL Injection, XSS, hardcoded secrets
- Command injection, path traversal
- OWASP Top 10 issues

TECH DEBT (Medium Priority):
- Dead code, duplication
- High complexity, missing error handling
- Poor naming, missing types

For each issue, provide file, line, severity, description, and fix.

CODE TO ANALYZE:
""",
    }

    prompt_header = task_prompts.get(task, task_prompts["full_scan"])
    return prompt_header + code


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python large_codebase_analyzer.py <project_path> [task]")
        print("\nTasks: security_vulnerability_scan, tech_debt_scan, full_scan")
        sys.exit(1)

    project = sys.argv[1]
    task = sys.argv[2] if len(sys.argv) > 2 else "security_vulnerability_scan"

    result = asyncio.run(analyze_codebase(project, task))

    if result["success"]:
        print("\n" + "=" * 60)
        print(f"Analysis complete ({result['mode']})")
        print("=" * 60)
        if "analysis" in result:
            print(result["analysis"])
        elif "summary" in result:
            print(result["summary"])
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")
