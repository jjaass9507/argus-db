"""Argus-DB 平台 API — FastAPI 應用程式進入點。

REST 為主 (OpenAPI 於 /docs)。AD Windows 驗證見 auth.py / ad_auth.py。
"""
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import ad_auth, config
from .auth import get_current_user, require_groups

app = FastAPI(title="Argus-DB Platform API", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)


class LoginBody(BaseModel):
    username: str
    password: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/auth/whoami")
def whoami(request: Request) -> JSONResponse:
    """目前身分；無身分回 200 + auth_type=null (不回 401)。"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"auth_type": None,
                             "logged_out": request.session.get("logged_out", False)})
    info = ad_auth.get_ad_user_info(user["samaccount"])
    return JSONResponse({"auth_type": user["auth_type"], **info})


@app.post("/api/v1/auth/login")
def login(body: LoginBody, request: Request) -> JSONResponse:
    """手動 AD 登入 (切換帳號)。密碼錯誤回 401。"""
    if not ad_auth.verify_ad_password(body.username, body.password):
        return JSONResponse({"error": "帳號或密碼錯誤"}, status_code=401)
    request.session["manual_user"] = body.username
    request.session.pop("logged_out", None)
    return JSONResponse({"ok": True, "auth_type": "manual"})


@app.post("/api/v1/auth/logout")
def logout(request: Request) -> JSONResponse:
    """登出並壓制 SSO；回 200 (不回 401)。"""
    request.session.pop("manual_user", None)
    request.session["logged_out"] = True
    return JSONResponse({"ok": True})


@app.get("/api/v1/admin/ping")
def admin_ping(user: dict = Depends(require_groups("IT-Admins"))) -> dict:
    """示範：需屬於 IT-Admins 群組才能存取。"""
    return {"message": "pong", "user": user["samaccount"]}


if config.ENABLE_DEBUG_ENDPOINTS:
    @app.get("/debug/env")
    def debug_env(request: Request) -> dict:
        """確認 IIS 傳入的身分資訊；正式環境請關閉 ENABLE_DEBUG_ENDPOINTS。"""
        keys = ["x-iis-windowsauthtoken", "authorization", "host"]
        return {
            "headers": {k: request.headers.get(k, "(無)") for k in keys},
            "remote_user": request.scope.get("REMOTE_USER", "(無)"),
            "resolved": get_current_user(request) or None,
        }
