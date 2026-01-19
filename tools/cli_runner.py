"""
Backend Janitor CLI runner.

Maps CLI commands to Goose recipes and parameters.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_ENV = "BACKEND_JANITOR_CONFIG"
GOOSE_CMD_ENV = "BACKEND_JANITOR_GOOSE_CMD"

RECIPE_FILES = {
    "security": "recipes/security-scan.yaml",
    "tech-debt": "recipes/tech-debt-scan.yaml",
    "full": "recipes/full-janitor.yaml",
}

PRIORITY_CHOICES = ["security_first", "tech_debt_first", "severity", "quick_wins"]
FOCUS_CHOICES = ["all", "unused_code", "complexity", "style"]
SEVERITY_FILTER_CHOICES = ["all", "medium", "high", "critical"]
STRATEGY_CHOICES = ["safe", "approved", "all"]


@dataclass(frozen=True)
class RunRequest:
    recipe_path: Path
    params: dict[str, str]
    description: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_config_path(root: Path) -> Path:
    return root / "configs" / "janitor-config.yaml"


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _get_nested(config: dict[str, Any], keys: list[str], default: Any) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _resolve_project_path(path: str) -> str:
    return str(Path(path).resolve())


def _bool_param(value: bool) -> str:
    return "true" if value else "false"


def _recipe_path(root: Path, mode: str) -> Path:
    recipe_rel = RECIPE_FILES.get(mode)
    if not recipe_rel:
        raise ValueError(f"Unknown mode: {mode}")
    path = (root / recipe_rel).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Recipe not found: {path}")
    return path


def _build_scan_request(args: argparse.Namespace, config: dict[str, Any], root: Path) -> RunRequest:
    project_path = _resolve_project_path(args.project_path)

    if args.mode == "security":
        semgrep_config = args.semgrep_config or _get_nested(
            config,
            ["tools", "semgrep", "config"],
            "auto",
        )
        severity_filter = args.severity_filter or "all"
        params = {
            "project_path": project_path,
            "auto_fix": "false",
            "severity_filter": severity_filter,
            "semgrep_config": semgrep_config,
        }
        description = "Security scan (report only)"

    elif args.mode == "tech-debt":
        threshold = args.complexity_threshold
        if threshold is None:
            threshold = _get_nested(
                config,
                ["tools", "complexity_analyzer", "report_threshold", "cyclomatic_complexity"],
                10,
            )
        params = {
            "project_path": project_path,
            "auto_fix": "false",
            "focus_area": args.focus_area or "all",
            "complexity_threshold": str(threshold),
        }
        description = "Tech debt scan (report only)"

    else:
        priority = args.priority or _get_nested(
            config,
            ["prioritization", "default_mode"],
            "security_first",
        )
        params = {
            "project_path": project_path,
            "mode": "report",
            "priority": priority,
            "create_pr": "false",
        }
        description = "Full scan (report only)"

    return RunRequest(_recipe_path(root, args.mode), params, description)


def _build_fix_request(args: argparse.Namespace, config: dict[str, Any], root: Path) -> RunRequest:
    project_path = _resolve_project_path(args.project_path)

    if args.mode == "security":
        semgrep_config = args.semgrep_config or _get_nested(
            config,
            ["tools", "semgrep", "config"],
            "auto",
        )
        severity_filter = args.severity_filter or "all"
        params = {
            "project_path": project_path,
            "auto_fix": "true",
            "severity_filter": severity_filter,
            "semgrep_config": semgrep_config,
        }
        description = "Security fix run"

    elif args.mode == "tech-debt":
        threshold = args.complexity_threshold
        if threshold is None:
            threshold = _get_nested(
                config,
                ["tools", "complexity_analyzer", "report_threshold", "cyclomatic_complexity"],
                10,
            )
        params = {
            "project_path": project_path,
            "auto_fix": "true",
            "focus_area": args.focus_area or "all",
            "complexity_threshold": str(threshold),
        }
        description = "Tech debt fix run"

    else:
        priority = args.priority or _get_nested(
            config,
            ["prioritization", "default_mode"],
            "security_first",
        )
        mode_map = {
            "safe": "fix_safe",
            "approved": "fix_approved",
            "all": "fix_all",
        }
        mode = mode_map.get(args.strategy, "fix_safe")
        create_pr = args.create_pr or bool(args.pr_title)
        params = {
            "project_path": project_path,
            "mode": mode,
            "priority": priority,
            "create_pr": _bool_param(create_pr),
        }
        if args.pr_title:
            params["pr_title"] = args.pr_title
        description = f"Full fix run ({args.strategy})"

    return RunRequest(_recipe_path(root, args.mode), params, description)


def _build_pr_request(args: argparse.Namespace, config: dict[str, Any], root: Path) -> RunRequest:
    project_path = _resolve_project_path(args.project_path)
    priority = args.priority or _get_nested(
        config,
        ["prioritization", "default_mode"],
        "security_first",
    )
    params = {
        "project_path": project_path,
        "mode": "pr",
        "priority": priority,
        "create_pr": "true",
    }
    if args.pr_title:
        params["pr_title"] = args.pr_title

    return RunRequest(_recipe_path(root, "full"), params, "Full fix run with PR")


def _build_request(args: argparse.Namespace, config: dict[str, Any], root: Path) -> RunRequest:
    if args.command == "scan":
        return _build_scan_request(args, config, root)
    if args.command == "fix":
        return _build_fix_request(args, config, root)
    if args.command == "pr":
        return _build_pr_request(args, config, root)
    if args.command == "report":
        args.mode = "full"
        return _build_scan_request(args, config, root)
    raise ValueError(f"Unknown command: {args.command}")


def _format_command(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def _build_goose_command(args: argparse.Namespace, request: RunRequest) -> list[str]:
    cmd = [args.goose_cmd, "run", "--recipe", str(request.recipe_path)]

    for key, value in sorted(request.params.items()):
        cmd.extend(["--params", f"{key}={value}"])

    if args.explain:
        cmd.append("--explain")
    if args.render_recipe:
        cmd.append("--render-recipe")
    if args.interactive:
        cmd.append("--interactive")
    if args.debug:
        cmd.append("--debug")
    if args.no_session:
        cmd.append("--no-session")
    if args.max_turns is not None:
        cmd.extend(["--max-turns", str(args.max_turns)])
    if args.provider:
        cmd.extend(["--provider", args.provider])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.output_format:
        cmd.extend(["--output-format", args.output_format])
    if args.quiet:
        cmd.append("--quiet")
    if args.goose_arg:
        cmd.extend(args.goose_arg)

    return cmd


def _run_command(cmd: list[str], root: Path, dry_run: bool) -> int:
    if dry_run:
        print(_format_command(cmd))
        return 0

    env = os.environ.copy()
    env.setdefault("BACKEND_JANITOR_ROOT", str(root))

    try:
        result = subprocess.run(cmd, cwd=root, env=env)
    except FileNotFoundError:
        print(
            "Error: Goose CLI not found. Install goose or set BACKEND_JANITOR_GOOSE_CMD.",
            file=sys.stderr,
        )
        return 127

    return result.returncode


def _add_common_flags(parser: argparse.ArgumentParser, root: Path) -> None:
    default_config = os.getenv(CONFIG_ENV, str(_default_config_path(root)))

    parser.add_argument(
        "--project-path",
        default=".",
        help="Target project to scan or fix (default: .)",
    )
    parser.add_argument(
        "--config",
        default=default_config,
        help="Path to janitor-config.yaml",
    )
    parser.add_argument(
        "--goose-cmd",
        default=os.getenv(GOOSE_CMD_ENV, "goose"),
        help="Goose CLI command (default: goose)",
    )
    parser.add_argument("--interactive", action="store_true", help="Run goose interactively")
    parser.add_argument("--debug", action="store_true", help="Enable goose debug output")
    parser.add_argument("--no-session", action="store_true", help="Disable goose session storage")
    parser.add_argument("--max-turns", type=int, help="Limit goose turns")
    parser.add_argument("--provider", help="Override goose provider")
    parser.add_argument("--model", help="Override goose model")
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        help="Goose output format",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress non-response output")
    parser.add_argument("--explain", action="store_true", help="Show recipe details and exit")
    parser.add_argument(
        "--render-recipe",
        action="store_true",
        help="Render recipe without running it",
    )
    parser.add_argument(
        "--goose-arg",
        action="append",
        default=[],
        help="Extra argument passed to goose (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the goose command and exit")
    parser.add_argument("--verbose", action="store_true", help="Print the resolved run details")


def _build_parser(root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backend-janitor",
        description="Backend Janitor CLI wrapper for Goose recipes",
    )

    common = argparse.ArgumentParser(add_help=False)
    _add_common_flags(common, root)

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", parents=[common], help="Run a scan without fixes")
    scan.add_argument(
        "--mode",
        choices=["security", "tech-debt", "full"],
        default="full",
        help="Scan mode (default: full)",
    )
    scan.add_argument("--severity-filter", choices=SEVERITY_FILTER_CHOICES)
    scan.add_argument("--semgrep-config", help="Semgrep config (auto, p/security-audit, etc)")
    scan.add_argument("--focus-area", choices=FOCUS_CHOICES)
    scan.add_argument("--complexity-threshold", type=int)
    scan.add_argument("--priority", choices=PRIORITY_CHOICES)

    fix = subparsers.add_parser("fix", parents=[common], help="Fix issues with approvals")
    fix.add_argument(
        "--mode",
        choices=["security", "tech-debt", "full"],
        default="full",
        help="Fix mode (default: full)",
    )
    fix.add_argument("--severity-filter", choices=SEVERITY_FILTER_CHOICES)
    fix.add_argument("--semgrep-config", help="Semgrep config (auto, p/security-audit, etc)")
    fix.add_argument("--focus-area", choices=FOCUS_CHOICES)
    fix.add_argument("--complexity-threshold", type=int)
    fix.add_argument("--priority", choices=PRIORITY_CHOICES)
    fix.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default="safe",
        help="Full mode fix strategy (default: safe)",
    )
    fix.add_argument("--create-pr", action="store_true", help="Create a PR after fixes")
    fix.add_argument("--pr-title", help="PR title override")

    pr = subparsers.add_parser("pr", parents=[common], help="Fix issues and open a PR")
    pr.add_argument("--priority", choices=PRIORITY_CHOICES)
    pr.add_argument("--pr-title", help="PR title override")

    report = subparsers.add_parser(
        "report",
        parents=[common],
        help="Full scan report (alias for scan --mode full)",
    )
    report.add_argument("--priority", choices=PRIORITY_CHOICES)
    report.set_defaults(mode="full")

    return parser


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = _build_parser(root)
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = _load_config(config_path)

    try:
        request = _build_request(args, config, root)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    cmd = _build_goose_command(args, request)

    if args.verbose:
        print(f"Backend Janitor: {request.description}")
        print(f"Recipe: {request.recipe_path}")
        print(f"Params: {request.params}")
        print(f"Command: {_format_command(cmd)}")

    return _run_command(cmd, root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
