# Argus-DB

> 企業級的**多資料庫管理與稽核平台** — 一個集中化的資料庫治理中樞 (Governance Hub)。
> 原生支援管理多節點的 Microsoft SQL Server 與 PostgreSQL。

本 README 為本專案的**最高指導原則**。所有開發都必須遵循此處的技術棧與開發規範；
程式碼行為準則另見 [`CLAUDE.md`](./CLAUDE.md)。

---

## 1. 願景 (Vision)

打造一個集中化的 Web 平台，作為資料庫治理中樞，提供標準化 API 與視覺化入口網，讓內部
人員能集中透視所有受管資料庫的結構、進行細緻的權限管控，並全面追蹤跨系統的歷史資料
異動 (CRUD 稽核)。

---

## 2. 架構 (Architecture)

- **Hub-and-Spoke 拓樸**：平台 (Hub) 註冊並集中管理多台資料庫伺服器 (Spoke)。
- **API-First**：所有結構解析與稽核日誌皆封裝為標準 API (REST 為主 + 唯讀 GraphQL)。
- **集中化稽核**：各端異動經統一管線標準化後，寫入平台專屬的稽核日誌庫。

```
MSSQL ──(CDC)──────────┐                                   ┌── REST / read-only GraphQL API
                       ├─ Debezium ─ Kafka ─ Standardizer ─┤
PostgreSQL ─(WAL pgoutput)┘            (Schema Unify)       └── PostgreSQL 稽核庫 (分割表)
```

Phase 0 (底層異動追蹤) 的完整技術決策與稽核庫 Schema 定義見
[`docs/architecture/phase-0-change-tracking.md`](./docs/architecture/phase-0-change-tracking.md)。

---

## 3. 技術棧 (Tech Stack)

### Backend
- **Python 3.12+ / FastAPI**
- **REST (OpenAPI)** 為主對外介面 + **唯讀 GraphQL** (Strawberry) 供複雜查詢
- **SQLAlchemy** + `asyncpg` (PostgreSQL) 與 `aioodbc` / `pyodbc` (MSSQL，唯讀瀏覽)
- AD / LDAP 整合：`ldap3` (SIMPLE bind)；Windows SSO 經 IIS Windows 驗證
- 部署：Windows IIS + HttpPlatformHandler + Waitress (FastAPI 經 `a2wsgi` 橋接)
- 憑證：一律經 **secret manager**，禁止明文

### Frontend
- **React + TypeScript + Tailwind CSS** (Vite)
- 實作 CRT / HUD 設計語言 (見 [§4 設計語言](#4-核心模組-core-modules))

### Data / Infra
- **PostgreSQL**：平台 metadata + 集中化稽核庫 (分割表 + JSONB)
- **Debezium + Kafka / Kafka Connect**：跨資料庫的 log-based CDC 採集管線
- 身份認證 / SSO：串接企業 Active Directory (AD / LDAP)，依部門/職級賦權

---

## 4. 核心模組 (Core Modules)

| 模組 | 說明 |
|---|---|
| 全局結構中控台 | 動態解析並展示各 DB 的 Tables / Views / 型別 / 主外鍵關聯 |
| 資料庫存取權限視圖 | 將平台登入者與 DB 實際 Users/Roles 做映射與檢視 |
| 全域操作稽核戰情室 | 跨系統歷史變更查詢 (多條件過濾 + Old/New values 追蹤) |
| 安全唯讀資料瀏覽器 | 動態連線池 + 唯讀權限 + 強制分頁瀏覽實體資料 |

### 設計語言 (Design Language)
平台視覺識別採 dark terminal / CRT「戰情室」HUD 風格。完整 token 與元件規範見
[`docs/design/ui-design-language.md`](./docs/design/ui-design-language.md)，
正式參考稿：[`docs/design/mockups/global-schema-console.html`](./docs/design/mockups/global-schema-console.html)。

---

## 5. 開發規範 (最高指導原則)

以下為**不可違反**的硬性規範：

1. **強制唯讀連線**
   安全資料瀏覽器**必須**使用專屬的動態連線池，並綁定**唯讀 DB 角色**；嚴禁重用
   採集/管理憑證。需於**角色層級**與**唯讀交易**雙重強制。

2. **強制分頁**
   所有實體資料與稽核查詢**必須分頁**；大表優先採 **keyset / seek 分頁**而非
   `OFFSET`；強制 max page size；**嚴禁回傳無上限結果集**。

3. **憑證管理**
   repo 與 DB 內**禁止明文憑證**；一律以 `secret_ref` 指向 secret manager。

4. **每節點最小權限**
   採集 (capture) / 唯讀 (read) / 管理 (admin) 角色嚴格分離。

5. **API-First**
   每項能力都必須有版本化的 REST (OpenAPI) 介面；複雜唯讀查詢另提供 GraphQL。

6. **稽核 Schema 統一**
   各端異動日誌須先經 Schema Unification 標準化，才寫入集中化稽核庫。

> 程式碼層級的行為準則 (簡潔、外科手術式變更、目標導向驗證) 一律遵循
> [`CLAUDE.md`](./CLAUDE.md)。

---

## 6. 專案結構 (Proposed Layout)

```
argus-db/
├── README.md                      # 本檔 — 最高指導原則
├── CLAUDE.md                      # 程式碼行為準則
├── app/                           # 平台 API 服務 (FastAPI)
│   ├── argus_api/                 #   應用程式 (auth / AD 整合 / 路由)
│   ├── wsgi.py  web.config        #   IIS + Waitress 部署進入點與設定
│   ├── requirements.txt  .env.example
│   └── tests/                     #   純函式單元測試
├── deploy/                        # Phase 0 採集管線部署資產
│   ├── docker-compose.yml         #   postgres + kafka + connect
│   ├── .env.example               #   設定範例 (複製為 .env)
│   ├── audit-store/01_schema.sql  #   稽核庫 schema (初始化自動套用)
│   └── connectors/                #   Debezium 連接器設定 (mssql / postgres)
└── docs/
    ├── deployment.md              # Phase 0 採集管線部署說明 (容器)
    ├── deployment-iis.md          # 平台 API 部署說明 (Windows IIS + AD)
    ├── architecture/
    │   └── phase-0-change-tracking.md   # Phase 0 異動採集決策 + 稽核庫 Schema
    └── design/
        ├── ui-design-language.md        # UI 設計語言 (tokens + 元件規範)
        └── mockups/
            └── global-schema-console.html   # 設計參考稿
```

---

## 7. 路線圖 (Roadmap)

- **Phase 0 — 底層異動追蹤與標準化中介層**：文件已定案；採集管線 + 稽核庫已可部署
  (見 [`docs/deployment.md`](./docs/deployment.md))。剩餘程式任務：Standardizer 消費服務。
- **Phase 1 — 平台核心架構與權限中樞** (IAM / AD SSO / 多節點註冊) ← *進行中：平台 API
  骨架 + AD Windows 驗證 (SSO + 手動登入) 已可部署於 Windows IIS，見
  [`docs/deployment-iis.md`](./docs/deployment-iis.md)。*
- **Phase 2 — 核心功能模組** (結構中控台 / 權限視圖 / 稽核戰情室 / 唯讀瀏覽器)
