"""
LLM Instance - A worker that owns and analyzes a code shard.

Like a GPU in FSDP that owns a parameter shard, each LLMInstance
owns a CodeShard and builds deep understanding of it across rounds.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Any

from .models.shard import CodeShard
from .models.context import ContextUpdate, Export, Dependency, Finding
from .models.result import ShardResult


@dataclass
class Message:
    """A message in the conversation history."""
    role: str  # "system", "user", "assistant"
    content: str


class LLMInstance:
    """
    One LLM instance that owns and deeply understands one shard.

    Like one GPU in FSDP that owns a parameter shard, this instance:
    - Owns a specific shard of the codebase
    - Maintains conversation history (persistent context)
    - Receives context updates from other instances
    - Reports its discoveries for sync rounds
    """

    def __init__(
        self,
        instance_id: int,
        shard: CodeShard,
        llm_client: Any,
        model: str = "anthropic/claude-opus-4-6",
        codebase_root: str = ".",
    ):
        self.id = instance_id
        self.shard = shard
        self.llm_client = llm_client
        self.model = model
        self.codebase_root = codebase_root

        # Conversation history (maintains context across rounds)
        self.conversation_history: list[Message] = []

        # Context received from other instances
        self.context_from_others: list[ContextUpdate] = []

        # Initialize with system prompt
        self._init_system_prompt()

    def _init_system_prompt(self):
        """Set up the initial system prompt with shard info."""
        # Handle None values from Go bridge
        external_deps = self.shard.external_deps or []
        exported_to = self.shard.exported_to or []

        system_prompt = f"""You are LLM Instance {self.id} in a distributed codebase analysis system.

You OWN and deeply understand Shard {self.shard.id} of the codebase.

YOUR SHARD CONTAINS:
{self.shard.file_list()}

Total tokens in your shard: {self.shard.token_count}
Files depending on other shards: {len(external_deps)}
Other shards depending on you: {exported_to}

Your job is to:
1. Read EVERY line of code in your shard - do not skim
2. Report exports (functions, classes other shards use)
3. Report what you import from outside
4. Hunt for CRASH BUGS: unhandled exceptions, None/null access, missing error handling on I/O and parsing, resource leaks, infinite loops, index out-of-bounds, race conditions, division by zero, unchecked return values
5. Find security vulnerabilities: injection, auth bypass, data exposure
6. Find cross-shard issues that span multiple shards

Think adversarially: for every function, ask "what input breaks this?"
Trace error propagation - where do exceptions go unhandled across files?

