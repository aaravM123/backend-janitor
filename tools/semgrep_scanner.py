"""
Semgrep Scanner Tool

This module wraps Semgrep to scan code for security vulnerabilities.
It runs Semgrep, parses the JSON output, and categorizes findings by severity.
"""

import subprocess
import json
import os
import sys
import shutil
from pathlib import Path


def _get_scripts_dir_from_package() -> str | None:
    """
    Find the Scripts directory by locating where semgrep package is installed.

    This works regardless of PATH configuration - if pip install worked,
    we can find the executable.
    """
    try:
        # Method 1: Use importlib.metadata (Python 3.8+)
        from importlib.metadata import distribution
        dist = distribution("semgrep")

        # The package location is in site-packages
        # Scripts are in a parallel directory structure
        package_location = Path(dist._path).parent  # site-packages dir

        # Navigate from site-packages to Scripts
        # site-packages is typically at: .../Python3XX/Lib/site-packages (system)
        # or: .../Python3XX/site-packages (user on Windows)

        # Try to find Scripts relative to site-packages
        possible_scripts = [
            package_location.parent / "Scripts",  # Windows user install
            package_location.parent.parent / "Scripts",  # Windows system install
            package_location.parent / "bin",  # Unix user install
            package_location.parent.parent / "bin",  # Unix system install
        ]

        for scripts_dir in possible_scripts:
            if scripts_dir.exists():
                return str(scripts_dir)

    except Exception:
        pass

    try:
        # Method 2: Parse pip show output
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "-f", "semgrep"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            location = None
            for line in result.stdout.splitlines():
                if line.startswith("Location:"):
                    location = line.split(":", 1)[1].strip()
                    break

            if location:
                # Derive Scripts from site-packages location
                site_packages = Path(location)
                possible_scripts = [
                    site_packages.parent / "Scripts",
                    site_packages.parent.parent / "Scripts",
                    site_packages.parent / "bin",
                    site_packages.parent.parent / "bin",
                ]

                for scripts_dir in possible_scripts:
                    if scripts_dir.exists():
                        return str(scripts_dir)

    except Exception:
        pass

    return None


def find_semgrep_command() -> list[str]:
    """
    Find the best way to invoke Semgrep.

    Tries multiple methods to find semgrep, ensuring it works even when
    the Scripts folder is not in PATH. If pip install succeeded, this
    function will find the executable.

    Order of preference:
    1. 'pysemgrep' or 'semgrep' in PATH
    2. Find from pip package installation location (works without PATH)
    3. Check common installation directories

    Returns:
        List of command parts to invoke semgrep

    Raises:
        RuntimeError if semgrep cannot be found
    """
    # Determine executable names based on platform
    if sys.platform == "win32":
        exe_names = ["pysemgrep.exe", "semgrep.exe"]
    else:
        exe_names = ["pysemgrep", "semgrep"]

    # Method 1: Check if already in PATH
    for exe in exe_names:
        path = shutil.which(exe)
        if path:
            return [path]

    # Method 2: Find from pip package installation (the magic - no PATH needed!)
    scripts_dir = _get_scripts_dir_from_package()
    if scripts_dir:
        for exe in exe_names:
            exe_path = os.path.join(scripts_dir, exe)
            if os.path.exists(exe_path):
                # Verify it's executable
                try:
                    result = subprocess.run(
                        [exe_path, "--version"],
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        return [exe_path]
                except Exception:
                    continue

    # Method 3: Check common installation directories (fallback)
    common_dirs = []

    if sys.platform == "win32":
        common_dirs = [
            os.path.join(os.path.dirname(sys.executable), "Scripts"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Python",
                        f"Python{sys.version_info.major}{sys.version_info.minor}", "Scripts"),
            os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs",
                        "Python", f"Python{sys.version_info.major}{sys.version_info.minor}", "Scripts"),
        ]
    else:
        common_dirs = [
            os.path.join(os.path.dirname(sys.executable), "..", "bin"),
            os.path.expanduser("~/.local/bin"),
            "/usr/local/bin",
        ]

    for scripts_dir in common_dirs:
        for exe in exe_names:
            exe_path = os.path.join(scripts_dir, exe)
            if os.path.exists(exe_path):
                return [exe_path]

    raise RuntimeError(
        "Semgrep not found. Please install it with:\n"
        "  pip install semgrep\n\n"
        "If you've already run 'pip install -r requirements.txt', semgrep should be installed.\n"
        "Try running: pip show semgrep\n"
        "If it shows as installed but still not working, try:\n"
        "  pip install --force-reinstall semgrep"
    )


