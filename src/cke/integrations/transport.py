"""Explicit network policy for transports carrying private code."""
import ipaddress
import os
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


def validate_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Provider URL must be HTTP(S), without embedded credentials')
    host = parsed.hostname
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == 'localhost'
    authorized = {item.strip().rstrip('/') for item in os.environ.get('CKE_ALLOWED_ENDPOINTS', '').split(',') if item.strip()}
    if not local and url.rstrip('/') not in authorized:
        raise ValueError('External provider blocked; authorize its exact URL with CKE_ALLOWED_ENDPOINTS')
    return url.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Provider redirects are disabled to protect source code')


def open_request(request, timeout=120):
    # Do not route private code through environment-configured HTTP proxies.
    try:
        return build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout)
    except HTTPError:
        raise
    except URLError as exc:
        endpoint = urlsplit(request.full_url)
        service = 'OpenAI' if endpoint.hostname == 'api.openai.com' else ('Ollama' if endpoint.path.startswith('/api/') else 'Qdrant')
        address = f'{endpoint.scheme}://{endpoint.netloc}'
        hint = {'OpenAI': 'Comprueba la conexión de red y acceso a api.openai.com.', 'Ollama': 'Instala Ollama desde https://ollama.com/download e inicia ollama serve.', 'Qdrant': 'Inicia Qdrant con docker compose up -d.'}[service]
        raise RuntimeError(f'No se pudo conectar con {service} en {address}. {hint} Ejecuta cke doctor para comprobar los servicios.') from exc