Always respond in a structured format that can be parsed."""

        self.conversation_history.append(Message(role="system", content=system_prompt))

        # Add the actual code content
        contents = self.shard.get_content(self.codebase_root)
        code_prompt = "Here is the code in your shard:\n\n"
        for path, content in contents.items():
            # Truncate very large files
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            code_prompt += f"=== {path} ===\n{content}\n\n"

        self.conversation_history.append(Message(role="user", content=code_prompt))

    async def analyze_round(self, round_num: int, task: str) -> ShardResult:
        """
        Perform one round of analysis on our shard.

        Args:
            round_num: Which sync round (0 = discovery, 1+ = with cross-context)
            task: The analysis task (e.g., "security_vulnerability_scan")

        Returns:
            ShardResult with discoveries and findings
        """
        start_time = time.time()

        # Build prompt based on round
        if round_num == 0:
            prompt = self._build_discovery_prompt()
        else:
            prompt = self._build_analysis_prompt(task)

        # Add to conversation
        self.conversation_history.append(Message(role="user", content=prompt))

        # Call LLM
        response = await self._call_llm()

        # Add response to history
        self.conversation_history.append(Message(role="assistant", content=response))

        # Parse response into structured result
        result = self._parse_response(response, round_num)
        result.duration_ms = int((time.time() - start_time) * 1000)

        return result

    def _build_discovery_prompt(self) -> str:
        """Build prompt for round 0: discover what's in our shard."""
        return """ROUND 0: DISCOVERY

Analyze every function and code path in your shard. Report:

1. EXPORTS - Functions, classes, and variables your shard exports
   Format: EXPORT: <type> <name> in <file> - <brief description>

2. IMPORTS - What your shard needs from outside
   Format: IMPORT: <name> from <module> - <how it's used>

3. INITIAL_FINDINGS - Bugs, crash risks, and vulnerabilities
   Format: FINDING: [SEVERITY] <category> in <file>:<line> - <description>
   Look hard for: missing error handling, unguarded None access, unchecked
   I/O operations, resource leaks, unsafe parsing, and unvalidated inputs

Be thorough - read every line. Other instances will receive your exports."""

    def _build_analysis_prompt(self, task: str) -> str:
        """Build prompt for analysis rounds with cross-shard context."""
        context_str = self._format_cross_shard_context()

        return f"""ROUND: DEEP ANALYSIS WITH CROSS-SHARD CONTEXT

TASK: {task}

CONTEXT FROM OTHER SHARDS:
{context_str}

For every function in YOUR code, ask: what input crashes this? Then report:

1. CRASH_AND_SECURITY_FINDINGS - Bugs that cause crashes or security holes
   Format: SECURITY: [SEVERITY] <category> in <file>:<line>
   Description: <what's wrong and what input triggers it>
   Cross-shard context: <if this involves other shards, explain>
   Suggested fix: <how to fix>
   Categories: unhandled_exception, null_access, resource_leak, race_condition,
   infinite_loop, index_oob, missing_validation, unchecked_io, injection, auth_bypass

2. CROSS_SHARD_CRASH_PATHS - Crash/failure paths spanning multiple shards
   Format: CROSS_SHARD: [SEVERITY] <title>
   Shards involved: <list of shard IDs>
   Crash path: <step by step how this leads to a crash or data corruption>
   Description: <detailed explanation>

3. QUESTIONS - Things you need to know from other shards
   Format: QUESTION for shard <N>: <question>
   Context: <why you're asking>

Focus on HARD-TO-FIND bugs: error propagation across files, edge cases in parsing/I/O, missing cleanup, and crashes under unusual or adversarial inputs."""

    def _format_cross_shard_context(self) -> str:
        """Format context received from other instances."""
        if not self.context_from_others:
            return "No context received yet from other shards."

        parts = []
        for ctx in self.context_from_others:
            parts.append(ctx.to_prompt())

        return "\n\n".join(parts)

    async def _call_llm(self) -> str:
        """Call the LLM with our conversation history."""
        # Format messages for the API
        messages = [
            {"role": m.role, "content": m.content}
            for m in self.conversation_history
        ]

        # Call the LLM (works with OpenAI-compatible APIs)
        response = await self.llm_client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,  # Low temperature for consistent analysis
            max_tokens=8000,
        )

        return response.choices[0].message.content

    def _parse_response(self, response: str, round_num: int) -> ShardResult:
        """Parse LLM response into structured ShardResult."""
        result = ShardResult(
            shard_id=self.id,
            round_num=round_num,
            raw_response=response,
        )

        # Parse exports
        for line in response.split("\n"):
            line = line.strip()

            if line.startswith("EXPORT:"):
                export = self._parse_export(line)
                if export:
                    result.discovered_exports.append(export)

            elif line.startswith("FINDING:") or line.startswith("SECURITY:"):
                finding = self._parse_finding(line)
                if finding:
                    result.security_findings.append(finding)

            elif line.startswith("QUESTION"):
                question = self._parse_question(line)
                if question:
                    result.questions_for_others.append(question)

        return result

    def _parse_export(self, line: str) -> Optional[Export]:
        """Parse an EXPORT line."""
        try:
            # EXPORT: function login in auth/login.py - Handles user login
            parts = line[7:].strip()  # Remove "EXPORT:"
            words = parts.split()
            if len(words) >= 4:
                return Export(
                    name=words[1],
                    type=words[0],
                    file=words[3] if words[2] == "in" else "",
                    shard_id=self.id,
                )
        except Exception:
            pass
        return None

    def _parse_finding(self, line: str) -> Optional[Finding]:
        """Parse a FINDING or SECURITY line."""
        try:
            # FINDING: [HIGH] sql_injection in api/users.py:42 - SQL injection
            if "[" in line and "]" in line:
                severity_start = line.index("[") + 1
                severity_end = line.index("]")
                severity = line[severity_start:severity_end].lower()

                rest = line[severity_end + 1:].strip()
                parts = rest.split(" in ")
                if len(parts) >= 2:
                    category = parts[0].strip()
                    location = parts[1].split(" - ")[0].strip()
                    message = parts[1].split(" - ")[1] if " - " in parts[1] else ""

                    file_line = location.split(":")
                    file = file_line[0]
                    line_num = int(file_line[1]) if len(file_line) > 1 else 0

                    return Finding(
                        shard_id=self.id,
                        file=file,
                        line=line_num,
                        severity=severity,
                        category=category,
                        message=message,
                        code_snippet="",
                    )
        except Exception:
            pass
        return None

    def _parse_question(self, line: str) -> Optional[dict]:
        """Parse a QUESTION line."""
        try:
            # QUESTION for shard 2: Does query() sanitize input?
            if "for shard" in line:
                shard_num = int(line.split("shard")[1].split(":")[0].strip())
                question = line.split(":")[1].strip() if ":" in line else ""
                return {
                    "to_shard": shard_num,
                    "question": question,
                    "from_shard": self.id,
                }
        except Exception:
            pass
        return None

    def receive_context(self, update: ContextUpdate):
        """
        Receive context from other instances.

        This is called during sync rounds to share discoveries.
        """
        self.context_from_others.append(update)

        # Also add to conversation history so LLM knows
        self.conversation_history.append(Message(
            role="system",
            content=f"UPDATE FROM OTHER SHARDS (Round {update.round_num}):\n{update.to_prompt()}"
        ))

    def get_exports(self) -> list[Export]:
        """Get exports discovered so far."""
        # Extract from conversation history or cache
        exports = []
        for msg in self.conversation_history:
            if msg.role == "assistant":
                for line in msg.content.split("\n"):
                    if line.strip().startswith("EXPORT:"):
                        export = self._parse_export(line.strip())
                        if export:
                            exports.append(export)
        return exports
