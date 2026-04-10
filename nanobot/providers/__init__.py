"""LLM provider abstraction module."""

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider"]


def __getattr__(name: str):
    if name == "LLMProvider":
        from nanobot.providers.base import LLMProvider

        return LLMProvider
    if name == "LLMResponse":
        from nanobot.providers.base import LLMResponse

        return LLMResponse
    if name == "LiteLLMProvider":
        from nanobot.providers.litellm_provider import LiteLLMProvider

        return LiteLLMProvider
    raise AttributeError(name)
