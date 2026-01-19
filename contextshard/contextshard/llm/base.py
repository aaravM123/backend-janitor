"""
Base LLM Provider interface.

All LLM providers must implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Response from an LLM call."""
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    finish_reason: str


@dataclass
class Message:
    """A message in a conversation."""
    role: str  # "system", "user", "assistant"
    content: str


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All providers (DeepSeek, OpenAI, Anthropic, etc.) implement this interface.
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    async def chat(self, messages: list[Message]) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of messages in the conversation

        Returns:
            LLMResponse with the model's response
        """
        pass

    @abstractmethod
    async def stream_chat(self, messages: list[Message]):
        """
        Stream a chat completion response.

        Args:
            messages: List of messages in the conversation

        Yields:
            Chunks of the response as they arrive
        """
        pass

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Return the model's context window size in tokens."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'deepseek', 'openai')."""
        pass
