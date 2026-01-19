"""
PR Creator - GitHub Pull Request Automation

Creates branches, commits changes, pushes to remote, and opens PRs using GitHub CLI.

Usage:
    from tools.pr_creator import create_pr, create_branch, commit_changes

    # Full workflow
    pr_url = create_pr(
        title="Fix security vulnerabilities",
        body="Fixes SQL injection in user.py",
        changes=["tools/user.py", "tools/auth.py"],
    )

Requirements:
    - Git installed and configured
    - GitHub CLI (gh) installed and authenticated
    - Run: gh auth login
"""

import argparse
import subprocess
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class PRResult:
    """Result of PR creation."""
    success: bool
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    branch_name: Optional[str] = None
    error: Optional[str] = None
    commands: Optional[list[str]] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "branch_name": self.branch_name,
            "error": self.error,
            "commands": self.commands,
        }


@dataclass
class CommitResult:
    """Result of a commit operation."""
    success: bool
    commit_hash: Optional[str] = None
    message: Optional[str] = None
    files_changed: int = 0
    error: Optional[str] = None


def _run_git(args: list[str], cwd: Optional[str] = None) -> tuple[bool, str, str]:
    """Run a git command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=60,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return False, "", "Git not found. Please install git."
    except subprocess.TimeoutExpired:
        return False, "", "Git command timed out."


def _run_gh(args: list[str], cwd: Optional[str] = None) -> tuple[bool, str, str]:
    """Run a GitHub CLI command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return False, "", "GitHub CLI (gh) not found. Install from: https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return False, "", "GitHub CLI command timed out."


def check_prerequisites(project_path: str = ".") -> dict:
    """
    Check if all prerequisites are met for PR creation.

    Returns dict with status of each requirement.
    """
    results = {
        "git_installed": False,
        "gh_installed": False,
        "gh_authenticated": False,
        "is_git_repo": False,
        "has_remote": False,
        "all_ok": False,
    }

    # Check git
    success, _, _ = _run_git(["--version"])
    results["git_installed"] = success

    # Check gh
    success, _, _ = _run_gh(["--version"])
    results["gh_installed"] = success

    # Check gh auth
    if results["gh_installed"]:
        success, _, _ = _run_gh(["auth", "status"])
        results["gh_authenticated"] = success

    # Check if git repo
    success, _, _ = _run_git(["rev-parse", "--git-dir"], cwd=project_path)
    results["is_git_repo"] = success

    # Check remote
    if results["is_git_repo"]:
        success, stdout, _ = _run_git(["remote", "-v"], cwd=project_path)
        results["has_remote"] = success and len(stdout) > 0

    results["all_ok"] = all([
        results["git_installed"],
        results["gh_installed"],
        results["gh_authenticated"],
        results["is_git_repo"],
        results["has_remote"],
    ])

    return results


def get_current_branch(project_path: str = ".") -> Optional[str]:
    """Get the current git branch name."""
    success, stdout, _ = _run_git(["branch", "--show-current"], cwd=project_path)
    return stdout if success else None


