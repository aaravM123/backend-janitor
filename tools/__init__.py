"""
Backend Janitor - Security and Tech Debt Scanner Tools

This package contains Python tools for scanning and fixing code issues.
"""

__version__ = "0.1.0"

from .semgrep_scanner import scan, categorize_findings, print_summary as print_scan_summary
from .prioritizer import prioritize, PrioritizedIssue, FileGroup, print_summary as print_priority_summary
from .large_codebase_analyzer import analyze_codebase, estimate_tokens
from .ruff_analyzer import analyze as analyze_code_quality, AnalysisResult, auto_fix as ruff_fix
from .complexity_analyzer import analyze_complexity, ComplexityResult, FunctionComplexity
from .pr_creator import create_pr, create_branch, commit_changes, PRResult, format_pr_body

__all__ = [
    # Semgrep scanning (security)
    "scan",
    "categorize_findings",
    "print_scan_summary",
    # Prioritization
    "prioritize",
    "PrioritizedIssue",
    "FileGroup",
    "print_priority_summary",
    # Large codebase analysis (ContextShard)
    "analyze_codebase",
    "estimate_tokens",
    # Ruff analyzer (code quality)
    "analyze_code_quality",
    "AnalysisResult",
    "ruff_fix",
    # Complexity analyzer
    "analyze_complexity",
    "ComplexityResult",
    "FunctionComplexity",
    # PR creation
    "create_pr",
    "create_branch",
    "commit_changes",
    "PRResult",
    "format_pr_body",
]
