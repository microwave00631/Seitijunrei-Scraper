"""Basic 認証ミドルウェアのテスト。"""

import base64
import importlib

import pytest
from starlette.testclient import TestClient


def _reload_app(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import app.auth as auth
    import app.main as main
    importlib.reload(auth)
    importlib.reload(main)
    return main


def _basic(user, pw):
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_requires_password(monkeypatch):
    main = _reload_app(monkeypatch, SEITI_USER="admin", SEITI_PASSWORD="secret", SEITI_AUTH="1")
    c = TestClient(main.app)
    r = c.get("/")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate", "").startswith("Basic")


def test_wrong_password_rejected(monkeypatch):
    main = _reload_app(monkeypatch, SEITI_USER="admin", SEITI_PASSWORD="secret", SEITI_AUTH="1")
    c = TestClient(main.app)
    r = c.get("/", headers=_basic("admin", "nope"))
    assert r.status_code == 401


def test_correct_password_allows(monkeypatch):
    main = _reload_app(monkeypatch, SEITI_USER="admin", SEITI_PASSWORD="secret", SEITI_AUTH="1")
    c = TestClient(main.app)
    r = c.get("/", headers=_basic("admin", "secret"))
    assert r.status_code == 200
    assert "検索" in r.text


def test_non_ascii_password_works(monkeypatch):
    # 日本語パスワードでも TypeError にならず認証できること。
    main = _reload_app(monkeypatch, SEITI_USER="admin", SEITI_PASSWORD="ぱすわーど", SEITI_AUTH="1")
    c = TestClient(main.app)
    assert c.get("/").status_code == 401
    assert c.get("/", headers=_basic("admin", "まちがい")).status_code == 401
    assert c.get("/", headers=_basic("admin", "ぱすわーど")).status_code == 200


def test_auth_can_be_disabled(monkeypatch):
    main = _reload_app(monkeypatch, SEITI_AUTH="0")
    c = TestClient(main.app)
    r = c.get("/")
    assert r.status_code == 200


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    # 各テスト後に既定状態へ戻す。
    yield
    _reload_app(monkeypatch, SEITI_USER=None, SEITI_PASSWORD=None, SEITI_AUTH=None)
