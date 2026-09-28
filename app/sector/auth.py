"""Identidade de quem usa o planeamento, dada pelo Caddy (Passo 3 do plano de 28/09/2026).

O Caddy autentica cada pessoa (utilizador e palavra-passe), apaga os cabeçalhos X-Auth-User e
X-Planning-Proxy-Key que venham do browser e envia os seus: o utilizador e uma chave secreta
partilhada. Esta camada só confia no utilizador quando a chave confere (comparação em tempo
constante); outro processo local que tente enviar um nome sem a chave fica anónimo.

Interruptores (ambiente do serviço):
- MES_PLANNING_PROXY_KEY: a chave partilhada com o Caddy (sem ela, ninguém é identificado);
- MES_PLANNING_AUTH_REQUIRED=1: recusa gravações (POST, PUT, PATCH, DELETE) sem utilizador;
- MES_PLANNING_READONLY_USERS: utilizadores só de consulta, separados por vírgulas (ex.: parede).
"""
import hmac
import json
import os

from .. import planning_registration as registration

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def identity(headers: dict[str, str]) -> str | None:
    key = os.environ.get("MES_PLANNING_PROXY_KEY", "")
    sent = headers.get("x-planning-proxy-key", "")
    if not key or not hmac.compare_digest(sent.encode(), key.encode()):
        return None
    user = headers.get("x-auth-user", "").strip()
    return user or None


def readonly_users() -> set[str]:
    return {u.strip() for u in os.environ.get("MES_PLANNING_READONLY_USERS", "").split(",") if u.strip()}


class ProxyIdentity:
    """Pure ASGI middleware: sets registration.ACTOR for the request and enforces write rules."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        user = identity(headers)
        writing = scope.get("method", "GET").upper() not in READ_METHODS
        if writing and os.environ.get("MES_PLANNING_AUTH_REQUIRED") == "1":
            if not user:
                return await _deny(send, 401, "Entra com o teu utilizador para gravar.")
            if user in readonly_users():
                return await _deny(send, 403, "Este utilizador só pode consultar.")
        token = registration.ACTOR.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            registration.ACTOR.reset(token)


async def _deny(send, status: int, message: str) -> None:
    body = json.dumps({"error": message}, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})
