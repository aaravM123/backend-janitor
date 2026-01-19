"""
OpenAI LLM Provider.

Supports GPT-4, GPT-4o, GPT-3.5, and other OpenAI models.
"""

import os
from typing import Optional, AsyncIterator

from .base import BaseLLMProvider, LLMResponse, Message


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI LLM provider.

    Supports:
    - gpt-4o (128k context)
    - gpt-4-turbo (128k context)
    - gpt-4 (8k context)
    - gpt-3.5-turbo (16k context)
    """

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    ENV_KEY = "OPENAI_API_KEY"

    # Context windows for different models
    CONTEXT_WINDOWS = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4-turbo-preview": 128000,
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
        "gpt-3.5-turbo": 16385,
        "gpt-3.5-turbo-16k": 16385,
    }

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ):
        super().__init__(model, api_key, base_url, temperature, max_tokens)

        # Get API key from env if not provided
        self.api_key = api_key or os.getenv(self.ENV_KEY)
        if not self.api_key:
            raise ValueError(
                f"OpenAI API key required. Set {self.ENV_KEY} environment variable "
                "or pass api_key parameter."
            )

        self.base_url = base_url or self.DEFAULT_BASE_URL

        # Initialize client
        self._client = None

    async def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise ImportError(
                    "openai package required for OpenAI provider. "
                    "Install with: pip install openai"
                )

            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    async def chat(self, messages: list[Message]) -> LLMResponse:
        """
        Send a chat completion request to OpenAI.

        Args:
            messages: List of messages in the conversation

        Returns:
            LLMResponse with the model's response
        """
        client = await self._get_client()

        # Convert to API format
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        response = await client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            finish_reason=choice.finish_reason or "unknown",
        )

    async def stream_chat(self, messages: list[Message]) -> AsyncIterator[str]:
        """
        Stream a chat completion response from OpenAI.

        Args:
            messages: List of messages in the conversation

        Yields:
            Chunks of the response as they arrive
        """
        client = await self._get_client()

        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        stream = await client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @property
    def context_window(self) -> int:
        """Return OpenAI model's context window size."""
        return self.CONTEXT_WINDOWS.get(self.model, 128000)

    @property
    def provider_name(self) -> str:
        """Return provider name."""
        return "openai"