def scan(project_path: str, config: str = "auto") -> dict:
    """
    Scan a project for security vulnerabilities using Semgrep.

    Args:
        project_path: Path to the project folder to scan
        config: Semgrep config to use ("auto" uses built-in rules)

    Returns:
        Dictionary with findings categorized by severity
    """

    if not os.path.exists(project_path):
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    # Find the best way to invoke semgrep
    try:
        semgrep_cmd = find_semgrep_command()
    except RuntimeError as e:
        return {
            "error": str(e),
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "unknown": [],
            "total_count": 0
        }

    # Build the full command
    command = semgrep_cmd + [
        "scan",
        project_path,
        f"--config={config}",
        "--json",
        "--quiet"
    ]

    # Set up environment with UTF-8 encoding to avoid Windows encoding issues
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"  # Fixes Windows charmap encoding errors

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            env=env
        )
    except subprocess.TimeoutExpired:
        return {
            "error": "Semgrep scan timed out after 10 minutes",
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "unknown": [],
            "total_count": 0
        }
    except FileNotFoundError:
        return {
            "error": f"Failed to execute semgrep command: {' '.join(command)}",
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "unknown": [],
            "total_count": 0
        }

    try:
        semgrep_output = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Debug: print what we got
        error_msg = f"Failed to parse Semgrep output.\n"
        error_msg += f"STDOUT ({len(result.stdout)} chars): {result.stdout[:500]}\n"
        error_msg += f"STDERR ({len(result.stderr)} chars): {result.stderr[:500]}\n"
        error_msg += f"Return code: {result.returncode}"
        return {
            "error": error_msg,
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "unknown": [],
            "total_count": 0
        }

    categorized = categorize_findings(semgrep_output)

    return categorized


def categorize_findings(semgrep_output: dict) -> dict:
    """
    Take raw Semgrep output and organize findings by severity.

    Semgrep returns a flat list of results. We want to group them
    into critical/high/medium/low buckets for easier prioritization.
    """

    findings = {
        "critical": [],
        "high": [],
        "medium": [],
        "low": [],
        "unknown": []
    }

    results = semgrep_output.get("results", [])

    for result in results:
        finding = {
            "file": result.get("path", "unknown"),
            "start_line": result.get("start", {}).get("line", 0),
            "end_line": result.get("end", {}).get("line", 0),
            "rule_id": result.get("check_id", "unknown"),
            "message": result.get("extra", {}).get("message", "No description"),
            "severity": result.get("extra", {}).get("severity", "UNKNOWN").lower(),
            "code_snippet": result.get("extra", {}).get("lines", "")
        }

        severity = finding["severity"]

        if severity in ["error", "critical"]:
            findings["critical"].append(finding)
        elif severity in ["warning", "high"]:
            findings["high"].append(finding)
        elif severity in ["info", "medium"]:
            findings["medium"].append(finding)
        elif severity == "low":
            findings["low"].append(finding)
        else:
            findings["unknown"].append(finding)

    findings["total_count"] = len(results)
    findings["errors"] = semgrep_output.get("errors", [])

    return findings


def print_summary(findings: dict) -> None:
    """
    Print a human-readable summary of the scan results.
    Useful for command-line output.
    """

    print("\n" + "=" * 50)
    print("SEMGREP SECURITY SCAN RESULTS")
    print("=" * 50)

    print(f"\nTotal issues found: {findings['total_count']}")
    print(f"  Critical: {len(findings['critical'])}")
    print(f"  High:     {len(findings['high'])}")
    print(f"  Medium:   {len(findings['medium'])}")
    print(f"  Low:      {len(findings['low'])}")
    print(f"  Unknown:  {len(findings['unknown'])}")

    if findings["critical"]:
        print("\nCRITICAL ISSUES:")
        for issue in findings["critical"]:
            print(f"  - {issue['file']}:{issue['start_line']}")
            print(f"    Rule: {issue['rule_id']}")
            print(f"    {issue['message'][:100]}...")

    if findings["high"]:
        print("\nHIGH SEVERITY ISSUES:")
        for issue in findings["high"]:
            print(f"  - {issue['file']}:{issue['start_line']}")
            print(f"    Rule: {issue['rule_id']}")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Semgrep Security Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python semgrep_scanner.py ./my-project              # Human-readable + JSON
  python semgrep_scanner.py ./my-project --json-only  # Only JSON (for piping)
  python semgrep_scanner.py ./my-project --config p/security-audit
        """
    )
    parser.add_argument("project_path", help="Path to project to scan")
    parser.add_argument("--config", default="auto", help="Semgrep config (default: auto)")
    parser.add_argument("--json-only", action="store_true",
                       help="Output only JSON, no human-readable summary")

    args = parser.parse_args()

    # Only print scanning message if not in json-only mode
    if not args.json_only:
        print(f"Scanning {args.project_path}...")

    results = scan(args.project_path, config=args.config)

    if "error" in results:
        if not args.json_only:
            print(f"Error: {results['error']}")
        else:
            # In json-only mode, still output the error as JSON
            print(json.dumps(results, indent=2))
        sys.exit(1)

    if args.json_only:
        # Only JSON output - clean for piping/redirection
        print(json.dumps(results, indent=2))
    else:
        # Human-readable summary + JSON
        print_summary(results)
        print("\nRaw JSON output:")
        print(json.dumps(results, indent=2))
