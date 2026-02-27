"""
LLM Providers for ContextShard.

Provides a unified interface for different LLM providers.
"""

from .base import BaseLLMProvider, LLMResponse, Message
from .deepseek import DeepSeekProvider
from .openai_provider import OpenAIProvider

__all__ = [
    "BaseLLMProvider",
    "LLMResponse",
    "Message",
    "DeepSeekProvider",
    "OpenAIProvider",
    "get_provider",
]


def get_provider(
    model: str,
    api_key: str = None,
    base_url: str = None,
    **kwargs,
) -> BaseLLMProvider:
    """
    Factory function to get the appropriate LLM provider.

    Args:
        model: Model name (e.g., "deepseek-chat", "gpt-4o")
        api_key: Optional API key (uses env var if not provided)
        base_url: Optional custom base URL
        **kwargs: Additional provider-specific options

    Returns:
        Configured LLM provider instance

    Example:
        provider = get_provider("deepseek-chat")
        response = await provider.chat(messages)
    """
    model_lower = model.lower()

    if "deepseek" in model_lower:
        return DeepSeekProvider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
    elif "/" in model or "openrouter" in model_lower:
        # OpenRouter models use vendor/model format (e.g. anthropic/claude-opus-4-6)
        import os
        return OpenAIProvider(
            model=model,
            api_key=api_key or os.getenv("OPENROUTER_API_KEY"),
            base_url=base_url or "https://openrouter.ai/api/v1",
            **kwargs,
        )
    elif "gpt" in model_lower:
        return OpenAIProvider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
    else:
        # Default to OpenAI-compatible provider
        return OpenAIProvider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
