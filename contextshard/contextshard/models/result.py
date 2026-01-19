"""
Data models for analysis results.
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from .context import Finding, Export, Dependency


@dataclass
class ShardResult:
    """Result from analyzing a single shard in one round."""
    shard_id: int
    round_num: int

    # Discoveries
    discovered_exports: list[Export] = field(default_factory=list)
    discovered_dependencies: list[Dependency] = field(default_factory=list)

    # Findings
    security_findings: list[Finding] = field(default_factory=list)
    quality_findings: list[Finding] = field(default_factory=list)

    # Questions for other shards
    questions_for_others: list[dict] = field(default_factory=list)

    # Answers to questions from other shards
    answers: list[dict] = field(default_factory=list)

    # Raw LLM response (for debugging)
    raw_response: Optional[str] = None

    # Metrics
    tokens_used: int = 0
    duration_ms: int = 0


@dataclass
class CrossShardIssue:
    """
    An issue that spans multiple shards.

    These are the most valuable findings - attack paths or problems
    that only become visible when understanding multiple parts of the code.
    """
    title: str
    severity: str
    involved_shards: list[int]
    attack_path: list[str]  # Step-by-step path through the code
    description: str
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "severity": self.severity,
            "involved_shards": self.involved_shards,
            "attack_path": self.attack_path,
            "description": self.description,
            "recommendation": self.recommendation,
        }


@dataclass
class UnifiedResult:
    """
    Final merged result from all shards and all rounds.

    This is like the final model checkpoint in FSDP - the combined
    understanding from all distributed workers.
    """
    # All findings, deduplicated and sorted by severity
    findings: list[Finding] = field(default_factory=list)

    # Cross-shard issues (the valuable discoveries)
    cross_shard_issues: list[CrossShardIssue] = field(default_factory=list)

    # Statistics
    total_files_analyzed: int = 0
    total_tokens_processed: int = 0
    num_shards: int = 0
    num_rounds: int = 0

    # Coverage
    files_with_issues: list[str] = field(default_factory=list)
    clean_files: list[str] = field(default_factory=list)

    # Per-shard summaries
    shard_summaries: list[dict] = field(default_factory=list)

    # Timing
    total_duration_ms: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "findings": [
                {
                    "shard_id": f.shard_id,
                    "file": f.file,
                    "line": f.line,
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "code_snippet": f.code_snippet,
                    "suggested_fix": f.suggested_fix,
                    "cross_shard_context": f.cross_shard_context,
                }
                for f in self.findings
            ],
            "cross_shard_issues": [i.to_dict() for i in self.cross_shard_issues],
            "statistics": {
                "total_files_analyzed": self.total_files_analyzed,
                "total_tokens_processed": self.total_tokens_processed,
                "num_shards": self.num_shards,
                "num_rounds": self.num_rounds,
                "files_with_issues": len(self.files_with_issues),
                "clean_files": len(self.clean_files),
                "total_duration_ms": self.total_duration_ms,
            },
            "shard_summaries": self.shard_summaries,
        }

    def summary(self) -> str:
        """Generate a human-readable summary."""
        by_severity = {}
        for f in self.findings:
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

        lines = [
            "=" * 60,
            "CONTEXTSHARD ANALYSIS RESULTS",
            "=" * 60,
            "",
            f"Files analyzed: {self.total_files_analyzed}",
            f"Shards: {self.num_shards}",
            f"Sync rounds: {self.num_rounds}",
            f"Duration: {self.total_duration_ms}ms",
            "",
            "FINDINGS BY SEVERITY:",
        ]

        for sev in ["critical", "high", "medium", "low"]:
            count = by_severity.get(sev, 0)
            if count > 0:
                lines.append(f"  {sev.upper()}: {count}")

        if self.cross_shard_issues:
            lines.append("")
            lines.append(f"CROSS-SHARD ISSUES: {len(self.cross_shard_issues)}")
            for issue in self.cross_shard_issues[:5]:
                lines.append(f"  [{issue.severity.upper()}] {issue.title}")
                lines.append(f"    Shards involved: {issue.involved_shards}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)
