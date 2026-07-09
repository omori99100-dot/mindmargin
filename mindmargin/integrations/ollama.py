"""Backward-compatible wrapper — delegates to OllamaProvider."""

from mindmargin.integrations.ollama_provider import OllamaProvider

OllamaClient = OllamaProvider

__all__ = ["OllamaClient"]
