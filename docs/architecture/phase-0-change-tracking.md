# Phase 0 — 底層異動追蹤與標準化中介層 (Change Tracking)

> 本文件為 Argus-DB「階段零」的架構決策紀錄 (ADR)。
> 目標：以**最低侵入、最低延遲**的方式，從各受管節點擷取資料異動 (含 Old/New
> values)，標準化後寫入平台專屬的集中化稽核日誌庫。

---

## 0. TL;DR — 結論先行

| 來源引擎 | 採用技術 | 理由摘要 |
|---|---|---|
| **Microsoft SQL Server** | **Change Data Capture (CDC)** | 基於交易日誌、非同步、能擷取 before/after 完整列影像 (Old/New values)。 |
| **PostgreSQL** | **Logical Decoding (WAL) via Debezium `pgoutput`** | 基於 WAL、低負載、列級 before/after；`pgaudit` 作為 DDL/存取稽核的**互補**。 |

統一管線：兩端皆由 **Debezium** 連接器產生標準事件 → **Kafka** → 平台
**Standardizer** 服務做 Schema Unification → 寫入 **PostgreSQL** 集中化稽核庫
(`argus_audit`，按時間分割)。

---

## 1. MSSQL 異動採集 → Change Data Capture (CDC)

| 選項 | 結論 | 理由 |
|---|---|---|
| **Change Data Capture (CDC)** | ✅ **採用** | 讀取交易日誌、**非同步**，不需改動應用程式、不需 trigger，負載低。能擷取 **before + after 列影像** (Old/New values)，這是稽核的硬性需求。自 SQL Server 2016 SP1 起 Standard Edition 亦支援。Debezium SQL Server 連接器可原生消費 CDC 表。 |
| Change Tracking (CT) | ❌ 不採用 | 只記錄「某列變更了、哪些欄位變了」，**不保存欄位實際值**，無法滿足 Old/New 稽核需求。 |
| 自訂 Audit Triggers | ❌ 僅備援 | 在應用程式交易內**同步寫入**造成額外負載；schema 變更時脆弱；需逐表維護。僅在需要補捉 CDC 拿不到的應用層上下文時，作為局部備援。 |

**需留意的維運事項：**
- 依賴 **SQL Server Agent** 執行 capture 與 cleanup 作業。
- 需訂定 **schema 演進 / DDL 處理策略** (CDC 不會自動追蹤來源表的欄位變更)。
- 以 **LSN (Log Sequence Number)** 作為排序與冪等去重的依據。

---

## 2. PostgreSQL 異動採集 → Logical Decoding (WAL)

| 選項 | 結論 | 理由 |
|---|---|---|
| **Logical Replication / Logical Decoding (WAL)** | ✅ **採用** | 基於 WAL、低負載、列級 before/after。需對受稽核表設定 **`REPLICA IDENTITY FULL`** 才能在 UPDATE/DELETE 取得完整 OLD 值。採 Debezium PostgreSQL 連接器 + `pgoutput` plugin。 |
| pgaudit | ➕ **互補** | 記錄 SQL **語句文字**，適合 DDL / 特權存取稽核，但**不產生結構化的 Old/New 列差異**。與主管線並行啟用，用於 DDL 與登入稽核，不作為資料異動的主要採集手段。 |
| 通用 Triggers | ❌ 僅備援 | 可取得 OLD/NEW 與應用上下文，但有寫入負載且需逐表管理。保留作為 log-based 無法歸因時的「行為者上下文」補強。 |

**需留意的設定事項：**
- `wal_level = logical`、足夠的 `max_replication_slots` / `max_wal_senders`。
- 受稽核表 `REPLICA IDENTITY FULL`，否則 DELETE/UPDATE 取不到完整 OLD 值。
- 監控 replication slot 落後量，避免未消費造成 WAL 堆積撐爆磁碟。

---

## 3. 統一管線 (Unification Pipeline)

兩端 Debezium 連接器皆產生標準封包 (envelope)：`before` / `after` / `source` /
`op`。平台 **Standardizer** 服務 (Kafka consumer，FastAPI worker) 將每個封包映射為下
方 `audit_event` 統一結構，並套用 `schema_type_map` 做正規化型別轉換。

```
MSSQL ──(CDC)──────────┐                                   ┌── REST / read-only GraphQL API
                       ├─ Debezium ─ Kafka ─ Standardizer ─┤
PostgreSQL ─(WAL pgoutput)┘            (Schema Unify)       └── PostgreSQL 稽核庫 (分割表)
```

> **誠實揭露的已知限制：** log-based CDC 取得的是**資料庫層級**的行為者
> (`db_user`)。要對應到「平台登入者」身分，需要額外的上下文傳遞 (例如以
> `application_name` / session context 帶入)，此問題在 IAM / 存取權限模組解決，
> **CDC 本身無法獨力完成**。

---

## 4. 集中化稽核日誌庫 — Schema 定義

目標資料庫：平台專屬 PostgreSQL，schema 名稱 `argus_audit`。以下 DDL 可直接執行。

