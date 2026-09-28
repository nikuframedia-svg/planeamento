"""Identidade dada pelo Caddy (app/sector/auth.py) e o seu efeito em human_actor()."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import planning_registration as registration
from app.sector.auth import ProxyIdentity, identity

KEY = "chave-de-teste-32-caracteres-0123456789"


@pytest.fixture()
def client():
    app = FastAPI()

    @app.get("/quem")
    def who():  # síncrono: corre noutra thread, como as rotas reais
        return {"actor": registration.human_actor({})}

    @app.post("/grava")
    def save():
        return {"actor": registration.human_actor({"actor": "nome enviado pelo browser"})}

    app.add_middleware(ProxyIdentity)
    return TestClient(app)


def signed(user, key=KEY):
    return {"X-Auth-User": user, "X-Planning-Proxy-Key": key}


def test_identity_needs_the_shared_key(monkeypatch):
    monkeypatch.delenv("MES_PLANNING_PROXY_KEY", raising=False)
    assert identity({"x-auth-user": "luis", "x-planning-proxy-key": KEY}) is None
    monkeypatch.setenv("MES_PLANNING_PROXY_KEY", KEY)
    assert identity({"x-auth-user": "luis", "x-planning-proxy-key": KEY}) == "luis"
    assert identity({"x-auth-user": "luis", "x-planning-proxy-key": "outra"}) is None
    assert identity({"x-auth-user": " ", "x-planning-proxy-key": KEY}) is None


def test_without_configuration_everything_stays_anonymous(client, monkeypatch):
    monkeypatch.delenv("MES_PLANNING_PROXY_KEY", raising=False)
    monkeypatch.delenv("MES_PLANNING_AUTH_REQUIRED", raising=False)
    assert client.get("/quem", headers=signed("luis")).json() == {"actor": "Utilizador não identificado"}
    assert client.post("/grava").json() == {"actor": "Utilizador não identificado"}


def test_authenticated_user_is_the_actor_and_a_client_name_is_ignored(client, monkeypatch):
    monkeypatch.setenv("MES_PLANNING_PROXY_KEY", KEY)
    assert client.get("/quem", headers=signed("planeador")).json() == {"actor": "planeador"}
    assert client.post("/grava", headers=signed("planeador")).json() == {"actor": "planeador"}
    assert client.post("/grava", headers=signed("planeador", key="falsa")).json() == {"actor": "Utilizador não identificado"}
    assert registration.ACTOR.get() is None  # nada fica para o pedido seguinte


def test_required_login_blocks_anonymous_and_read_only_writes_but_not_reads(client, monkeypatch):
    monkeypatch.setenv("MES_PLANNING_PROXY_KEY", KEY)
    monkeypatch.setenv("MES_PLANNING_AUTH_REQUIRED", "1")
    monkeypatch.setenv("MES_PLANNING_READONLY_USERS", "parede, consulta")
    denied = client.post("/grava")
    assert denied.status_code == 401 and "utilizador" in denied.json()["error"]
    assert client.post("/grava", headers=signed("parede")).status_code == 403
    assert client.get("/quem", headers=signed("parede")).json() == {"actor": "parede"}
    assert client.get("/quem").status_code == 200
    assert client.post("/grava", headers=signed("planeador")).json() == {"actor": "planeador"}
