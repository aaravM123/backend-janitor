"""
Data models for context synchronization between LLM instances.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Export:
    """An exported symbol from a shard."""
    name: str
    type: str  # "function", "class", "variable"
    file: str
    shard_id: int
    signature: Optional[str] = None  # e.g., "def login(username: str, password: str) -> User"


@dataclass
class Dependency:
    """A dependency between files/shards."""
    from_file: str
    from_shard: int
    to_file: str
    to_shard: int
    symbol: str  # What symbol is being used


@dataclass
class Finding:
    """A security or quality finding from analysis."""
    shard_id: int
    file: str
    line: int
    severity: str  # "critical", "high", "medium", "low"
    category: str  # "sql_injection", "xss", "hardcoded_secret", etc.
    message: str
    code_snippet: str
    suggested_fix: Optional[str] = None
    cross_shard_context: Optional[str] = None  # If this finding involves other shards


@dataclass
class Question:
    """A question one shard has for another."""
    from_shard: int
    to_shard: int
    question: str
    context: str
    answered: bool = False
    answer: Optional[str] = None


@dataclass
class ContextUpdate:
    """
    Context update shared between LLM instances during sync rounds.

    This is the "gradient" equivalent in FSDP - information that gets
    aggregated and broadcast to all instances.
    """
    round_num: int = 0
    exports: list[Export] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def to_prompt(self) -> str:
        """Convert context update to a prompt string for LLM."""
        parts = []

        if self.exports:
            parts.append("=== EXPORTS FROM OTHER SHARDS ===")
            for exp in self.exports[:50]:  # Limit to avoid token explosion
                sig = f" - {exp.signature}" if exp.signature else ""
                parts.append(f"Shard {exp.shard_id}: {exp.type} {exp.name}{sig} (in {exp.file})")

        if self.dependencies:
            parts.append("\n=== CROSS-SHARD DEPENDENCIES ===")
            for dep in self.dependencies[:30]:
                parts.append(
                    f"{dep.from_file} (shard {dep.from_shard}) "
                    f"uses {dep.symbol} from {dep.to_file} (shard {dep.to_shard})"
                )

        if self.findings:
            parts.append("\n=== FINDINGS FROM OTHER SHARDS ===")
            for f in self.findings[:20]:
                parts.append(
                    f"[{f.severity.upper()}] Shard {f.shard_id}: {f.category} in {f.file}:{f.line}"
                )
                parts.append(f"  {f.message}")

        if self.questions:
            unanswered = [q for q in self.questions if not q.answered]
            if unanswered:
                parts.append("\n=== QUESTIONS FOR YOU ===")
                for q in unanswered[:10]:
                    parts.append(f"From Shard {q.from_shard}: {q.question}")
                    parts.append(f"  Context: {q.context[:200]}...")

        return "\n".join(parts)

    def merge_with(self, other: "ContextUpdate") -> "ContextUpdate":
        """Merge another context update into this one."""
        return ContextUpdate(
            round_num=max(self.round_num, other.round_num),
            exports=self.exports + other.exports,
            dependencies=self.dependencies + other.dependencies,
            findings=self.findings + other.findings,
            questions=self.questions + other.questions,
        )

    def deduplicate(self) -> None:
        """Remove duplicate entries."""
        # Dedupe exports by (name, shard_id)
        seen_exports = set()
        unique_exports = []
        for exp in self.exports:
            key = (exp.name, exp.shard_id)
            if key not in seen_exports:
                seen_exports.add(key)
                unique_exports.append(exp)
        self.exports = unique_exports

        # Dedupe findings by (file, line, category)
        seen_findings = set()
        unique_findings = []
        for f in self.findings:
            key = (f.file, f.line, f.category)
            if key not in seen_findings:
                seen_findings.add(key)
                unique_findings.append(f)
        self.findings = unique_findings
