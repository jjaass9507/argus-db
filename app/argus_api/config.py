"""平台 API 設定 — 由 .env 載入 (見 .env.example)。

機密一律由環境變數 / secret manager 注入，禁止寫死於程式碼。
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# --- AD / LDAP ---
AD_SERVER = os.environ.get("AD_SERVER", "ldap://KH")        # NetBIOS 短名
AD_DOMAIN = os.environ.get("AD_DOMAIN", "")                 # 完整網域
AD_BASE_DN = os.environ.get("AD_BASE_DN", "")               # 搜尋根目錄 (空則由網域推導)
AD_BIND_DN = os.environ.get("AD_BIND_DN", "")               # 服務帳號 (選填，查群組用)
AD_BIND_PW = os.environ.get("AD_BIND_PW", "")

# --- Session ---
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")

# --- 開發模式 ---
# MOCK_AD=true 時跳過真實 AD，回傳設定好的假身分，使 app 可在非 Windows 環境開發/測試。
MOCK_AD = _bool("MOCK_AD", False)
MOCK_AD_USER = os.environ.get("MOCK_AD_USER", "K11879")
MOCK_AD_GROUPS = [g.strip() for g in os.environ.get("MOCK_AD_GROUPS", "DB-Viewers").split(",") if g.strip()]

# 診斷端點 (/debug/env)；正式環境務必關閉 (skill 建議上線前移除)。
ENABLE_DEBUG_ENDPOINTS = _bool("ENABLE_DEBUG_ENDPOINTS", False)
