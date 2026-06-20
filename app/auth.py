"""簡易パスワード保護(HTTP Basic 認証)。

全ルート(静的ファイル `/screenshots` を含む)をミドルウェアで保護する。
認証情報は環境変数で設定する。

  SEITI_USER      ユーザー名(既定: "admin")
  SEITI_PASSWORD  パスワード(既定: "seichi" — 公開時は必ず変更すること)
  SEITI_AUTH      "0"/"false"/"off" で認証を無効化(ローカル開発用)

注意: Basic 認証は資格情報を Base64 で送るだけなので、**公開時は必ず HTTPS
(リバースプロキシ等)の背後で運用**すること。
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_REALM = "Seitijunrei"


def _enabled() -> bool:
    return os.environ.get("SEITI_AUTH", "1").lower() not in {"0", "false", "off", "no"}


def _credentials() -> tuple[str, str]:
    return (
        os.environ.get("SEITI_USER", "admin"),
        os.environ.get("SEITI_PASSWORD", "seichi"),
    )


def _check(header: str | None) -> bool:
    """Authorization ヘッダが正しい Basic 認証なら True。"""
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return False
    user, _, password = decoded.partition(":")
    exp_user, exp_password = _credentials()
    # タイミング攻撃を避けるため定数時間比較。
    ok_user = secrets.compare_digest(user, exp_user)
    ok_pass = secrets.compare_digest(password, exp_password)
    return ok_user and ok_pass


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """全リクエストに Basic 認証を要求するミドルウェア。"""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not _enabled():
            return await call_next(request)
        if not _check(request.headers.get("Authorization")):
            return Response(
                status_code=401,
                content="認証が必要です / Authentication required",
                headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
            )
        return await call_next(request)
