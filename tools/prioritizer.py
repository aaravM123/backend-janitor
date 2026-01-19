"""
Prioritizer Tool - Unified Security & Tech Debt Prioritizer

This module takes findings from BOTH security scanners (semgrep) AND
tech debt analyzers (ruff, complexity) and produces a unified,
prioritized fix list.

Key responsibilities:
- Accept findings from multiple sources (semgrep, ruff, complexity analyzer)
- Rank ALL issues on a unified scale (security vs tech debt)
- Group related issues by file for batch fixing
- Estimate fix complexity based on various factors
- Return an ordered list ready for the LLM to process

Priority Order (default - security_first):
1. CRITICAL security issues (SQL injection, RCE, auth bypass)
2. HIGH security issues (XSS, hardcoded secrets)
3. MEDIUM security issues
4. Errors/bugs from linting (actual bugs)
5. Dead code and unused imports (quick wins)
6. Complex functions needing refactoring
7. LOW security issues
8. Style issues

Usage:
    from tools.prioritizer import prioritize_all, prioritize

    # Security only (original behavior)
    result = prioritize(semgrep_findings)

    # Unified (security + tech debt)
    result = prioritize_all(
        security_findings=semgrep_findings,
        ruff_findings=ruff_results,
        complexity_findings=complexity_results
    )
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import IntEnum, Enum
from typing import Optional


class IssueType(Enum):
    SECURITY = "security"
    TECH_DEBT = "tech_debt"


class Severity(IntEnum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    UNKNOWN = 5


class Complexity(IntEnum):
    TRIVIAL = 1     
    EASY = 2        
    MODERATE = 3    
    COMPLEX = 4   
    VERY_COMPLEX = 5 


class TechDebtCategory(Enum):
    """Categories of tech debt issues."""
    UNUSED_IMPORTS = "unused_imports" 
    DEAD_CODE = "dead_code"          
    ERRORS = "errors"           
    COMPLEXITY = "complexity"      
    STYLE = "style"           


class PriorityMode(Enum):
    """Different ways to prioritize issues."""
    SECURITY_FIRST = "security_first"   
    TECH_DEBT_FIRST = "tech_debt_first" 
    SEVERITY = "severity"              
    QUICK_WINS = "quick_wins"    


# =============================================================================
# UNIFIED PRIORITY SCORING SYSTEM
# Lower score = higher priority (fix first)
#
# The scoring system uses "tiers" to ensure proper ordering:
# - Tier 1 (1.0-1.9): Critical security issues
# - Tier 2 (2.0-2.9): High security issues
# - Tier 3 (3.0-3.9): Medium security + Linting errors (actual bugs)
# - Tier 4 (4.0-4.9): Dead code + Unused imports (quick wins)
# - Tier 5 (5.0-5.9): Complex functions needing refactoring
# - Tier 6 (6.0-6.9): Low security issues
# - Tier 7 (7.0-7.9): Style issues

SECURITY_SEVERITY_SCORES = {
    "critical": 1.0,  
    "high": 2.0,    
    "medium": 3.0,   
    "low": 6.0,     
    "unknown": 6.5,   
}

TECH_DEBT_CATEGORY_SCORES = {
    "errors": 3.5,        
    "unused_imports": 4.0,
    "dead_code": 4.2,     
    "complexity": 5.0,    
    "style": 7.0,        
}

TECH_DEBT_COMPLEXITY = {
    "unused_imports": Complexity.TRIVIAL,  
    "dead_code": Complexity.EASY,          
    "errors": Complexity.MODERATE,         
    "complexity": Complexity.COMPLEX,      
    "style": Complexity.TRIVIAL,           
}


COMPLEX_RULE_PATTERNS = {
    "sql-injection": Complexity.COMPLEX,
    "xss": Complexity.MODERATE,
    "hardcoded-secret": Complexity.EASY,
    "hardcoded-password": Complexity.EASY,
    "path-traversal": Complexity.MODERATE,
    "command-injection": Complexity.COMPLEX,
    "deserialization": Complexity.COMPLEX,
    "xxe": Complexity.COMPLEX,
    "ssrf": Complexity.COMPLEX,
    "open-redirect": Complexity.MODERATE,
    "csrf": Complexity.MODERATE,
    "insecure-cookie": Complexity.TRIVIAL,
    "missing-auth": Complexity.COMPLEX,
    "weak-crypto": Complexity.MODERATE,
    "timing-attack": Complexity.COMPLEX,
}


@dataclass
class PrioritizedIssue:
    """A single issue with priority metadata attached."""
    file: str
    start_line: int
    end_line: int
    rule_id: str
    message: str
    severity: str
    code_snippet: str

    issue_type: str = "security"          
    tech_debt_category: Optional[str] = None  

    priority_score: float = 0.0
    complexity: str = "moderate"
    complexity_score: int = 3
    fix_order: int = 0
    group_id: Optional[str] = None

    lines_affected: int = 1
    related_issues_count: int = 0

    fix_available: bool = False       
    suggested_fix: Optional[str] = None   

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FileGroup:
    """Group of issues in the same file for batch processing."""
    file_path: str
    issues: list = field(default_factory=list)
    total_priority_score: float = 0.0
    highest_severity: str = "unknown"
    issue_count: int = 0

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "issues": [i.to_dict() for i in self.issues],
            "total_priority_score": self.total_priority_score,
            "highest_severity": self.highest_severity,
            "issue_count": self.issue_count
        }


def calculate_priority_score(finding: dict, severity: str) -> float:
    """
    Calculate a numeric priority score for a finding.

    Lower score = higher priority (should be fixed first)

    Factors:
    - Severity (major factor)
    - Lines affected (more lines = harder to fix = slightly lower priority)
    - Rule type (some issues are more impactful)
    """
    severity_map = {
        "critical": 1.0,
        "high": 2.0,
        "medium": 3.0,
        "low": 4.0,
        "unknown": 5.0
    }
    base_score = severity_map.get(severity, 5.0)

    start_line = finding.get("start_line", 0)
    end_line = finding.get("end_line", start_line)
    lines_affected = max(1, end_line - start_line + 1)

    line_adjustment = min(0.3, lines_affected * 0.01)

    rule_id = finding.get("rule_id", "").lower()
    rule_adjustment = 0.0

    high_impact_patterns = ["injection", "rce", "auth", "secret", "password"]
    for pattern in high_impact_patterns:
        if pattern in rule_id:
            rule_adjustment = -0.2
            break

    return base_score + line_adjustment + rule_adjustment


def estimate_complexity(finding: dict) -> tuple[Complexity, str]:
    """
    Estimate how complex a fix will be.

    Returns:
        Tuple of (complexity enum, human-readable explanation)
    """
    rule_id = finding.get("rule_id", "").lower()
    start_line = finding.get("start_line", 0)
    end_line = finding.get("end_line", start_line)
    lines_affected = max(1, end_line - start_line + 1)

    # Check for known complex patterns
    for pattern, complexity in COMPLEX_RULE_PATTERNS.items():
        if pattern in rule_id:
            explanation = get_complexity_explanation(complexity, rule_id)
            return complexity, explanation

    # Estimate based on lines affected
    if lines_affected <= 1:
        complexity = Complexity.TRIVIAL
    elif lines_affected <= 3:
        complexity = Complexity.EASY
    elif lines_affected <= 10:
        complexity = Complexity.MODERATE
    elif lines_affected <= 30:
        complexity = Complexity.COMPLEX
    else:
        complexity = Complexity.VERY_COMPLEX

    explanation = get_complexity_explanation(complexity, rule_id)
    return complexity, explanation


def get_complexity_explanation(complexity: Complexity, rule_id: str) -> str:
    """Generate human-readable explanation for complexity rating."""
    explanations = {
        Complexity.TRIVIAL: f"Simple fix - likely a one-line change",
        Complexity.EASY: f"Easy fix - minor code changes needed",
        Complexity.MODERATE: f"Moderate fix - requires understanding the context",
        Complexity.COMPLEX: f"Complex fix - may require refactoring ({rule_id})",
        Complexity.VERY_COMPLEX: f"Very complex - significant changes needed ({rule_id})"
    }
    return explanations.get(complexity, "Unknown complexity")


# =============================================================================
# TECH DEBT CONVERSION FUNCTIONS
# =============================================================================
# These functions convert ruff_analyzer and complexity_analyzer output
# into PrioritizedIssue objects so they can be mixed with security findings.
# =============================================================================

def convert_ruff_findings(ruff_result: dict) -> list[PrioritizedIssue]:
    """
    Convert ruff_analyzer output to PrioritizedIssue objects.

    Args:
        ruff_result: Output from ruff_analyzer.analyze().to_dict() with structure:
            {
                "unused_imports": [...],
                "dead_code": [...],
                "complexity": [...],
                "style": [...],
                "errors": [...]
            }

    Returns:
        List of PrioritizedIssue objects for tech debt issues
    """
    issues = []

    category_map = {
        "unused_imports": "unused_imports",
        "dead_code": "dead_code",
        "complexity": "complexity",
        "style": "style",
        "errors": "errors",
    }

    for category_key, tech_debt_category in category_map.items():
        for finding in ruff_result.get(category_key, []):
            base_score = TECH_DEBT_CATEGORY_SCORES.get(tech_debt_category, 7.0)

            complexity_enum = TECH_DEBT_COMPLEXITY.get(tech_debt_category, Complexity.MODERATE)
            complexity_explanation = get_complexity_explanation(complexity_enum, finding.get("code", ""))

            ruff_severity = finding.get("severity", "low")
            severity_map = {"high": "high", "medium": "medium", "low": "low"}
            severity = severity_map.get(ruff_severity, "low")

            severity_adjustment = {"high": -0.3, "medium": 0.0, "low": 0.2}.get(ruff_severity, 0.0)

            issue = PrioritizedIssue(
                file=finding.get("file", "unknown"),
                start_line=finding.get("line", 0),
                end_line=finding.get("line", 0), 
                rule_id=finding.get("code", "unknown"),
                message=finding.get("message", "Code quality issue"),
                severity=severity,
                code_snippet="",  
                issue_type=IssueType.TECH_DEBT.value,
                tech_debt_category=tech_debt_category,
                priority_score=base_score + severity_adjustment,
                complexity=complexity_explanation,
                complexity_score=complexity_enum.value,
                lines_affected=1,
                fix_available=finding.get("fix_available", False),
                suggested_fix=finding.get("suggested_fix"),
            )
            issues.append(issue)

    return issues


def convert_complexity_findings(complexity_result: dict) -> list[PrioritizedIssue]:
    """
    Convert complexity_analyzer output to PrioritizedIssue objects.

    Args:
        complexity_result: Output from complexity_analyzer.analyze_complexity().to_dict()
            with structure:
            {
                "functions": [
                    {
                        "name": "func_name",
                        "file": "path/to/file.py",
                        "line": 42,
                        "cyclomatic_complexity": 15,
                        "lines_of_code": 100,
                        "max_nesting_depth": 5,
                        "recommendation": "split",
                        "issues": ["High complexity...", ...]
                    },
                    ...
                ]
            }

    Returns:
        List of PrioritizedIssue objects for complexity issues
    """
    issues = []

    for func in complexity_result.get("functions", []):
        recommendation = func.get("recommendation", "ok")

        if recommendation == "ok":
            continue

        rec_to_severity = {
            "review": "medium",
            "split": "high",
            "refactor": "high",
        }
        rec_to_complexity = {
            "review": Complexity.MODERATE,
            "split": Complexity.COMPLEX,
            "refactor": Complexity.VERY_COMPLEX,
        }

        severity = rec_to_severity.get(recommendation, "low")
        complexity_enum = rec_to_complexity.get(recommendation, Complexity.MODERATE)

        base_score = TECH_DEBT_CATEGORY_SCORES.get("complexity", 5.0)
        rec_adjustment = {"review": 0.3, "split": 0.0, "refactor": -0.2}.get(recommendation, 0.0)

        issues_list = func.get("issues", [])
        message = f"Function '{func.get('name', 'unknown')}' needs attention"
        if issues_list:
            message = "; ".join(issues_list)

        issue = PrioritizedIssue(
            file=func.get("file", "unknown"),
            start_line=func.get("line", 0),
            end_line=func.get("line", 0) + func.get("lines_of_code", 1) - 1,
            rule_id=f"complexity-{recommendation}",
            message=message,
            severity=severity,
            code_snippet="",  
            issue_type=IssueType.TECH_DEBT.value,
            tech_debt_category="complexity",
            priority_score=base_score + rec_adjustment,
            complexity=f"Complexity fix - {recommendation} recommended",
            complexity_score=complexity_enum.value,
            lines_affected=func.get("lines_of_code", 1),
            fix_available=False,  # Complexity issues need manual refactoring
            suggested_fix=f"Consider breaking down this function (complexity: {func.get('cyclomatic_complexity', 0)})",
        )
        issues.append(issue)

    return issues


def convert_security_findings(security_findings: dict) -> list[PrioritizedIssue]:
    """
    Convert semgrep_scanner output to PrioritizedIssue objects.

    This is essentially what the original prioritize() did, but returns
    a list instead of the full result dict.

    Args:
        security_findings: Output from semgrep_scanner.scan() with structure:
            {
                "critical": [...],
                "high": [...],
                "medium": [...],
                "low": [...],
                "unknown": [...]
            }

    Returns:
        List of PrioritizedIssue objects for security issues
    """
    issues = []
    severity_order = ["critical", "high", "medium", "low", "unknown"]

    for severity in severity_order:
        for finding in security_findings.get(severity, []):
            # Use the new unified scoring
            base_score = SECURITY_SEVERITY_SCORES.get(severity, 6.5)

            # Adjust for rule type impact
            rule_id = finding.get("rule_id", "").lower()
            rule_adjustment = 0.0
            high_impact_patterns = ["injection", "rce", "auth", "secret", "password"]
            for pattern in high_impact_patterns:
                if pattern in rule_id:
                    rule_adjustment = -0.2
                    break

            # Adjust for lines affected
            start_line = finding.get("start_line", 0)
            end_line = finding.get("end_line", start_line)
            lines_affected = max(1, end_line - start_line + 1)
            line_adjustment = min(0.3, lines_affected * 0.01)

            priority_score = base_score + rule_adjustment + line_adjustment

            # Estimate complexity
            complexity_enum, complexity_explanation = estimate_complexity(finding)

            issue = PrioritizedIssue(
                file=finding.get("file", "unknown"),
                start_line=start_line,
                end_line=end_line,
                rule_id=finding.get("rule_id", "unknown"),
                message=finding.get("message", "No description"),
                severity=severity,
                code_snippet=finding.get("code_snippet", ""),
                issue_type=IssueType.SECURITY.value,
                tech_debt_category=None,
                priority_score=priority_score,
                complexity=complexity_explanation,
                complexity_score=complexity_enum.value,
                lines_affected=lines_affected,
                fix_available=False,
                suggested_fix=None,
            )
            issues.append(issue)

    return issues


# =============================================================================
# MAIN PRIORITIZATION FUNCTIONS
# =============================================================================

def prioritize_all(
    security_findings: Optional[dict] = None,
    ruff_findings: Optional[dict] = None,
    complexity_findings: Optional[dict] = None,
    mode: str = "security_first",
) -> dict:
    """
    UNIFIED PRIORITIZER: Combine and prioritize ALL types of findings.

    This is the main entry point for the full Backend Janitor workflow.
    It takes findings from security scanners AND tech debt analyzers,
    scores them on a unified scale, and returns a single prioritized list.

    Args:
        security_findings: Output from semgrep_scanner.scan()
        ruff_findings: Output from ruff_analyzer.analyze().to_dict()
        complexity_findings: Output from complexity_analyzer.analyze_complexity().to_dict()
        mode: Prioritization mode - one of:
            - "security_first": Security issues before tech debt (default)
            - "tech_debt_first": Tech debt before security
            - "severity": By severity regardless of type
            - "quick_wins": Easiest fixes first

    Returns:
        Dictionary with:
            - ordered_issues: Flat list sorted by priority
            - grouped_by_file: Issues grouped by file path
            - summary: Statistics about ALL findings
    """
    all_issues: list[PrioritizedIssue] = []

    # Convert and collect all findings
    if security_findings:
        all_issues.extend(convert_security_findings(security_findings))

    if ruff_findings:
        all_issues.extend(convert_ruff_findings(ruff_findings))

    if complexity_findings:
        all_issues.extend(convert_complexity_findings(complexity_findings))

    # Apply priority mode adjustments
    all_issues = apply_priority_mode(all_issues, mode)

    # Sort by priority score (lower = fix first), then by complexity
    all_issues.sort(key=lambda x: (x.priority_score, x.complexity_score))

    # Assign fix order
    for i, issue in enumerate(all_issues):
        issue.fix_order = i + 1

    # Group by file
    file_groups = group_by_file(all_issues)

    # Calculate unified summary
    summary = calculate_unified_summary(all_issues, file_groups)

    return {
        "ordered_issues": [issue.to_dict() for issue in all_issues],
        "grouped_by_file": [group.to_dict() for group in file_groups],
        "summary": summary,
    }


def apply_priority_mode(issues: list[PrioritizedIssue], mode: str) -> list[PrioritizedIssue]:
    """
    Adjust priority scores based on the selected mode.

    Args:
        issues: List of PrioritizedIssue objects
        mode: Priority mode (security_first, tech_debt_first, severity, quick_wins)

    Returns:
        Same list with adjusted priority_score values
    """
    for issue in issues:
        if mode == "security_first":
            if issue.issue_type == IssueType.TECH_DEBT.value:
                issue.priority_score += 0.05

        elif mode == "tech_debt_first":
            if issue.issue_type == IssueType.TECH_DEBT.value:
                issue.priority_score -= 3.0
            else:
                issue.priority_score += 2.0

        elif mode == "quick_wins":

            complexity_base = {
                1: 1.0,  # TRIVIAL - fix first
                2: 2.0,  # EASY
                3: 4.0,  # MODERATE
                4: 6.0,  # COMPLEX
                5: 8.0,  # VERY_COMPLEX - fix last
            }
            issue.priority_score = complexity_base.get(issue.complexity_score, 5.0)

        # mode == "severity" uses default scoring (already severity-based)

    return issues


def calculate_unified_summary(issues: list[PrioritizedIssue], groups: list) -> dict:
    """Generate summary statistics for unified findings (security + tech debt)."""
    if not issues:
        return {
            "total_issues": 0,
            "security_issues": 0,
            "tech_debt_issues": 0,
            "by_severity": {},
            "by_complexity": {},
            "by_type": {},
            "by_tech_debt_category": {},
            "files_affected": 0,
            "estimated_effort": "none",
            "quick_wins": 0,
            "recommended_approach": "No issues found - codebase is clean!"
        }

    # Count by type
    security_count = sum(1 for i in issues if i.issue_type == IssueType.SECURITY.value)
    tech_debt_count = sum(1 for i in issues if i.issue_type == IssueType.TECH_DEBT.value)

    # Count by severity
    severity_counts = defaultdict(int)
    for issue in issues:
        severity_counts[issue.severity] += 1

    # Count by complexity
    complexity_counts = defaultdict(int)
    complexity_names = {1: "trivial", 2: "easy", 3: "moderate", 4: "complex", 5: "very_complex"}
    for issue in issues:
        complexity_name = complexity_names.get(issue.complexity_score, "unknown")
        complexity_counts[complexity_name] += 1

    # Count by tech debt category
    tech_debt_category_counts = defaultdict(int)
    for issue in issues:
        if issue.tech_debt_category:
            tech_debt_category_counts[issue.tech_debt_category] += 1

    # Count quick wins (trivial + easy complexity with auto-fix available)
    quick_wins = sum(1 for i in issues if i.complexity_score <= 2 or i.fix_available)

    # Estimate total effort
    total_complexity = sum(i.complexity_score for i in issues)
    if total_complexity <= 10:
        effort = "minimal (< 30 minutes)"
    elif total_complexity <= 30:
        effort = "low (30 min - 2 hours)"
    elif total_complexity <= 60:
        effort = "moderate (2-4 hours)"
    elif total_complexity <= 120:
        effort = "significant (4-8 hours)"
    else:
        effort = "extensive (8+ hours)"

    # Generate recommended approach
    critical_count = severity_counts.get("critical", 0)
    high_count = severity_counts.get("high", 0)
    unused_imports = tech_debt_category_counts.get("unused_imports", 0)

    if critical_count > 0:
        approach = f"URGENT: Fix {critical_count} critical security issue(s) immediately!"
    elif high_count > 0:
        approach = f"HIGH PRIORITY: Address {high_count} high-severity issue(s) soon."
    elif unused_imports > 0:
        approach = f"Start with {unused_imports} unused imports (quick wins), then address other issues."
    else:
        approach = "No critical issues. Work through the prioritized list at your own pace."

    return {
        "total_issues": len(issues),
        "security_issues": security_count,
        "tech_debt_issues": tech_debt_count,
        "by_severity": dict(severity_counts),
        "by_complexity": dict(complexity_counts),
        "by_type": {
            "security": security_count,
            "tech_debt": tech_debt_count,
        },
        "by_tech_debt_category": dict(tech_debt_category_counts),
        "files_affected": len(groups),
        "estimated_effort": effort,
        "quick_wins": quick_wins,
        "recommended_approach": approach,
    }


def prioritize(findings: dict) -> dict:
    """
    Main entry point: take raw findings and return prioritized fix list.

    Args:
        findings: Output from semgrep_scanner.scan() with structure:
            {
                "critical": [...],
                "high": [...],
                "medium": [...],
                "low": [...],
                "unknown": [...],
                "total_count": int
            }

    Returns:
        Dictionary with:
            - ordered_issues: Flat list sorted by priority
            - grouped_by_file: Issues grouped by file path
            - summary: Statistics about the findings
    """
    all_issues = []
    severity_order = ["critical", "high", "medium", "low", "unknown"]

    # Process all findings and create PrioritizedIssue objects
    for severity in severity_order:
        for finding in findings.get(severity, []):
            priority_score = calculate_priority_score(finding, severity)
            complexity, complexity_explanation = estimate_complexity(finding)

            start_line = finding.get("start_line", 0)
            end_line = finding.get("end_line", start_line)

            issue = PrioritizedIssue(
                file=finding.get("file", "unknown"),
                start_line=start_line,
                end_line=end_line,
                rule_id=finding.get("rule_id", "unknown"),
                message=finding.get("message", "No description"),
                severity=severity,
                code_snippet=finding.get("code_snippet", ""),
                issue_type=IssueType.SECURITY.value,  # Original function is security-only
                tech_debt_category=None,
                priority_score=priority_score,
                complexity=complexity_explanation,
                complexity_score=complexity.value,
                lines_affected=max(1, end_line - start_line + 1),
            )
            all_issues.append(issue)

    # Sort by priority score (lower = fix first)
    all_issues.sort(key=lambda x: (x.priority_score, x.complexity_score))

    # Assign fix order
    for i, issue in enumerate(all_issues):
        issue.fix_order = i + 1

    # Group by file
    file_groups = group_by_file(all_issues)

    # Calculate summary statistics
    summary = calculate_summary(all_issues, file_groups)

    return {
        "ordered_issues": [issue.to_dict() for issue in all_issues],
        "grouped_by_file": [group.to_dict() for group in file_groups],
        "summary": summary
    }


def group_by_file(issues: list[PrioritizedIssue]) -> list[FileGroup]:
    """
    Group issues by file path for batch processing.

    This allows the LLM to fix multiple issues in a file at once,
    which is more efficient than opening/closing files repeatedly.
    """
    file_map = defaultdict(list)

    for issue in issues:
        file_map[issue.file].append(issue)
        issue.group_id = issue.file

    groups = []
    for file_path, file_issues in file_map.items():
        # Count related issues
        for issue in file_issues:
            issue.related_issues_count = len(file_issues) - 1

        # Find highest severity in group
        severity_priority = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
        highest = min(file_issues, key=lambda x: severity_priority.get(x.severity, 5))

        group = FileGroup(
            file_path=file_path,
            issues=sorted(file_issues, key=lambda x: x.start_line),
            total_priority_score=sum(i.priority_score for i in file_issues),
            highest_severity=highest.severity,
            issue_count=len(file_issues)
        )
        groups.append(group)

    # Sort groups by total priority (fix most critical files first)
    groups.sort(key=lambda g: (
        {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}.get(g.highest_severity, 5),
        -g.issue_count  # More issues = higher priority (batch fix)
    ))

    return groups


def calculate_summary(issues: list[PrioritizedIssue], groups: list[FileGroup]) -> dict:
    """Generate summary statistics for the prioritized findings."""
    if not issues:
        return {
            "total_issues": 0,
            "by_severity": {},
            "by_complexity": {},
            "files_affected": 0,
            "estimated_effort": "none",
            "recommended_approach": "No issues found - codebase is clean!"
        }

    # Count by severity
    severity_counts = defaultdict(int)
    for issue in issues:
        severity_counts[issue.severity] += 1

    # Count by complexity
    complexity_counts = defaultdict(int)
    complexity_names = {1: "trivial", 2: "easy", 3: "moderate", 4: "complex", 5: "very_complex"}
    for issue in issues:
        complexity_name = complexity_names.get(issue.complexity_score, "unknown")
        complexity_counts[complexity_name] += 1

    # Estimate total effort
    total_complexity = sum(i.complexity_score for i in issues)
    if total_complexity <= 5:
        effort = "minimal (< 30 minutes)"
    elif total_complexity <= 15:
        effort = "low (30 min - 2 hours)"
    elif total_complexity <= 40:
        effort = "moderate (2-4 hours)"
    elif total_complexity <= 80:
        effort = "significant (4-8 hours)"
    else:
        effort = "extensive (8+ hours)"

    # Generate recommended approach
    critical_count = severity_counts.get("critical", 0)
    high_count = severity_counts.get("high", 0)

    if critical_count > 0:
        approach = f"URGENT: Fix {critical_count} critical issue(s) immediately. "
        approach += "These represent severe security risks."
    elif high_count > 0:
        approach = f"HIGH PRIORITY: Address {high_count} high-severity issue(s) soon. "
        approach += "Consider fixing in the next sprint."
    else:
        approach = "No critical issues found. "
        approach += "Address medium/low issues during regular maintenance."

    return {
        "total_issues": len(issues),
        "by_severity": dict(severity_counts),
        "by_complexity": dict(complexity_counts),
        "files_affected": len(groups),
        "estimated_effort": effort,
        "recommended_approach": approach
    }


def print_summary(prioritized: dict) -> None:
    """Print a human-readable summary of prioritized findings (security only)."""
    summary = prioritized["summary"]

    print("\n" + "=" * 60)
    print("PRIORITIZED SECURITY FINDINGS")
    print("=" * 60)

    print(f"\nTotal Issues: {summary['total_issues']}")
    print(f"Files Affected: {summary['files_affected']}")
    print(f"Estimated Effort: {summary['estimated_effort']}")

    print("\nBy Severity:")
    for severity, count in summary.get("by_severity", {}).items():
        print(f"  {severity.upper():12} {count}")

    print("\nBy Complexity:")
    for complexity, count in summary.get("by_complexity", {}).items():
        print(f"  {complexity.capitalize():12} {count}")

    print(f"\nRecommendation: {summary['recommended_approach']}")

    print("\n" + "-" * 60)
    print("FIX ORDER (by priority):")
    print("-" * 60)

    for issue in prioritized["ordered_issues"][:10]:  # Show top 10
        print(f"\n#{issue['fix_order']} [{issue['severity'].upper()}] {issue['file']}:{issue['start_line']}")
        print(f"   Rule: {issue['rule_id']}")
        print(f"   Complexity: {issue['complexity']}")
        print(f"   Message: {issue['message'][:80]}...")

    if len(prioritized["ordered_issues"]) > 10:
        print(f"\n... and {len(prioritized['ordered_issues']) - 10} more issues")

    print("\n" + "-" * 60)
    print("FILES TO FIX (grouped):")
    print("-" * 60)

    for group in prioritized["grouped_by_file"][:5]:  # Show top 5 files
        print(f"\n{group['file_path']} ({group['issue_count']} issues)")
        print(f"   Highest Severity: {group['highest_severity'].upper()}")
        for issue in group["issues"][:3]:
            print(f"   - Line {issue['start_line']}: {issue['rule_id']}")
        if len(group["issues"]) > 3:
            print(f"   ... and {len(group['issues']) - 3} more")

    print("\n" + "=" * 60)


def print_unified_summary(prioritized: dict) -> None:
    """Print a human-readable summary of unified findings (security + tech debt)."""
    summary = prioritized["summary"]

    print("\n" + "=" * 70)
    print("  BACKEND JANITOR - UNIFIED PRIORITIZED FINDINGS")
    print("=" * 70)

    # Overview
    print(f"\nTotal Issues:      {summary['total_issues']}")
    print(f"  Security:        {summary.get('security_issues', 0)}")
    print(f"  Tech Debt:       {summary.get('tech_debt_issues', 0)}")
    print(f"Files Affected:    {summary['files_affected']}")
    print(f"Quick Wins:        {summary.get('quick_wins', 0)}")
    print(f"Estimated Effort:  {summary['estimated_effort']}")

    # By Type breakdown
    print("\n" + "-" * 40)
    print("BY TYPE")
    print("-" * 40)
    by_type = summary.get("by_type", {})
    print(f"  Security:    {by_type.get('security', 0)}")
    print(f"  Tech Debt:   {by_type.get('tech_debt', 0)}")

    # Tech debt categories
    by_category = summary.get("by_tech_debt_category", {})
    if by_category:
        print("\n  Tech Debt Breakdown:")
        for category, count in by_category.items():
            print(f"    {category.replace('_', ' ').title():20} {count}")

    # By Severity
    print("\n" + "-" * 40)
    print("BY SEVERITY")
    print("-" * 40)
    for severity, count in summary.get("by_severity", {}).items():
        print(f"  {severity.upper():12} {count}")

    # By Complexity
    print("\n" + "-" * 40)
    print("BY COMPLEXITY")
    print("-" * 40)
    for complexity, count in summary.get("by_complexity", {}).items():
        print(f"  {complexity.capitalize():12} {count}")

    print(f"\nRecommendation: {summary['recommended_approach']}")

    # Fix order
    print("\n" + "-" * 70)
    print("FIX ORDER (by priority):")
    print("-" * 70)

    for issue in prioritized["ordered_issues"][:15]:  # Show top 15
        issue_type_tag = "[SEC]" if issue.get("issue_type") == "security" else "[TDT]"
        category = ""
        if issue.get("tech_debt_category"):
            category = f" ({issue['tech_debt_category']})"

        print(f"\n#{issue['fix_order']} {issue_type_tag} [{issue['severity'].upper()}] {issue['file']}:{issue['start_line']}{category}")
        print(f"   Rule: {issue['rule_id']}")
        print(f"   Complexity: {issue['complexity']}")
        msg = issue['message'][:75] + "..." if len(issue['message']) > 75 else issue['message']
        print(f"   Message: {msg}")

        if issue.get("fix_available"):
            print(f"   Auto-fix: AVAILABLE")
        if issue.get("suggested_fix"):
            print(f"   Hint: {issue['suggested_fix'][:60]}...")

    if len(prioritized["ordered_issues"]) > 15:
        print(f"\n... and {len(prioritized['ordered_issues']) - 15} more issues")

    # Files to fix
    print("\n" + "-" * 70)
    print("FILES TO FIX (grouped):")
    print("-" * 70)

    for group in prioritized["grouped_by_file"][:5]:  # Show top 5 files
        print(f"\n{group['file_path']} ({group['issue_count']} issues)")
        print(f"   Highest Severity: {group['highest_severity'].upper()}")
        for issue in group["issues"][:3]:
            issue_type_tag = "[SEC]" if issue.get("issue_type") == "security" else "[TDT]"
            print(f"   - Line {issue['start_line']}: {issue_type_tag} {issue['rule_id']}")
        if len(group["issues"]) > 3:
            print(f"   ... and {len(group['issues']) - 3} more")

    print("\n" + "=" * 70)


def main():
    """CLI entry point for standalone usage."""
    if len(sys.argv) < 2:
        print("Usage: python prioritizer.py <security_findings.json>")
        print("       python prioritizer.py --stdin")
        print("       python prioritizer.py --unified --security <file> --ruff <file> --complexity <file>")
        print("")
        print("Security-only mode (original):")
        print("  python prioritizer.py scan_results.json")
        print("  python semgrep_scanner.py ./project | python prioritizer.py --stdin")
        print("")
        print("Unified mode (security + tech debt):")
        print("  python prioritizer.py --unified \\")
        print("      --security semgrep_results.json \\")
        print("      --ruff ruff_results.json \\")
        print("      --complexity complexity_results.json")
        print("")
        print("  Options:")
        print("    --mode <mode>   Priority mode: security_first, tech_debt_first, severity, quick_wins")
        print("    --json          Output JSON only (no human-readable summary)")
        sys.exit(1)

    # Check for unified mode
    if "--unified" in sys.argv:
        run_unified_mode()
    elif sys.argv[1] == "--stdin":
        # Read JSON from stdin (pipe from semgrep_scanner)
        try:
            findings = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
            sys.exit(1)

        # Run prioritization
        prioritized = prioritize(findings)
        print_summary(prioritized)
        print("\n\nJSON OUTPUT:")
        print(json.dumps(prioritized, indent=2))
    else:
        # Read from file
        try:
            with open(sys.argv[1], "r") as f:
                findings = json.load(f)
        except FileNotFoundError:
            print(f"Error: File not found: {sys.argv[1]}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in file: {e}", file=sys.stderr)
            sys.exit(1)

        # Run prioritization
        prioritized = prioritize(findings)
        print_summary(prioritized)
        print("\n\nJSON OUTPUT:")
        print(json.dumps(prioritized, indent=2))


def run_unified_mode():
    """Run the unified prioritizer with multiple input sources."""
    security_findings = None
    ruff_findings = None
    complexity_findings = None
    mode = "security_first"
    json_only = "--json" in sys.argv

    # Parse arguments
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]

        if arg == "--security" and i + 1 < len(args):
            try:
                with open(args[i + 1], "r") as f:
                    security_findings = json.load(f)
                print(f"Loaded security findings from: {args[i + 1]}")
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"Warning: Could not load security findings: {e}", file=sys.stderr)
            i += 2
            continue

        elif arg == "--ruff" and i + 1 < len(args):
            try:
                with open(args[i + 1], "r") as f:
                    ruff_findings = json.load(f)
                print(f"Loaded ruff findings from: {args[i + 1]}")
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"Warning: Could not load ruff findings: {e}", file=sys.stderr)
            i += 2
            continue

        elif arg == "--complexity" and i + 1 < len(args):
            try:
                with open(args[i + 1], "r") as f:
                    complexity_findings = json.load(f)
                print(f"Loaded complexity findings from: {args[i + 1]}")
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"Warning: Could not load complexity findings: {e}", file=sys.stderr)
            i += 2
            continue

        elif arg == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            if mode not in ["security_first", "tech_debt_first", "severity", "quick_wins"]:
                print(f"Warning: Unknown mode '{mode}', using 'security_first'", file=sys.stderr)
                mode = "security_first"
            i += 2
            continue

        i += 1

    # Check if we have at least one input
    if not any([security_findings, ruff_findings, complexity_findings]):
        print("Error: No input files provided. Use --security, --ruff, and/or --complexity", file=sys.stderr)
        sys.exit(1)

    # Run unified prioritization
    prioritized = prioritize_all(
        security_findings=security_findings,
        ruff_findings=ruff_findings,
        complexity_findings=complexity_findings,
        mode=mode,
    )

    # Output
    if json_only:
        print(json.dumps(prioritized, indent=2))
    else:
        print_unified_summary(prioritized)
        print("\n\nJSON OUTPUT:")
        print(json.dumps(prioritized, indent=2))


if __name__ == "__main__":
    main()
