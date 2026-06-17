# Argus-DB 平台 API — Windows IIS + AD 部署說明

本指南說明把 **平台 API 服務** (`app/`, FastAPI) 部署到 **Windows Server IIS**，
採 **HttpPlatformHandler + Waitress** 架構並整合 **Active Directory Windows 驗證**。

> 本文件遵循 **`python-iis-ad-deploy` skill**；該 skill 為部署方法的權威參考
> (架構決策、PowerShell/UI 步驟、AD 整合、離線打包、故障排除)。本文件只記錄
> Argus-DB 的具體參數與差異點。

> **範圍**：這是「平台 Web/API 層」的部署。Phase 0 的異動採集管線
> (Kafka + Debezium + 稽核庫) 是另一條軌，見 [`deployment.md`](./deployment.md)；
> skill 也指出非 HTTP 的背景 worker 用 WinSW/NSSM，不走 HttpPlatformHandler。

---

## 與 skill 的關鍵差異：FastAPI (ASGI) 如何配 Waitress (WSGI)

skill 範例為 Flask；本平台用 **FastAPI (ASGI)**，而 Waitress 是 WSGI server。
因此 `app/wsgi.py` 以 **`a2wsgi`** 橋接：

```python
from a2wsgi import ASGIMiddleware
from argus_api.main import app
application = ASGIMiddleware(app)
```

如此一來 skill 的 web.config 範本
(`waitress-serve ... wsgi:application`) **可原封不動沿用**。
> 限制：WSGI 橋接不支援 WebSocket/streaming；本平台 API 為 REST，無此需求。
> 若未來需原生 ASGI，改用 `uvicorn`/`hypercorn` 並調整 web.config 的 `arguments`。

---

## `app/` 結構

```
app/
├── argus_api/
│   ├── main.py          # FastAPI app + 路由 (/health, /api/v1/auth/*, /api/v1/admin/*)
│   ├── config.py        # 由 .env 載入設定 (AD_*, SECRET_KEY, MOCK_AD)
│   ├── auth.py          # 身分解析 (manual > logged_out > SSO) + 群組授權相依
│   ├── ad_auth.py       # SIMPLE bind 密碼驗證 + 使用者/群組查詢
│   ├── ad_utils.py      # 純函式 (base_dn 推導、NTLM 解碼)
│   └── windows_token.py # Windows token -> 帳號 (僅 Windows 生效)
├── wsgi.py              # Waitress 進入點 (a2wsgi 橋接)
├── web.config          # IIS HttpPlatformHandler 設定 (本次部署的關鍵檔)
├── requirements.txt
├── .env.example        # 複製為 .env，正式環境 MOCK_AD=false
└── tests/              # 純函式單元測試
```

---

## 部署前資訊 (對照 skill「部署前需確認的資訊」)

| 資訊 | Argus-DB 範例 |
|------|--------------|
| 部署目錄 | `D:\WebServices\argus-api` |
| IIS 站台 Port | `8001` |
| AD 伺服器 (NetBIOS) | `KH` → `AD_SERVER=ldap://KH` |
| AD 網域 | `kh.asegroup.com` |
| AD BaseDN | `DC=kh,DC=asegroup,DC=com` |
| Python 版本 | 與 `wheels/` 打包時一致 (建議 3.11.x) |

---

## 步驟總覽 (詳細指令見 skill)

依 skill 的 6 步，Argus-DB 專屬參數如下：

1. **安裝 IIS 功能 + HttpPlatformHandler + Python**
   `Web-Server, Web-Windows-Auth, Web-CGI` + HttpPlatformHandler v2.0 MSI；
   Python 勾「Install for all users」。→ skill `references/iis-setup.md`

2. **開發機打包離線 wheel** (內網隔離用)：
   ```powershell
   cd app
   pip download -r requirements.txt -d wheels `
     --platform win_amd64 --python-version 3.11 --only-binary=:all:
   ```
   把 `app/`（含 source、`requirements.txt`、`wheels/`、`web.config`）傳到部署機；
   **不傳** `venv/`、`.env`。→ skill `references/offline-deploy.md`

3. **部署機建 venv + 離線安裝 + 建 logs**：
   ```powershell
   cd D:\WebServices\argus-api
   python -m venv venv
   .\venv\Scripts\pip install --no-index --find-links=wheels -r requirements.txt
   New-Item -ItemType Directory -Force .\logs
   ```

4. **放入 `web.config`**：把檔內 `D:\WebServices\argus-api` 全部替換成實際路徑。
   三個必填欄位 (`processPath` / `PYTHONPATH` / `forwardWindowsAuthToken="true"`)
   見 skill `references/web-config.md`。

5. **建立 `.env`** (由 `.env.example` 複製)：
   ```ini
   MOCK_AD=false
   AD_SERVER=ldap://KH
   AD_DOMAIN=kh.asegroup.com
   AD_BASE_DN=DC=kh,DC=asegroup,DC=com
   AD_BIND_DN=            # 服務帳號 (選填，查群組才需要)
   AD_BIND_PW=
   SECRET_KEY=<長亂數>
   ENABLE_DEBUG_ENDPOINTS=false
   ```

6. **建 AppPool (No Managed Code + AlwaysRunning) + 網站 (Port 8001) + 停用匿名/啟用
   Windows 驗證 + 目錄權限 → `iisreset`**。→ skill `references/iis-setup.md`

---

## 驗證

```powershell
# 即時看 log
Get-Content "D:\WebServices\argus-api\logs\python.log" -Tail 20 -Wait
```

透過 IIS 站台 Port (非 Waitress 動態 port) 存取：

| 端點 | 預期 |
|------|------|
| `GET http://<host>:8001/health` | `{"status":"ok"}` |
| `GET /api/v1/auth/whoami` | SSO 自動帶入 → `{"auth_type":"sso","samaccount":...}`；無身分回 200 + `auth_type:null` (**不回 401**) |
| `GET /debug/env` | 確認 IIS 傳入身分 (需 `ENABLE_DEBUG_ENDPOINTS=true`，**驗證後關閉**) |
| `GET /docs` | OpenAPI 文件 |

切換帳號：`POST /api/v1/auth/login {username,password}` (SIMPLE bind)；
`POST /api/v1/auth/logout` 壓制 SSO。

---

## 開發 / 非 Windows 環境

`MOCK_AD=true` 時跳過真實 AD，回傳 `MOCK_AD_USER` 假身分 (登入密碼用 `mock`)，
可在 Linux/macOS 直接跑：

```bash
cd app
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
MOCK_AD=true SECRET_KEY=dev uvicorn argus_api.main:app --reload
# 單元測試 (純函式，免裝相依)
python -m unittest discover -s tests -t .
```

---

## 常見錯誤

完整故障排除見 skill `references/troubleshooting.md`。最常見：

| 訊息 | 解法 |
|------|------|
| `502 Bad Gateway` | 看 `logs\python.log`；確認 `processPath`/`PYTHONPATH`/目錄權限/venv 套件 |
| `unsupported hash type MD4` | 已用 SIMPLE bind (非 NTLM)，本平台不受影響 |
| 登出後跳 Windows 認證視窗 | 無身分一律回 200 (本平台已遵循)，勿回 401 |
| `Fatal error in launcher` | venv 不可搬移，於部署機最終路徑重建 |
