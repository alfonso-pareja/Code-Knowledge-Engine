"""Validated provider settings; credentials stay in environment variables."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import os
import re
from .config import home, ensure_home
from .utils import read_json, write_json
from .locking import exclusive

PROVIDERS = ('ollama', 'openai', 'copilot', 'chatgpt', 'codex')
AGENTS = ('copilot', 'chatgpt', 'codex')


@dataclass(frozen=True)
class ModelSettings:
    provider: str = 'ollama'
    model: str = 'llama3.2'
    embedding_provider: str = 'ollama'
    embedding_model: str = 'embeddinggemma'
    allow_cloud_code: bool = False

    @property
    def search_mode(self) -> str:
        return 'keyword' if self.embedding_provider == 'none' else 'hybrid'


def validate(settings: ModelSettings) -> ModelSettings:
    if settings.provider not in PROVIDERS:
        raise ValueError('Unsupported answer provider')
    if settings.embedding_provider not in ('none', 'ollama', 'openai'):
        raise ValueError('Embeddings require none, ollama or openai; agent subscriptions do not supply embeddings')
    if type(settings.allow_cloud_code) is not bool:
        raise ValueError('allow_cloud_code must be a boolean')
    for name in ('model', 'embedding_model'):
        value = getattr(settings, name)
        if not isinstance(value, str) or len(value) > 200 or (value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]*', value)):
            raise ValueError('Invalid model name')
    if settings.provider not in AGENTS and not settings.model.strip():
        raise ValueError('An answer model is required')
    if settings.embedding_provider != 'none' and not settings.embedding_model.strip():
        raise ValueError('An embedding model is required')
    return settings


def load_settings() -> ModelSettings:
    data = read_json(home() / 'settings.json')
    if data is None:
        return ModelSettings(embedding_model=os.environ.get('CKE_EMBEDDING_MODEL', 'embeddinggemma'))
    if not isinstance(data, dict) or set(data) - set(ModelSettings.__dataclass_fields__):
        raise ValueError('Invalid settings.json fields')
    return validate(ModelSettings(**data))


def configure(provider: str, model: str | None = None, embedding_provider: str | None = None,
              embedding_model: str | None = None, allow_cloud_code: bool = False) -> ModelSettings:
    if provider not in PROVIDERS:
        raise ValueError('Unsupported provider')
    embedding_provider = embedding_provider or ('none' if provider in AGENTS else provider)
    settings = validate(ModelSettings(
        provider=provider,
        model=model if model is not None else {'ollama': 'llama3.2', 'openai': 'gpt-4.1-mini'}.get(provider, ''),
        embedding_provider=embedding_provider,
        embedding_model=embedding_model if embedding_model is not None else {'ollama': 'embeddinggemma', 'openai': 'text-embedding-3-small', 'none': ''}.get(embedding_provider, ''),
        allow_cloud_code=allow_cloud_code,
    ))
    with exclusive('settings'):
        write_json(ensure_home() / 'settings.json', asdict(settings))
    return settings


def setup_instructions(settings: ModelSettings) -> list[str]:
    steps = []
    if settings.provider == 'ollama' or settings.embedding_provider == 'ollama':
        steps += ['Instala Ollama desde https://ollama.com/download y abre la aplicación o ejecuta: ollama serve']
        models = []
        if settings.provider == 'ollama':
            models.append(settings.model)
        if settings.embedding_provider == 'ollama':
            models.append(settings.embedding_model)
        steps += [f'ollama pull {model}' for model in dict.fromkeys(models)]
    if settings.provider == 'openai' or settings.embedding_provider == 'openai':
        steps += ['Define OPENAI_API_KEY en el entorno del proceso CKE; no la guardes en settings.json.',
                  'La API OpenAI tiene facturación independiente de ChatGPT.']
        if not settings.allow_cloud_code:
            steps += ['El envío a OpenAI está bloqueado. Autoriza explícitamente con --allow-cloud-code si tu política empresarial lo permite.']
        if settings.embedding_provider == 'openai':
            steps += ['Los embeddings OpenAI envían los chunks indexados a la nube; las respuestas envían el contexto recuperado.']
    if settings.provider in AGENTS:
        steps += ['El modelo se elige en el cliente/agente; CKE prepara evidencia y no usa esa suscripción como una API de generación.']
        if settings.provider == 'chatgpt':
            steps += ['Puedes copiar el campo context de cke ask en ChatGPT. Este servidor MCP es stdio: no se conecta directamente a ChatGPT web. Una integración remota requiere un transporte y autorización adicionales.']
        else:
            steps += ['Configura cke mcp serve como servidor stdio en tu cliente y define CKE_MCP_ALLOWED_KBS con las KB autorizadas.']
    if settings.embedding_provider == 'none':
        steps += ['Búsqueda keyword disponible con cke chunks; no necesitas Ollama, Qdrant ni cke index.']
    else:
        steps += ['Para búsqueda vectorial inicia Qdrant: docker compose up -d', 'Después ejecuta cke index --kb <kb>.']
    return steps


def settings_status() -> dict:
    settings = load_settings()
    return {**asdict(settings), 'search_mode': settings.search_mode,
            'api_key_configured': bool(os.environ.get('OPENAI_API_KEY')),
            'instructions': setup_instructions(settings)}
