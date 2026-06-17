"""身分解析與授權相依 (FastAPI dependencies)。

身分優先順序 (skill)：
    手動登入 (session.manual_user) > logged_out 壓制 > SSO (Windows 驗證) > 無身分
無身分時一律回 200 + auth_type=null，**永不回 401** (回 401 會觸發瀏覽器原生憑證視窗)。
"""
from fastapi import Depends, HTTPException, Request

from . import ad_auth, config
from .ad_utils import parse_ntlm_username
from .windows_token import username_from_token


def _resolve_sso(request: Request) -> str:
    """從 IIS 傳入的 Windows 驗證資訊解析帳號名。"""
    if config.MOCK_AD:
        return config.MOCK_AD_USER

    # 方法 1：REMOTE_USER (ARR/反向代理環境，a2wsgi 會放進 scope)
    remote = request.scope.get("REMOTE_USER") or ""
    if remote:
        return remote.split("\\")[-1].split("@")[0]

    # 方法 2：NTLM Authorization 標頭直接解碼 (純 Python)
    auth = request.headers.get("authorization", "")
    if auth.startswith(("NTLM ", "Negotiate ")):
        username = parse_ntlm_username(auth)
        if username:
            return username

    # 方法 3：HttpPlatformHandler 主要方式 — Windows token handle
    token_str = request.headers.get("x-iis-windowsauthtoken", "")
    if token_str:
        try:
            return username_from_token(int(token_str, 16))
        except ValueError:
            return ""
    return ""


def get_current_user(request: Request) -> dict:
    """回傳 {'samaccount':..., 'auth_type': 'manual'|'sso'} 或 {} (無身分)。"""
    manual = request.session.get("manual_user")
    if manual:
        return {"samaccount": manual, "auth_type": "manual"}
    if request.session.get("logged_out"):
        return {}
    sso = _resolve_sso(request)
    if sso:
        return {"samaccount": sso, "auth_type": "sso"}
    return {}


def require_groups(*groups):
    """產生「需屬於指定 AD 群組」的相依。未登入回 401、權限不足回 403。"""
    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if not user:
            raise HTTPException(status_code=401, detail="未登入")
        if not ad_auth.user_in_groups(user["samaccount"], groups):
            raise HTTPException(status_code=403,
                                detail={"error": "權限不足", "required": list(groups)})
        return user
    return dependency
