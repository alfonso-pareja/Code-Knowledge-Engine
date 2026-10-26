"""Check only configured dependencies; never send code or credentials to cloud probes."""
import json
import shutil
import sqlite3
import sys
from urllib.request import Request
from .config import home
from .settings import load_settings, settings_status
from .integrations.ollama import OllamaClient
from .integrations.transport import open_request
from .providers import vector_client


def doctor() -> dict:
    settings = load_settings()
    checks = {'home': str(home()), 'git': shutil.which('git'), 'python': sys.version.split()[0],
              'sqlite': sqlite3.sqlite_version, 'configuration': settings_status()}
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('CREATE VIRTUAL TABLE probe USING fts5(body)')
        checks['fts5'] = True
    except sqlite3.Error:
        checks['fts5'] = False
    finally:
        connection.close()
    needs_ollama = settings.provider == 'ollama' or settings.embedding_provider == 'ollama'
    checks['ollama'] = {'required': needs_ollama}
    if needs_ollama:
        try:
            client = OllamaClient()
            with open_request(Request(client.url + '/api/tags'), timeout=3) as response:
                payload = json.load(response)
            installed = {model['name'].removesuffix(':latest') for model in payload.get('models', [])}
            required = set()
            if settings.provider == 'ollama':
                required.add(settings.model)
            if settings.embedding_provider == 'ollama':
                required.add(settings.embedding_model)
            missing = sorted(model for model in required if model.removesuffix(':latest') not in installed)
            checks['ollama'].update(available=True, missing_models=missing,
                                    instructions=[f'ollama pull {model}' for model in missing])
        except Exception as error:
            checks['ollama'].update(available=False, reason=str(error),
                                    instructions=['Instala Ollama desde https://ollama.com/download', 'ollama serve'])
    checks['qdrant'] = {'required': settings.embedding_provider != 'none'}
    if settings.embedding_provider != 'none':
        try:
            client = vector_client()
            with open_request(Request(client.url + '/collections'), timeout=3) as response:
                json.load(response)
            checks['qdrant'].update(available=True, collection=client.collection)
        except Exception as error:
            checks['qdrant'].update(available=False, reason=str(error), instructions=['docker compose up -d'])
    if settings.provider == 'openai' or settings.embedding_provider == 'openai':
        checks['openai'] = {'credentials_present': checks['configuration']['api_key_configured'],
                            'code_transfer_authorized': settings.allow_cloud_code,
                            'connectivity': 'not_checked', 'note': 'No se llama a la nube durante doctor.'}
    return checks
