"""
ContextShard: FSDP-style Distributed LLM Analysis for Large Codebases

This library enables analysis of codebases that exceed single LLM context windows
by distributing work across multiple LLM instances with synchronized understanding.

Usage:
    from contextshard import FSDPCoordinator

    coordinator = FSDPCoordinator(
        num_instances=4,
        model="deepseek-chat",
        sync_rounds=3,
    )

    result = await coordinator.analyze(
        codebase_path="./my-large-project",
        task="security_vulnerability_scan",
    )
"""

__version__ = "0.1.0"

from .coordinator import FSDPCoordinator, analyze_codebase
from .instance import LLMInstance
from .sync import SyncLayer
from .models.shard import CodeShard
from .models.context import ContextUpdate
from .models.result import ShardResult, UnifiedResult
from .llm import DeepSeekProvider, OpenAIProvider, get_provider

__all__ = [
    # Main API
    "FSDPCoordinator",
    "analyze_codebase",
    # Components
    "LLMInstance",
    "SyncLayer",
    # Models
    "CodeShard",
    "ContextUpdate",
    "ShardResult",
    "UnifiedResult",
    # LLM Providers
    "DeepSeekProvider",
    "OpenAIProvider",
    "get_provider",
]
