-- =============================================================================
-- Argus-DB | Phase 0 集中化稽核日誌庫 (Central Audit Store)
-- Target: PostgreSQL 14+ (developed/validated on 16)
-- 此檔為 docs/architecture/phase-0-change-tracking.md §4 的可執行版本。
-- 由 Postgres 容器的 /docker-entrypoint-initdb.d 於初始化時自動套用。
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS argus_audit;

-- -----------------------------------------------------------------------------
-- Roles (落實「每節點最小權限」: 採集寫入 vs 唯讀分離)
-- 密碼一律由外部 secret manager 注入; 此處只建立角色, 不設明文密碼。
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'argus_writer') THEN
        CREATE ROLE argus_writer NOLOGIN;   -- Standardizer 寫入稽核事件
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'argus_reader') THEN
        CREATE ROLE argus_reader NOLOGIN;   -- 戰情室/API 唯讀查詢
    END IF;
END
$$;

-- =============================================================================
-- 4.1 受管節點註冊表 (Hub-and-Spoke registry)
-- =============================================================================
CREATE TABLE IF NOT EXISTS argus_audit.managed_node (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    node_key            TEXT        NOT NULL UNIQUE,          -- 穩定 slug, 如 'prod-mssql-01'
    display_name        TEXT        NOT NULL,
    engine              TEXT        NOT NULL CHECK (engine IN ('mssql', 'postgresql')),
    host                TEXT        NOT NULL,
    port                INTEGER     NOT NULL,
    environment         TEXT        NOT NULL,                 -- prod / staging / dev
    secret_ref          TEXT        NOT NULL,                 -- 指向 secret manager, 禁止明文
    readonly_secret_ref TEXT        NOT NULL,                 -- 唯讀連線專用憑證參考
    status              TEXT        NOT NULL DEFAULT 'registered',
    registered_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- 4.2 統一異動事件表 (按 committed_at 月分割)
-- =============================================================================
CREATE TABLE IF NOT EXISTS argus_audit.audit_event (
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
    source_lsn        TEXT,                                  -- MSSQL LSN / PG LSN, 排序與去重
    source_ts_utc     TIMESTAMPTZ,                           -- 來源端 commit 時間
    committed_at      TIMESTAMPTZ NOT NULL,                  -- 正規事件時間 (分割鍵)
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),    -- 平台寫入時間
    capture_method    TEXT        NOT NULL
        CHECK (capture_method IN ('mssql_cdc','pg_logical','trigger','pgaudit')),
    source_offset     JSONB,                                 -- Debezium offset, 供重播/去重
    raw_payload       JSONB,                                 -- 原始封包, 保真用
    PRIMARY KEY (event_id, committed_at)
) PARTITION BY RANGE (committed_at);

-- 冪等去重: 同一節點/同一 LSN/同一表/同一列只入帳一次 (含分割鍵)
CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_event_idem
    ON argus_audit.audit_event (node_id, source_lsn, source_table, row_pk, committed_at);

-- 常用查詢索引 (戰情室過濾)
CREATE INDEX IF NOT EXISTS ix_audit_event_node_time
    ON argus_audit.audit_event (node_id, committed_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_event_table_time
    ON argus_audit.audit_event (source_table, committed_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_event_old_gin
    ON argus_audit.audit_event USING GIN (old_values);
CREATE INDEX IF NOT EXISTS ix_audit_event_new_gin
    ON argus_audit.audit_event USING GIN (new_values);
CREATE INDEX IF NOT EXISTS ix_audit_event_pk_gin
    ON argus_audit.audit_event USING GIN (row_pk);

-- -----------------------------------------------------------------------------
-- 月分割表: 啟動年度先建好 12 個月。
-- 生產環境建議改用 pg_partman 自動維護 (建立 + 過期 DETACH/DROP)。
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    start_month DATE := date_trunc('year', now())::date;   -- 當年 1 月
    m           INTEGER;
    p_from      DATE;
    p_to        DATE;
    p_name      TEXT;
BEGIN
    FOR m IN 0..11 LOOP
        p_from := (start_month + (m    || ' month')::interval)::date;
        p_to   := (start_month + (m + 1 || ' month')::interval)::date;
        p_name := format('audit_event_%s', to_char(p_from, 'YYYY_MM'));
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS argus_audit.%I PARTITION OF argus_audit.audit_event '
            || 'FOR VALUES FROM (%L) TO (%L);',
            p_name, p_from, p_to
        );
    END LOOP;
END
$$;

-- =============================================================================
-- 4.3 每節點/每表的採集設定
-- =============================================================================
CREATE TABLE IF NOT EXISTS argus_audit.capture_config (
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

-- =============================================================================
-- 4.4 Schema Unification: 來源型別 -> 正規化型別 對應表
-- =============================================================================
CREATE TABLE IF NOT EXISTS argus_audit.schema_type_map (
    engine         TEXT NOT NULL CHECK (engine IN ('mssql','postgresql')),
    source_type    TEXT NOT NULL,                            -- 如 'datetime2', 'uniqueidentifier'
    canonical_type TEXT NOT NULL,                            -- 如 'timestamp', 'uuid'
    notes          TEXT,
    PRIMARY KEY (engine, source_type)
);

-- 常見型別的初始對應 (可後續擴充)
INSERT INTO argus_audit.schema_type_map (engine, source_type, canonical_type, notes) VALUES
    ('mssql',      'uniqueidentifier', 'uuid',      NULL),
    ('mssql',      'datetime2',        'timestamp', NULL),
    ('mssql',      'bit',              'boolean',   NULL),
    ('mssql',      'nvarchar',         'text',      NULL),
    ('postgresql', 'timestamptz',      'timestamp', NULL),
    ('postgresql', 'uuid',             'uuid',      NULL),
    ('postgresql', 'jsonb',            'json',      NULL)
ON CONFLICT (engine, source_type) DO NOTHING;

-- =============================================================================
-- 4.5 連接器斷點續傳檢查點
-- =============================================================================
CREATE TABLE IF NOT EXISTS argus_audit.ingest_checkpoint (
    node_id        BIGINT      NOT NULL REFERENCES argus_audit.managed_node(id),
    connector_name TEXT        NOT NULL,
    last_lsn       TEXT,
    last_offset    JSONB,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node_id, connector_name)
);

-- =============================================================================
-- 權限授予 (最小權限)
-- =============================================================================
GRANT USAGE ON SCHEMA argus_audit TO argus_writer, argus_reader;

-- writer: 註冊/設定表可讀寫, 稽核事件可寫入
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA argus_audit TO argus_writer;

-- reader: 全 schema 唯讀
GRANT SELECT ON ALL TABLES IN SCHEMA argus_audit TO argus_reader;

-- 未來新建的分割表/資料表自動沿用上述授權
ALTER DEFAULT PRIVILEGES IN SCHEMA argus_audit
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO argus_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA argus_audit
    GRANT SELECT ON TABLES TO argus_reader;
