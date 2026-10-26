"""Resolve configured providers without coupling domain services to a vendor."""
import os
from .settings import AGENTS, load_settings
from .config import home
from .utils import digest
from .integrations.ollama import OllamaClient
from .integrations.openai import OpenAIClient
from .integrations.qdrant import QdrantClient


def embedding_client():
    settings = load_settings()
    if settings.embedding_provider == 'none':
        raise ValueError('Embeddings desactivados. Usa --mode keyword o configura --embedding-provider ollama/openai.')
    if settings.embedding_provider == 'openai':
        return OpenAIClient(settings.embedding_model, settings.allow_cloud_code)
    return OllamaClient(settings.embedding_model)


def answer_client():
    settings = load_settings()
    if settings.provider in AGENTS:
        return None
    if settings.provider == 'openai':
        return OpenAIClient(settings.model, settings.allow_cloud_code)
    return OllamaClient(settings.model)


def vector_client():
    settings = load_settings()
    collection = os.environ.get('CKE_COLLECTION')
    if collection is None and (home() / 'settings.json').exists():
        collection = 'cke_' + settings.embedding_provider + '_' + digest(settings.embedding_model)[:12]
    return QdrantClient(collection=collection)