def get_default_branch(project_path: str = ".") -> str:
    """Get the default branch (main or master)."""
    # Try to get from remote
    success, stdout, _ = _run_git(
        ["symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
        cwd=project_path
    )
    if success and stdout:
        return stdout.replace("origin/", "")

    # Check if main exists
    success, _, _ = _run_git(["show-ref", "--verify", "refs/heads/main"], cwd=project_path)
    if success:
        return "main"

    return "master"


def create_branch(
    branch_name: str,
    project_path: str = ".",
    base_branch: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Create a new git branch.

    Args:
        branch_name: Name for the new branch
        project_path: Path to the git repository
        base_branch: Base branch to create from (default: current branch)

    Returns:
        (success, message)
    """
    # Checkout base branch if specified
    if base_branch:
        success, _, stderr = _run_git(["checkout", base_branch], cwd=project_path)
        if not success:
            return False, f"Failed to checkout {base_branch}: {stderr}"

        # Pull latest
        _run_git(["pull"], cwd=project_path)

    # Create and checkout new branch
    success, _, stderr = _run_git(["checkout", "-b", branch_name], cwd=project_path)
    if not success:
        # Branch might already exist, try switching
        success, _, stderr = _run_git(["checkout", branch_name], cwd=project_path)
        if not success:
            return False, f"Failed to create branch: {stderr}"

    return True, f"Created and switched to branch: {branch_name}"


def generate_branch_name(prefix: str = "janitor") -> str:
    """Generate a unique branch name."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}/{timestamp}"


def _dry_run_pr_commands(
    title: str,
    body: str,
    changes: Optional[list[str]],
    base_branch: str,
    branch_name: str,
    draft: bool,
    labels: Optional[list[str]],
    auto_commit: bool,
) -> list[str]:
    commands = []
    commands.append(f"git checkout {base_branch}")
    commands.append("git pull")
    commands.append(f"git checkout -b {branch_name}")

    if changes and auto_commit:
        for file in changes:
            commands.append(f"git add {file}")
        commands.append(f"git commit -m {title!r}")

    commands.append(f"git push -u origin {branch_name}")

    gh_cmd = [
        "gh pr create",
        f"--title {title!r}",
        f"--body {body!r}",
        f"--base {base_branch}",
    ]
    if draft:
        gh_cmd.append("--draft")
    if labels:
        for label in labels:
            gh_cmd.append(f"--label {label!r}")
    commands.append(" ".join(gh_cmd))

    return commands


def stage_files(
    files: list[str],
    project_path: str = ".",
) -> tuple[bool, str]:
    """
    Stage files for commit.

    Args:
        files: List of file paths to stage (or ["."] for all)
        project_path: Path to the git repository

    Returns:
        (success, message)
    """
    for file in files:
        success, _, stderr = _run_git(["add", file], cwd=project_path)
        if not success:
            return False, f"Failed to stage {file}: {stderr}"

    return True, f"Staged {len(files)} file(s)"


def commit_changes(
    message: str,
    files: Optional[list[str]] = None,
    project_path: str = ".",
    add_signature: bool = True,
) -> CommitResult:
    """
    Commit staged changes.

    Args:
        message: Commit message
        files: Optional list of files to stage before committing
        project_path: Path to the git repository
        add_signature: Add Backend Janitor signature to commit

    Returns:
        CommitResult with commit details
    """
    # Stage files if provided
    if files:
        success, error = stage_files(files, project_path)
        if not success:
            return CommitResult(success=False, error=error)

    # Build commit message
    full_message = message
    if add_signature:
        full_message += "\n\n---\nGenerated by Backend Janitor"

    # Commit
    success, stdout, stderr = _run_git(
        ["commit", "-m", full_message],
        cwd=project_path
    )

    if not success:
        if "nothing to commit" in stderr.lower() or "nothing to commit" in stdout.lower():
            return CommitResult(success=False, error="Nothing to commit")
        return CommitResult(success=False, error=stderr)

    # Get commit hash
    success, commit_hash, _ = _run_git(["rev-parse", "HEAD"], cwd=project_path)

    # Count files changed
    success, stdout, _ = _run_git(["diff", "--stat", "HEAD~1"], cwd=project_path)
    files_changed = stdout.count("\n") if stdout else 0

    return CommitResult(
        success=True,
        commit_hash=commit_hash[:8] if commit_hash else None,
        message=message,
        files_changed=files_changed,
    )


def push_branch(
    branch_name: Optional[str] = None,
    project_path: str = ".",
    set_upstream: bool = True,
) -> tuple[bool, str]:
    """
    Push branch to remote.

    Args:
        branch_name: Branch to push (default: current branch)
        project_path: Path to the git repository
        set_upstream: Set upstream tracking

    Returns:
        (success, message)
    """
    if not branch_name:
        branch_name = get_current_branch(project_path)

    args = ["push"]
    if set_upstream:
        args.extend(["-u", "origin", branch_name])
    else:
        args.extend(["origin", branch_name])

    success, stdout, stderr = _run_git(args, cwd=project_path)

    if not success:
        return False, f"Failed to push: {stderr}"

    return True, f"Pushed {branch_name} to origin"


def create_pr(
    title: str,
    body: str,
    changes: Optional[list[str]] = None,
    base_branch: Optional[str] = None,
    branch_name: Optional[str] = None,
    project_path: str = ".",
    draft: bool = False,
    labels: Optional[list[str]] = None,
    auto_commit: bool = True,
    dry_run: bool = False,
) -> PRResult:
    """
    Create a GitHub Pull Request.

    Full workflow:
    1. Create branch (if branch_name provided)
    2. Stage and commit changes (if changes provided)
    3. Push to remote
    4. Create PR via gh CLI

    Args:
        title: PR title
        body: PR description/body
        changes: List of files to commit (optional)
        base_branch: Target branch for PR (default: repo default)
        branch_name: Name for new branch (auto-generated if None)
        project_path: Path to the git repository
        draft: Create as draft PR
        labels: Labels to add to PR
        auto_commit: Automatically commit staged changes

    Returns:
        PRResult with PR URL and details
    """
    # Check prerequisites
    prereqs = check_prerequisites(project_path)
    if not prereqs["all_ok"] and not dry_run:
        missing = [k for k, v in prereqs.items() if not v and k != "all_ok"]
        return PRResult(
            success=False,
            error=f"Prerequisites not met: {', '.join(missing)}"
        )
    if dry_run and (not prereqs["git_installed"] or not prereqs["is_git_repo"]):
        missing = []
        if not prereqs["git_installed"]:
            missing.append("git_installed")
        if not prereqs["is_git_repo"]:
            missing.append("is_git_repo")
        return PRResult(
            success=False,
            error=f"Prerequisites not met for dry run: {', '.join(missing)}"
        )

    # Get base branch
    if not base_branch:
        base_branch = get_default_branch(project_path)

    # Create branch if needed
    if branch_name:
        selected_branch = branch_name
    else:
        selected_branch = generate_branch_name()

    if dry_run:
        return PRResult(
            success=True,
            pr_url="DRY_RUN",
            pr_number=None,
            branch_name=selected_branch,
            commands=_dry_run_pr_commands(
                title=title,
                body=body,
                changes=changes,
                base_branch=base_branch,
                branch_name=selected_branch,
                draft=draft,
                labels=labels,
                auto_commit=auto_commit,
            ),
        )

    if branch_name:
        success, error = create_branch(branch_name, project_path, base_branch)
        if not success:
            return PRResult(success=False, error=error)
    else:
        # Generate branch name
        branch_name = selected_branch
        success, error = create_branch(branch_name, project_path, base_branch)
        if not success:
            return PRResult(success=False, error=error)

    # Commit changes if provided
    if changes and auto_commit:
        commit_result = commit_changes(
            message=title,
            files=changes,
            project_path=project_path,
        )
        if not commit_result.success:
            return PRResult(
                success=False,
                branch_name=branch_name,
                error=commit_result.error
            )

    # Push branch
    success, error = push_branch(branch_name, project_path)
    if not success:
        return PRResult(
            success=False,
            branch_name=branch_name,
            error=error
        )

    # Create PR via gh
    gh_args = [
        "pr", "create",
        "--title", title,
        "--body", body,
        "--base", base_branch,
    ]

    if draft:
        gh_args.append("--draft")

    if labels:
        for label in labels:
            gh_args.extend(["--label", label])

    success, stdout, stderr = _run_gh(gh_args, cwd=project_path)

    if not success:
        return PRResult(
            success=False,
            branch_name=branch_name,
            error=f"Failed to create PR: {stderr}"
        )

    # Extract PR URL and number
    pr_url = stdout.strip()
    pr_number = None

    # Extract PR number from URL (e.g., .../pull/123)
    match = re.search(r"/pull/(\d+)", pr_url)
    if match:
        pr_number = int(match.group(1))

    return PRResult(
        success=True,
        pr_url=pr_url,
        pr_number=pr_number,
        branch_name=branch_name,
    )


def create_pr_from_current_branch(
    title: str,
    body: str,
    base_branch: Optional[str] = None,
    project_path: str = ".",
    draft: bool = False,
    dry_run: bool = False,
) -> PRResult:
    """
    Create a PR from the current branch (assumes changes already committed).

    Args:
        title: PR title
        body: PR description
        base_branch: Target branch
        project_path: Path to git repo
        draft: Create as draft

    Returns:
        PRResult
    """
    current_branch = get_current_branch(project_path)
    if not current_branch:
        return PRResult(success=False, error="Could not determine current branch")

    if not base_branch:
        base_branch = get_default_branch(project_path)

    if dry_run:
        return PRResult(
            success=True,
            pr_url="DRY_RUN",
            pr_number=None,
            branch_name=current_branch,
            commands=_dry_run_pr_commands(
                title=title,
                body=body,
                changes=None,
                base_branch=base_branch,
                branch_name=current_branch,
                draft=draft,
                labels=None,
                auto_commit=False,
            ),
        )

    # Push current branch
    success, error = push_branch(current_branch, project_path)
    if not success:
        return PRResult(success=False, error=error)

    # Create PR
    gh_args = [
        "pr", "create",
        "--title", title,
        "--body", body,
        "--base", base_branch,
    ]

    if draft:
        gh_args.append("--draft")

    success, stdout, stderr = _run_gh(gh_args, cwd=project_path)

    if not success:
        return PRResult(success=False, error=f"Failed to create PR: {stderr}")

    pr_url = stdout.strip()
    pr_number = None
    match = re.search(r"/pull/(\d+)", pr_url)
    if match:
        pr_number = int(match.group(1))

    return PRResult(
        success=True,
        pr_url=pr_url,
        pr_number=pr_number,
        branch_name=current_branch,
    )


def format_pr_body(
    summary: str,
    changes: list[str],
    test_results: Optional[dict] = None,
    issues_fixed: Optional[list[dict]] = None,
) -> str:
    """
    Format a nice PR body with all the details.

    Args:
        summary: Short summary of changes
        changes: List of files changed
        test_results: Optional test results dict
        issues_fixed: Optional list of issues that were fixed

    Returns:
        Formatted PR body markdown
    """
    body_parts = []

    # Summary
    body_parts.append("## Summary")
    body_parts.append(summary)
    body_parts.append("")

    # Issues fixed
    if issues_fixed:
        body_parts.append("## Issues Fixed")
        for issue in issues_fixed:
            severity = issue.get("severity", "medium").upper()
            category = issue.get("category", "")
            file = issue.get("file", "")
            line = issue.get("line", "")
            body_parts.append(f"- **[{severity}]** {category} in `{file}:{line}`")
        body_parts.append("")

    # Files changed
    body_parts.append("## Files Changed")
    for file in changes:
        body_parts.append(f"- `{file}`")
    body_parts.append("")

    # Test results
    if test_results:
        body_parts.append("## Test Results")
        passed = test_results.get("passed", 0)
        failed = test_results.get("failed", 0)
        status = "PASSED" if failed == 0 else "FAILED"
        body_parts.append(f"**Status:** {status}")
        body_parts.append(f"- Passed: {passed}")
        body_parts.append(f"- Failed: {failed}")
        body_parts.append("")

    # Footer
    body_parts.append("---")
    body_parts.append("*Generated by Backend Janitor*")

    return "\n".join(body_parts)


def _parse_create_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pr_creator.py create",
        description="Create a PR with optional branch/commit automation.",
    )
    parser.add_argument("title", help="PR title")
    parser.add_argument("--project-path", default=".", help="Path to the git repository")
    parser.add_argument("--base", help="Base branch for the PR")
    parser.add_argument("--branch", help="Branch name to create or reuse")
    parser.add_argument("--draft", action="store_true", help="Create as draft PR")
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="Label to add (repeatable)",
    )
    parser.add_argument(
        "--change",
        action="append",
        default=[],
        help="File or path to stage (repeatable, defaults to all)",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Skip staging and committing changes",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    return parser.parse_args(argv)


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pr_creator.py <command> [options]")
        print("\nCommands:")
        print("  check              Check prerequisites")
        print("  create <title>     Create PR with title")
        print("\nExample:")
        print("  python pr_creator.py check")
        print('  python pr_creator.py create "Fix security issues"')
        print('  python pr_creator.py create --dry-run "Fix security issues"')
        sys.exit(1)

    command = sys.argv[1]

    if command == "check":
        print("Checking prerequisites...")
        results = check_prerequisites()
        for key, value in results.items():
            status = "[OK]" if value else "[FAIL]"
            print(f"  {status} {key}")

    elif command == "create":
        parsed = _parse_create_args(sys.argv[2:])
        title = parsed.title
        body = "Automated changes by Backend Janitor"
        changes = parsed.change or ["."]
        auto_commit = not parsed.no_commit

        action = "Dry run for PR" if parsed.dry_run else "Creating PR"
        print(f"{action}: {title}")
        result = create_pr(
            title=title,
            body=body,
            changes=changes if auto_commit else None,
            base_branch=parsed.base,
            branch_name=parsed.branch,
            project_path=parsed.project_path,
            draft=parsed.draft,
            labels=parsed.label or None,
            auto_commit=auto_commit,
            dry_run=parsed.dry_run,
        )

        if result.success:
            if parsed.dry_run and result.commands:
                print("\n[DRY RUN] Commands that would be executed:")
                for command_line in result.commands:
                    print(f"  {command_line}")
            print(f"\n[OK] PR created: {result.pr_url}")
        else:
            print(f"\n[FAIL] {result.error}")
