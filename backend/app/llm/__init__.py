from .base import ModelProvider
from .schemas import GenerationRequest, Message, ModelSelection, ProviderConfig, ProviderError
from .openai_provider import OpenAIProvider
from .ollama_provider import OllamaProvider


def create_provider(config):
    return {"openai": OpenAIProvider, "ollama": OllamaProvider}[config.kind](config)
