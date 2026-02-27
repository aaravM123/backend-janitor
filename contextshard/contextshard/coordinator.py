"""
FSDP Coordinator - Orchestrates distributed LLM analysis.

Like FSDP coordinates GPUs for distributed training, this coordinator:
- Shards the codebase
- Spawns LLM instances
- Runs sync rounds
- Merges final results
"""

import asyncio
import time
from typing import Any, Optional

from .bridge import get_bridge, CShardBridge
from .models.shard import CodeShard
from .models.context import ContextUpdate
from .models.result import ShardResult, UnifiedResult, CrossShardIssue
from .instance import LLMInstance
from .sync import SyncLayer


class FSDPCoordinator:
    """
    Coordinates multiple LLM instances for distributed codebase analysis.

    Like FSDP (Fully Sharded Data Parallel) for ML training:
    - Shards the codebase across instances
    - Each instance owns and deeply understands its shard
    - Sync rounds share context (like gradient all-reduce)
    - Final merge combines all understanding

    Usage:
        coordinator = FSDPCoordinator(
            num_instances=4,
            model="deepseek-chat",
            sync_rounds=3,
        )

        result = await coordinator.analyze(
            codebase_path="./my-project",
            task="security_vulnerability_scan",
        )
    """

    def __init__(
        self,
        num_instances: int = 4,
        model: str = "anthropic/claude-opus-4-6",
        sync_rounds: int = 3,
        max_tokens_per_shard: int = 100000,
        llm_client: Optional[Any] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        exclude_dirs: Optional[list[str]] = None,
    ):
        """
        Initialize the coordinator.

        Args:
            num_instances: Number of LLM instances to spawn
            model: Model to use (deepseek-chat, gpt-4, claude-3-opus, etc.)
            sync_rounds: Number of synchronization rounds
            max_tokens_per_shard: Maximum tokens per shard
            llm_client: Pre-configured LLM client (optional)
            api_key: API key for LLM provider (optional, uses env var if not set)
            base_url: Base URL for API (optional, for custom endpoints)
            exclude_dirs: List of directory names to exclude from indexing
        """
        self.num_instances = num_instances
        self.model = model
        self.sync_rounds = sync_rounds
        self.max_tokens_per_shard = max_tokens_per_shard
        self.exclude_dirs = exclude_dirs or []

        # Set up LLM client
        if llm_client:
            self.llm_client = llm_client
        else:
            self.llm_client = self._create_llm_client(api_key, base_url)

        # Will be populated during analysis
        self.instances: list[LLMInstance] = []
        self.shards: list[CodeShard] = []
        self.sync_layer: Optional[SyncLayer] = None
        self.bridge: CShardBridge = get_bridge()

    def _create_llm_client(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
    ) -> Any:
        """Create an OpenAI-compatible client."""
        import os

        # Try to import openai
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package required. Install with: pip install openai"
            )

        # Determine provider from model name
        model_lower = self.model.lower()
        if "deepseek" in model_lower:
            default_base = "https://api.deepseek.com"
            env_key = "DEEPSEEK_API_KEY"
        elif "/" in self.model or "openrouter" in model_lower:
            # OpenRouter models use vendor/model format (e.g. anthropic/claude-opus-4-6)
            default_base = "https://openrouter.ai/api/v1"
            env_key = "OPENROUTER_API_KEY"
        elif "gpt" in model_lower:
            default_base = "https://api.openai.com/v1"
            env_key = "OPENAI_API_KEY"
        else:
            default_base = "https://api.openai.com/v1"
            env_key = "OPENAI_API_KEY"

        return AsyncOpenAI(
            api_key=api_key or os.getenv(env_key),
            base_url=base_url or default_base,
        )

    async def analyze(
        self,
        codebase_path: str,
        task: str = "security_vulnerability_scan",
    ) -> UnifiedResult:
        """
        Main entry point - analyze a codebase using FSDP-style distribution.

        Args:
            codebase_path: Path to the codebase root
            task: Analysis task (e.g., "security_vulnerability_scan")

        Returns:
            UnifiedResult with all findings merged
        """
        start_time = time.time()

        # Step 1: Index and shard the codebase
        print(f"Indexing codebase: {codebase_path}")
        self.shards = await self._prepare_shards(codebase_path)
        print(f"Created {len(self.shards)} shards")

        # Step 2: Spawn LLM instances
        print(f"Spawning {len(self.shards)} LLM instances")
        self.instances = self._spawn_instances(self.shards, codebase_path)
        self.sync_layer = SyncLayer(self.instances)

        # Step 3: Run sync rounds
        all_results: list[list[ShardResult]] = []

        for round_num in range(self.sync_rounds):
            print(f"Running sync round {round_num + 1}/{self.sync_rounds}")

            # Each instance analyzes in parallel
            round_results = await self._parallel_analyze(round_num, task)
            all_results.append(round_results)

            # Sync: aggregate and broadcast context
            if round_num < self.sync_rounds - 1:  # Don't sync after last round
                context = await self.sync_layer.sync_round(round_results)
                print(f"  Synced {len(context.exports)} exports, {len(context.findings)} findings")

        # Step 4: Merge all results
        print("Merging results")
        result = self._merge_results(all_results)
        result.total_duration_ms = int((time.time() - start_time) * 1000)

        return result

    async def _prepare_shards(self, codebase_path: str) -> list[CodeShard]:
        """Index and shard the codebase using Go binary."""
        # Index
        index = self.bridge.index(codebase_path, exclude_dirs=self.exclude_dirs)

        # Calculate optimal number of shards
        total_tokens = index.get("total_tokens", 0)
        optimal_shards = max(
            self.num_instances,
            (total_tokens // self.max_tokens_per_shard) + 1
        )

        # Shard
        shards = self.bridge.shard(
            index,
            num_shards=optimal_shards,
            max_tokens=self.max_tokens_per_shard,
        )

        return shards

    def _spawn_instances(
        self,
        shards: list[CodeShard],
        codebase_path: str,
    ) -> list[LLMInstance]:
        """Create LLM instances, one per shard."""
        instances = []
        for i, shard in enumerate(shards):
            instance = LLMInstance(
                instance_id=i,
                shard=shard,
                llm_client=self.llm_client,
                model=self.model,
                codebase_root=codebase_path,
            )
            instances.append(instance)
        return instances

    async def _parallel_analyze(
        self,
        round_num: int,
        task: str,
    ) -> list[ShardResult]:
        """Run analysis on all instances in parallel."""
        tasks = [
            instance.analyze_round(round_num, task)
            for instance in self.instances
        ]
        results = await asyncio.gather(*tasks)
        return list(results)

    def _merge_results(
        self,
        all_results: list[list[ShardResult]],
    ) -> UnifiedResult:
        """Merge results from all rounds into unified result."""
        result = UnifiedResult(
            num_shards=len(self.shards),
            num_rounds=len(all_results),
        )

        # Collect all findings
        seen_findings = set()
        for round_results in all_results:
            for shard_result in round_results:
                for finding in shard_result.security_findings:
                    key = (finding.file, finding.line, finding.category)
                    if key not in seen_findings:
                        seen_findings.add(key)
                        result.findings.append(finding)

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        result.findings.sort(
            key=lambda f: severity_order.get(f.severity, 4)
        )

        # Identify cross-shard issues
        result.cross_shard_issues = self._identify_cross_shard_issues(all_results)

        # Calculate statistics
        result.total_files_analyzed = sum(len(s.files) for s in self.shards)
        result.total_tokens_processed = sum(s.token_count for s in self.shards)

        files_with_issues = set(f.file for f in result.findings)
        result.files_with_issues = list(files_with_issues)

        all_files = set()
        for shard in self.shards:
            for f in shard.files:
                all_files.add(f.path)
        result.clean_files = list(all_files - files_with_issues)

        # Per-shard summaries
        for shard in self.shards:
            result.shard_summaries.append({
                "id": shard.id,
                "files": len(shard.files),
                "tokens": shard.token_count,
                "findings": len([f for f in result.findings if f.shard_id == shard.id]),
            })

        return result

    def _identify_cross_shard_issues(
        self,
        all_results: list[list[ShardResult]],
    ) -> list[CrossShardIssue]:
        """Identify issues that span multiple shards."""
        cross_shard = []

        # Look for findings with cross_shard_context
        for round_results in all_results:
            for shard_result in round_results:
                for finding in shard_result.security_findings:
                    if finding.cross_shard_context:
                        cross_shard.append(CrossShardIssue(
                            title=f"{finding.category} in {finding.file}",
                            severity=finding.severity,
                            involved_shards=[shard_result.shard_id],  # TODO: Parse actual shards
                            attack_path=[finding.file],
                            description=finding.message,
                            recommendation=finding.suggested_fix or "Review and fix",
                        ))

        return cross_shard


# Convenience function for simple usage
async def analyze_codebase(
    path: str,
    task: str = "security_vulnerability_scan",
    num_instances: int = 4,
    model: str = "deepseek-chat",
) -> UnifiedResult:
    """
    Convenience function to analyze a codebase.

    Usage:
        result = await analyze_codebase("./my-project")
        print(result.summary())
    """
    coordinator = FSDPCoordinator(
        num_instances=num_instances,
        model=model,
    )
    return await coordinator.analyze(path, task)
