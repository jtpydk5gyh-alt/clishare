import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import DomainError

MAX_RESPONSE = 32 * 1024 * 1024


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class Client:
    def __init__(self, url="http://127.0.0.1:8765", token=None):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise DomainError(400, "invalid_url", "Usa la URL base http(s) del coordinador, sin credenciales ni ruta.")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise DomainError(400, "https_required", "Los coordinadores remotos requieren HTTPS.")
        self.url = url.rstrip("/")
        self.token = token
        self.opener = build_opener(NoRedirects())

    def request(self, method, path, body=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(self.url + path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            with error:
                try:
                    payload = json.loads(error.read(1024 * 1024))
                    detail = payload["error"]
                    code, message = detail["code"], detail["message"]
                    if not isinstance(code, str) or not isinstance(message, str):
                        raise ValueError("invalid error")
                except (ValueError, KeyError, TypeError):
                    code, message = "http_error", f"El coordinador respondió HTTP {error.code}."
                raise DomainError(error.code, code, message) from None
        except (URLError, TimeoutError, OSError):
            raise DomainError(503, "coordinator_unavailable", "No se pudo conectar al coordinador. Comprueba clishare serve y CLISHARE_URL.") from None
        with response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise DomainError(502, "response_too_large", "La respuesta supera 32 MiB; usa páginas más pequeñas.")
            try:
                payload = json.loads(raw)
                return payload["data"]
            except (ValueError, KeyError, TypeError):
                raise DomainError(502, "invalid_response", "El coordinador devolvió una respuesta JSON inválida.") from None
