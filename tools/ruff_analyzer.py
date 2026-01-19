"""
Ruff Analyzer - Code Quality Scanner

Runs Ruff to detect code quality issues like unused imports, dead code,
complexity issues, and style violations.

Usage:
    from tools.ruff_analyzer import analyze, print_summary

    results = analyze("./my-project")
    print_summary(results)
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class CodeIssue:
    """Represents a single code quality issue."""
    file: str
    line: int
    column: int
    code: str           # e.g., "F401", "E501"
    message: str
    category: str       # unused_imports, dead_code, complexity, style
    severity: str       # low, medium, high
    fix_available: bool = False
    suggested_fix: Optional[str] = None


@dataclass
class AnalysisResult:
    """Results from Ruff analysis."""
    unused_imports: list[CodeIssue] = field(default_factory=list)
    dead_code: list[CodeIssue] = field(default_factory=list)
    complexity: list[CodeIssue] = field(default_factory=list)
    style: list[CodeIssue] = field(default_factory=list)
    errors: list[CodeIssue] = field(default_factory=list)
    total_count: int = 0
    files_scanned: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "unused_imports": [vars(i) for i in self.unused_imports],
            "dead_code": [vars(i) for i in self.dead_code],
            "complexity": [vars(i) for i in self.complexity],
            "style": [vars(i) for i in self.style],
            "errors": [vars(i) for i in self.errors],
            "total_count": self.total_count,
            "files_scanned": self.files_scanned,
            "summary": {
                "unused_imports": len(self.unused_imports),
                "dead_code": len(self.dead_code),
                "complexity": len(self.complexity),
                "style": len(self.style),
                "errors": len(self.errors),
            }
        }


# Ruff rule code categories
RULE_CATEGORIES = {
    # Unused imports and variables
    "F401": ("unused_imports", "medium", "Unused import"),
    "F841": ("dead_code", "medium", "Unused variable"),
    "F811": ("dead_code", "high", "Redefinition of unused name"),

    # Dead code
    "F821": ("errors", "high", "Undefined name"),
    "F822": ("errors", "high", "Undefined name in __all__"),
    "F823": ("dead_code", "medium", "Local variable referenced before assignment"),

    # Complexity (from mccabe)
    "C901": ("complexity", "high", "Function too complex"),

    # Style - pycodestyle errors
    "E101": ("style", "low", "Indentation contains mixed spaces and tabs"),
    "E111": ("style", "low", "Indentation is not a multiple of four"),
    "E501": ("style", "low", "Line too long"),
    "E711": ("style", "medium", "Comparison to None"),
    "E712": ("style", "medium", "Comparison to True/False"),
    "E721": ("style", "medium", "Type comparison instead of isinstance()"),
    "E722": ("errors", "high", "Bare except"),
    "E731": ("style", "medium", "Lambda assignment"),
    "E741": ("style", "medium", "Ambiguous variable name"),

    # Style - pycodestyle warnings
    "W291": ("style", "low", "Trailing whitespace"),
    "W292": ("style", "low", "No newline at end of file"),
    "W293": ("style", "low", "Blank line contains whitespace"),
    "W505": ("style", "low", "Doc line too long"),

    # Pyflakes
    "F": ("errors", "medium", "Pyflakes error"),

    # isort
    "I001": ("style", "low", "Import block is not sorted"),
    "I002": ("style", "low", "Missing required import"),

    # pep8-naming
    "N801": ("style", "low", "Class name should use CapWords"),
    "N802": ("style", "low", "Function name should be lowercase"),
    "N803": ("style", "low", "Argument name should be lowercase"),
    "N806": ("style", "low", "Variable should be lowercase"),

    # pyupgrade
    "UP": ("style", "low", "Pyupgrade suggestion"),

    # flake8-bugbear
    "B": ("errors", "medium", "Bugbear issue"),
    "B006": ("errors", "high", "Mutable default argument"),
    "B007": ("dead_code", "medium", "Unused loop variable"),
    "B008": ("errors", "high", "Function call in default argument"),
    "B009": ("style", "low", "getattr with constant"),
    "B010": ("style", "low", "setattr with constant"),
    "B017": ("errors", "high", "assertRaises(Exception)"),
    "B023": ("errors", "high", "Function uses loop variable"),
    "B024": ("style", "medium", "Abstract class without abstract methods"),
    "B026": ("errors", "medium", "Star-arg unpacking after keyword"),

    # flake8-comprehensions
    "C4": ("style", "low", "Comprehension issue"),

    # flake8-simplify
    "SIM": ("style", "low", "Simplify suggestion"),

    # Ruff-specific
    "RUF": ("style", "low", "Ruff-specific rule"),
}


def _get_category_and_severity(code: str) -> tuple[str, str, str]:
    """
    Get category and severity for a Ruff rule code.

    Returns: (category, severity, description)
    """
    # Check exact match first
    if code in RULE_CATEGORIES:
        return RULE_CATEGORIES[code]

    # Check prefix match (e.g., "F" for all Pyflakes rules)
    for prefix in ["F", "E", "W", "I", "N", "UP", "B", "C4", "SIM", "RUF"]:
        if code.startswith(prefix) and prefix in RULE_CATEGORIES:
            return RULE_CATEGORIES[prefix]

    # Default
    return ("style", "low", "Code style issue")


def analyze(
    project_path: str,
    config_path: Optional[str] = None,
    select: Optional[list[str]] = None,
    ignore: Optional[list[str]] = None,
) -> AnalysisResult:
    """
    Analyze a project for code quality issues using Ruff.

    Args:
        project_path: Path to the project to analyze
        config_path: Optional path to ruff.toml config file
        select: Optional list of rule codes to enable (e.g., ["F", "E", "W"])
        ignore: Optional list of rule codes to ignore

    Returns:
        AnalysisResult with categorized issues
    """
    project_path = str(Path(project_path).resolve())

    # Build ruff command - use python -m ruff for cross-platform compatibility
    cmd = [
        sys.executable, "-m", "ruff", "check",
        project_path,
        "--output-format=json",
        "--no-fix",  # Don't auto-fix, just report
    ]

    if config_path:
        cmd.extend(["--config", config_path])

    if select:
        cmd.extend(["--select", ",".join(select)])
    else:
        # Default: enable common rules
        cmd.extend(["--select", "F,E,W,C901,I,N,B,UP,SIM"])

    if ignore:
        cmd.extend(["--ignore", ",".join(ignore)])

    # Run ruff
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Ruff not found. Install with: pip install ruff"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Ruff analysis timed out (>5 minutes)")

    # Parse JSON output
    issues = []
    if result.stdout.strip():
        try:
            issues = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Ruff might output non-JSON on certain errors
            pass

    # Categorize issues
    analysis = AnalysisResult()
    seen_files = set()

    for issue in issues:
        file_path = issue.get("filename", "unknown")
        seen_files.add(file_path)

        code = issue.get("code", "")
        category, severity, _ = _get_category_and_severity(code)

        code_issue = CodeIssue(
            file=file_path,
            line=issue.get("location", {}).get("row", 0),
            column=issue.get("location", {}).get("column", 0),
            code=code,
            message=issue.get("message", ""),
            category=category,
            severity=severity,
            fix_available=issue.get("fix") is not None,
            suggested_fix=issue.get("fix", {}).get("message") if issue.get("fix") else None,
        )

        # Add to appropriate category
        if category == "unused_imports":
            analysis.unused_imports.append(code_issue)
        elif category == "dead_code":
            analysis.dead_code.append(code_issue)
        elif category == "complexity":
            analysis.complexity.append(code_issue)
        elif category == "errors":
            analysis.errors.append(code_issue)
        else:
            analysis.style.append(code_issue)

    analysis.total_count = len(issues)
    analysis.files_scanned = len(seen_files)

    return analysis


def print_summary(result: AnalysisResult) -> None:
    """Print a human-readable summary of the analysis."""
    print("\n" + "=" * 60)
    print("RUFF CODE QUALITY ANALYSIS")
    print("=" * 60)

    print(f"\nFiles scanned: {result.files_scanned}")
    print(f"Total issues:  {result.total_count}")

    print("\n" + "-" * 40)
    print("SUMMARY BY CATEGORY")
    print("-" * 40)
    print(f"  Unused imports: {len(result.unused_imports)}")
    print(f"  Dead code:      {len(result.dead_code)}")
    print(f"  Complexity:     {len(result.complexity)}")
    print(f"  Style issues:   {len(result.style)}")
    print(f"  Errors:         {len(result.errors)}")

    # Print high-severity issues
    high_severity = [
        i for i in (result.errors + result.complexity + result.dead_code)
        if i.severity == "high"
    ]

    if high_severity:
        print("\n" + "-" * 40)
        print("HIGH SEVERITY ISSUES")
        print("-" * 40)
        for issue in high_severity[:10]:
            print(f"\n  [{issue.code}] {issue.file}:{issue.line}")
            print(f"  {issue.message}")
            if issue.suggested_fix:
                print(f"  Fix: {issue.suggested_fix}")

    # Print unused imports (common quick wins)
    if result.unused_imports:
        print("\n" + "-" * 40)
        print("UNUSED IMPORTS (Quick Wins)")
        print("-" * 40)
        for issue in result.unused_imports[:10]:
            print(f"  {issue.file}:{issue.line} - {issue.message}")

    print("\n" + "=" * 60)


def get_fixable_issues(result: AnalysisResult) -> list[CodeIssue]:
    """Get all issues that Ruff can auto-fix."""
    all_issues = (
        result.unused_imports +
        result.dead_code +
        result.complexity +
        result.style +
        result.errors
    )
    return [i for i in all_issues if i.fix_available]


def auto_fix(
    project_path: str,
    config_path: Optional[str] = None,
    unsafe: bool = False,
) -> dict:
    """
    Auto-fix issues using Ruff.

    Args:
        project_path: Path to the project
        config_path: Optional ruff.toml config
        unsafe: If True, apply unsafe fixes too

    Returns:
        Dict with fix results
    """
    cmd = [
        sys.executable, "-m", "ruff", "check",
        project_path,
        "--fix",
    ]

    if unsafe:
        cmd.append("--unsafe-fixes")

    if config_path:
        cmd.extend(["--config", config_path])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "fixed": "fixed" in result.stdout.lower() or result.returncode == 0,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Ruff Code Quality Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ruff_analyzer.py ./project                    # Analyze and print summary
  python ruff_analyzer.py ./project --fix              # Auto-fix issues
  python ruff_analyzer.py ./project -o report.json     # Save JSON report
  python ruff_analyzer.py ./project --json             # Print JSON to stdout
        """
    )
    parser.add_argument("project_path", help="Path to the project to analyze")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues")
    parser.add_argument("-o", "--output-file", help="Save JSON report to file")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")

    args = parser.parse_args()

    if args.fix:
        print(f"Auto-fixing issues in: {args.project_path}")
        result = auto_fix(args.project_path)
        print(result)
    else:
        print(f"Analyzing: {args.project_path}")
        result = analyze(args.project_path)
        print_summary(result)

        # Save to file if requested
        if args.output_file:
            with open(args.output_file, "w") as f:
                json.dump(result.to_dict(), f, indent=2)
            print(f"\nJSON report saved to: {args.output_file}")

        # Print JSON to stdout if requested
        if args.json:
            print("\nJSON OUTPUT:")
            print(json.dumps(result.to_dict(), indent=2))
