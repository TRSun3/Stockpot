"""The LLM behind Stockpot: Google Gemini when configured with a key, a deterministic mock otherwise."""

from stockpot.config import Settings
from stockpot.llm.base import LLM, LLMError

__all__ = ["LLM", "LLMError", "get_llm"]


def get_llm(settings: Settings) -> LLM:
    if settings.backend == "gemini":
        from stockpot.llm.gemini import Gemini

        return Gemini(settings.gemini_api_key, settings.gemini_model)
    from stockpot.llm.mock import Mock

    return Mock()
