"""
Sync Layer - All-reduce style synchronization between LLM instances.

Like FSDP's gradient all-reduce, this layer:
- Collects discoveries from all instances
- Aggregates and deduplicates
- Broadcasts combined context to all instances
"""

from typing import TYPE_CHECKING
from .models.context import ContextUpdate, Export, Dependency, Finding
from .models.result import ShardResult

if TYPE_CHECKING:
    from .instance import LLMInstance


class SyncLayer:
    """
    Handles all-reduce style synchronization between LLM instances.

    Like FSDP's gradient synchronization:
    - Gather: Collect results from all instances
    - Reduce: Aggregate into unified context
    - Broadcast: Send to all instances
    """

    def __init__(self, instances: list["LLMInstance"]):
        self.instances = instances
        self.round_num = 0

    async def sync_round(
        self,
        results: list[ShardResult],
        round_type: str = "full",
    ) -> ContextUpdate:
        """
        Synchronize context between all instances.

        Args:
            results: Results from each instance's analysis
            round_type: Type of sync ("discovery", "dependencies", "findings", "full")

        Returns:
            Aggregated ContextUpdate that was broadcast
        """
        self.round_num += 1

        # Gather phase: collect from all instances
        context = self._all_gather(results)

        # Reduce phase: aggregate and deduplicate
        context.deduplicate()

        # Broadcast phase: send to all instances
        await self._broadcast(context)

        return context

    def _all_gather(self, results: list[ShardResult]) -> ContextUpdate:
        """
        Gather results from all instances into a single ContextUpdate.

        Like all-gather in distributed computing.
        """
        context = ContextUpdate(round_num=self.round_num)

        for result in results:
            # Collect exports
            context.exports.extend(result.discovered_exports)

            # Collect dependencies
            context.dependencies.extend(result.discovered_dependencies)

            # Collect findings
            context.findings.extend(result.security_findings)
            context.findings.extend(result.quality_findings)

            # Collect questions
            for q in result.questions_for_others:
                from .models.context import Question
                context.questions.append(Question(
                    from_shard=result.shard_id,
                    to_shard=q.get("to_shard", -1),
                    question=q.get("question", ""),
                    context=q.get("context", ""),
                ))

        return context

    async def _broadcast(self, context: ContextUpdate):
        """
        Broadcast aggregated context to all instances.

        Each instance receives context from all OTHER instances
        (not its own discoveries - it already knows those).
        """
        for instance in self.instances:
            # Filter out this instance's own contributions
            filtered_context = self._filter_for_instance(context, instance.id)
            instance.receive_context(filtered_context)

    def _filter_for_instance(
        self,
        context: ContextUpdate,
        instance_id: int,
    ) -> ContextUpdate:
        """
        Filter context to exclude an instance's own contributions.

        Each instance only needs to know about OTHER instances.
        """
        return ContextUpdate(
            round_num=context.round_num,
            exports=[e for e in context.exports if e.shard_id != instance_id],
            dependencies=[d for d in context.dependencies if d.from_shard != instance_id],
            findings=[f for f in context.findings if f.shard_id != instance_id],
            questions=[q for q in context.questions if q.to_shard == instance_id],
        )

    def get_cross_shard_findings(self, all_results: list[ShardResult]) -> list[Finding]:
        """
        Identify findings that involve multiple shards.

        These are the most valuable discoveries.
        """
        cross_shard = []

        for result in all_results:
            for finding in result.security_findings:
                if finding.cross_shard_context:
                    cross_shard.append(finding)

        return cross_shard

    def build_attack_paths(
        self,
        all_results: list[ShardResult],
        context: ContextUpdate,
    ) -> list[dict]:
        """
        Build attack paths from findings and dependencies.

        An attack path traces how an attacker could exploit
        vulnerabilities across multiple shards.
        """
        attack_paths = []

        # Build dependency graph
        dep_graph = {}
        for dep in context.dependencies:
            if dep.from_file not in dep_graph:
                dep_graph[dep.from_file] = []
            dep_graph[dep.from_file].append((dep.to_file, dep.symbol))

        # Find entry points (files with vulnerabilities)
        vuln_files = set()
        for result in all_results:
            for finding in result.security_findings:
                if finding.severity in ["critical", "high"]:
                    vuln_files.add(finding.file)

        # Trace paths from entry points
        for entry in vuln_files:
            path = self._trace_path(entry, dep_graph, set())
            if len(path) > 1:
                attack_paths.append({
                    "entry_point": entry,
                    "path": path,
                    "length": len(path),
                })

        return attack_paths

    def _trace_path(
        self,
        file: str,
        dep_graph: dict,
        visited: set,
    ) -> list[str]:
        """Trace a dependency path from a file."""
        if file in visited:
            return []

        visited.add(file)
        path = [file]

        if file in dep_graph:
            for dep_file, _ in dep_graph[file]:
                sub_path = self._trace_path(dep_file, dep_graph, visited)
                if sub_path:
                    path.extend(sub_path)
                    break  # Take first path for simplicity

        return path