```sql
CREATE SCHEMA IF NOT EXISTS argus_audit;

-- 4.1 受管節點註冊表 (Hub-and-Spoke registry)
CREATE TABLE argus_audit.managed_node (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    node_key            TEXT        NOT NULL UNIQUE,          -- 穩定 slug，如 'prod-mssql-01'
    display_name        TEXT        NOT NULL,
    engine              TEXT        NOT NULL CHECK (engine IN ('mssql', 'postgresql')),
    host                TEXT        NOT NULL,
    port                INTEGER     NOT NULL,
    environment         TEXT        NOT NULL,                 -- prod / staging / dev
    secret_ref          TEXT        NOT NULL,                 -- 指向 secret manager，禁止明文
    readonly_secret_ref TEXT        NOT NULL,                 -- 唯讀連線專用憑證參考
    status              TEXT        NOT NULL DEFAULT 'registered',
    registered_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4.2 統一異動事件表 (按 committed_at 月分割)
CREATE TABLE argus_audit.audit_event (
    event_id          UUID        NOT NULL,
    node_id           BIGINT      NOT NULL REFERENCES argus_audit.managed_node(id),
    source_database   TEXT        NOT NULL,
    source_schema     TEXT        NOT NULL,
    source_table      TEXT        NOT NULL,
    operation         TEXT        NOT NULL
        CHECK (operation IN ('INSERT','UPDATE','DELETE','TRUNCATE','DDL','SNAPSHOT')),
    row_pk            JSONB       NOT NULL,                   -- 識別該列的主鍵
    old_values        JSONB,                                 -- 變更前 (DELETE/UPDATE)
    new_values        JSONB,                                 -- 變更後 (INSERT/UPDATE)
    changed_columns   TEXT[],                                -- UPDATE 時的異動欄位
    db_user           TEXT,                                  -- DB 層行為者
    app_user          TEXT,                                  -- 對應到的平台登入者 (若可傳遞)
    client_host       TEXT,
    application_name  TEXT,
    tx_id             TEXT,                                  -- 來源交易 ID
    source_lsn        TEXT,                                  -- MSSQL LSN / PG LSN，排序與去重
    source_ts_utc     TIMESTAMPTZ,                           -- 來源端 commit 時間
    committed_at      TIMESTAMPTZ NOT NULL,                  -- 正規事件時間 (分割鍵)
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),    -- 平台寫入時間
    capture_method    TEXT        NOT NULL
        CHECK (capture_method IN ('mssql_cdc','pg_logical','trigger','pgaudit')),
    source_offset     JSONB,                                 -- Debezium offset，供重播/去重
    raw_payload       JSONB,                                 -- 原始封包，保真用
    PRIMARY KEY (event_id, committed_at)
) PARTITION BY RANGE (committed_at);

-- 冪等去重：同一節點、同一 LSN、同一表、同一列只入帳一次
CREATE UNIQUE INDEX uq_audit_event_idem
    ON argus_audit.audit_event (node_id, source_lsn, source_table, row_pk, committed_at);

-- 常用查詢索引 (戰情室過濾)
CREATE INDEX ix_audit_event_node_time   ON argus_audit.audit_event (node_id, committed_at DESC);
CREATE INDEX ix_audit_event_table_time  ON argus_audit.audit_event (source_table, committed_at DESC);
CREATE INDEX ix_audit_event_old_gin     ON argus_audit.audit_event USING GIN (old_values);
CREATE INDEX ix_audit_event_new_gin     ON argus_audit.audit_event USING GIN (new_values);
CREATE INDEX ix_audit_event_pk_gin      ON argus_audit.audit_event USING GIN (row_pk);

-- 月分割範例 (實務上以排程或 pg_partman 自動建立)
CREATE TABLE argus_audit.audit_event_2026_06 PARTITION OF argus_audit.audit_event
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- 4.3 每節點/每表的採集設定
CREATE TABLE argus_audit.capture_config (
    id                 BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    node_id            BIGINT      NOT NULL REFERENCES argus_audit.managed_node(id),
    source_schema      TEXT        NOT NULL,
    source_table       TEXT        NOT NULL,
    enabled            BOOLEAN     NOT NULL DEFAULT true,
    capture_old_values BOOLEAN     NOT NULL DEFAULT true,
    retention_days     INTEGER     NOT NULL DEFAULT 365,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (node_id, source_schema, source_table)
);

-- 4.4 Schema Unification：來源型別 → 正規化型別 對應表
CREATE TABLE argus_audit.schema_type_map (
    engine         TEXT NOT NULL CHECK (engine IN ('mssql','postgresql')),
    source_type    TEXT NOT NULL,                            -- 如 'datetime2', 'uniqueidentifier'
    canonical_type TEXT NOT NULL,                            -- 如 'timestamp', 'uuid'
    notes          TEXT,
    PRIMARY KEY (engine, source_type)
);

-- 4.5 連接器斷點續傳檢查點
CREATE TABLE argus_audit.ingest_checkpoint (
    node_id        BIGINT      NOT NULL REFERENCES argus_audit.managed_node(id),
    connector_name TEXT        NOT NULL,
    last_lsn       TEXT,
    last_offset    JSONB,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node_id, connector_name)
);
```

---

## 5. 後續開放議題 (Open Questions)

- **DDL / Schema 演進**：來源表新增/移除欄位時，連接器與 `audit_event` 的對應策略。
- **保留政策**：依 `capture_config.retention_days` 自動 drop 過期分割表 (`DETACH` + `DROP`)。
- **行為者歸因**：如何將 `db_user` 對應到平台登入者 (與 IAM 模組整合)。
- **大量寫入擴展**：分割表 + GIN 索引的寫入成本評估；未來可評估外掛列式儲存。
