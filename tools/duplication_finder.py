"""
Duplication Finder - Code Duplication Scanner

Runs `jscpd` to detect copy-pasted or duplicated code blocks across the codebase.

Usage:
    from tools.duplication_finder import analyze_duplication, print_summary

    results = analyze_duplication("./my-project")
    print_summary(results)
"""

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DuplicateFragment:
    """Represents one instance of a duplicated code block."""
    file: str
    start_line: int
    end_line: int
    code: str

    def to_dict(self) -> dict:
        return vars(self)


@dataclass
class DuplicateBlock:
    """Represents a set of duplicated code fragments."""
    total_tokens: int
    lines: int
    fragment: str # The actual duplicated code content
    fragments: list[DuplicateFragment] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        """Counts the number of unique files involved in the duplication."""
        return len(set(f.file for f in self.fragments))

    def to_dict(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "lines": self.lines,
            "file_count": self.file_count,
            "fragment": self.fragment,
            "fragments": [f.to_dict() for f in self.fragments],
        }


@dataclass
class DuplicationResult:
    """Results from jscpd analysis."""
    duplicates: list[DuplicateBlock] = field(default_factory=list)
    total_duplicated_lines: int = 0
    total_lines: int = 0
    duplication_percentage: float = 0.0

    def to_dict(self) -> dict:
        return {
            "duplicates": [d.to_dict() for d in self.duplicates],
            "summary": {
                "total_duplicated_lines": self.total_duplicated_lines,
                "total_lines": self.total_lines,
                "duplication_percentage": round(self.duplication_percentage, 2),
                "total_duplicate_blocks": len(self.duplicates),
            }
        }


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _extract_fragment_location(fragment: dict) -> tuple[str, int, int]:
    file_path = (
        fragment.get("source")
        or fragment.get("name")
        or fragment.get("file")
        or fragment.get("path")
        or ""
    )

    start = fragment.get("start") or fragment.get("startLine") or fragment.get("start_line")
    end = fragment.get("end") or fragment.get("endLine") or fragment.get("end_line")

    if isinstance(start, dict):
        start = start.get("line")
    if isinstance(end, dict):
        end = end.get("line")

    return str(file_path), _coerce_int(start), _coerce_int(end)


def analyze_duplication(
    project_path: str,
    min_lines: int = 5,
    min_tokens: int = 50,
    ignore: Optional[list[str]] = None,
) -> DuplicationResult:
    """
    Analyze a project for code duplication using jscpd.

    Args:
        project_path: Path to the project to analyze.
        min_lines: Minimum number of lines to consider a duplicate.
        min_tokens: Minimum number of tokens to consider a duplicate.
        ignore: List of glob patterns to ignore.

    Returns:
        DuplicationResult with all detected duplicate blocks.
    """
    project_path = str(Path(project_path).resolve())
    
    default_ignore = [
        "**/node_modules/**",
        "**/__pycache__/**",
        "**/.venv/**",
        "**/.git/**",
        "**/build/**",
        "**/dist/**",
    ]
    if ignore:
        ignore_patterns = default_ignore + ignore
    else:
        ignore_patterns = default_ignore

    npx_command = "npx.cmd" if os.name == "nt" else "npx"

    with tempfile.TemporaryDirectory() as temp_dir:
        cmd = [
            npx_command, "jscpd",
            project_path,
            f"--reporters=json",
            f"--output={temp_dir}",
            "--min-lines", str(min_lines),
            "--min-tokens", str(min_tokens),
            "--ignore", ",".join(ignore_patterns),
            "--silent"
        ]

        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600, # 10 minutes
                shell=False
            )
        except FileNotFoundError:
            raise RuntimeError(
                "jscpd not found. Please ensure Node.js and npx are installed and in your PATH."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("jscpd analysis timed out (>10 minutes)")

        report_path = Path(temp_dir) / "jscpd-report.json"
        if not report_path.exists():
            candidates = sorted(Path(temp_dir).glob("*.json"))
            if candidates:
                report_path = candidates[0]
            elif process.returncode == 0:
                return DuplicationResult()
            else:
                raise RuntimeError(
                    "jscpd failed and did not produce a JSON report. "
                    f"stdout: {process.stdout.strip()[:500]} "
                    f"stderr: {process.stderr.strip()[:500]}"
                )

        with open(report_path, 'r') as f:
            try:
                report = json.load(f)
            except json.JSONDecodeError:
                raise RuntimeError(f"Failed to parse jscpd JSON report from {report_path}")

        result = DuplicationResult(
            total_duplicated_lines=report.get("statistics", {}).get("total", {}).get("duplicatedLines", 0),
            total_lines=report.get("statistics", {}).get("total", {}).get("lines", 0),
            duplication_percentage=report.get("statistics", {}).get("total", {}).get("percentage", 0),
        )

        for dup in report.get("duplicates", []):
            block = DuplicateBlock(
                total_tokens=dup.get("tokens", 0),
                lines=dup.get("lines", 0),
                fragment=dup.get("fragment", "")
            )
            
            # jscpd's "blame" array contains all fragments for a given duplicate block
            fragments_data = dup.get("blame", [])
            # Fallback for older jscpd versions
            if not fragments_data:
                if "firstFile" in dup: fragments_data.append(dup["firstFile"])
                if "secondFile" in dup: fragments_data.append(dup["secondFile"])

            for frag_data in fragments_data:
                if not frag_data:
                    continue

                file_path, start_line, end_line = _extract_fragment_location(frag_data)
                if not file_path:
                    continue

                fragment = DuplicateFragment(
                    file=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    code=dup.get("fragment", ""),
                )
                block.fragments.append(fragment)
            
            if block.fragments:
                result.duplicates.append(block)
        
        return result


def print_summary(result: DuplicationResult) -> None:
    """Print a human-readable summary of the duplication analysis."""
    summary = result.to_dict()["summary"]
    
    print("\n" + "=" * 60)
    print("CODE DUPLICATION ANALYSIS (jscpd)")
    print("=" * 60)

    if not result.duplicates:
        print("\nNo significant code duplication found. Well done!")
        print("=" * 60)
        return

    print(f"\nTotal lines scanned: {summary['total_lines']}")
    print(f"Total duplicated lines: {summary['total_duplicated_lines']}")
    print(f"Duplication percentage: {summary['duplication_percentage']:.2f}%")
    print(f"Total duplicate blocks found: {summary['total_duplicate_blocks']}")
    
    sorted_duplicates = sorted(result.duplicates, key=lambda d: d.lines, reverse=True)

    print("\n" + "-" * 40)
    print("TOP 5 DUPLICATE BLOCKS")
    print("-" * 40)

    for i, block in enumerate(sorted_duplicates[:5]):
        print(f"\n{i+1}. {block.lines}-line block found in {block.file_count} files (Tokens: {block.total_tokens})")
        for fragment in block.fragments:
            print(f"  - {fragment.file}:{fragment.start_line}-{fragment.end_line}")
    
    if len(sorted_duplicates) > 5:
        print(f"\n... and {len(sorted_duplicates) - 5} more duplicate blocks.")

    print("\n" + "=" * 60)
    print("Recommendation: Refactor duplicated code into shared functions or classes.")
    print("=" * 60)


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python duplication_finder.py <project_path>")
        sys.exit(1)

    project = sys.argv[1]

    print(f"Scanning for code duplication in: {project}")
    try:
        analysis_result = analyze_duplication(project)
        print_summary(analysis_result)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"\nAn error occurred: {e}", file=sys.stderr)
        sys.exit(1)
