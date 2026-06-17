# Argus-DB — Phase 0 部署說明 (Deployment Guide)

本指南帶你部署 **Phase 0 異動採集管線**：集中化稽核庫 (PostgreSQL) + Kafka +
Kafka Connect (Debezium)，並註冊 MSSQL / PostgreSQL 來源連接器。

> **範圍界定**：本階段交付的是「採集基礎設施 + 稽核庫 schema」。將 Debezium 事件
> 標準化寫入 `argus_audit.audit_event` 的 **Standardizer 消費服務** 屬於下一個
> (Phase 0 收尾的程式) 任務，尚未包含於此。詳見文末「下一步」。

相關檔案都在 [`deploy/`](../deploy/)：

```
deploy/
├── docker-compose.yml          # postgres + kafka + connect
├── .env.example                # 設定範例 (複製為 .env)
├── audit-store/01_schema.sql   # 稽核庫 schema (容器初始化時自動套用)
└── connectors/
    ├── postgres-source.json     # Debezium PostgreSQL (pgoutput)
    └── mssql-source.json        # Debezium SQL Server (CDC)
```

---

## 0. 前置需求

- Docker + Docker Compose v2
- 對受管來源 DB 的網路連通性
- 來源 DB 的管理權限 (用於啟用 CDC / 邏輯複製)

---

## 1. 設定環境變數

```bash
cd deploy
cp .env.example .env
# 編輯 .env：填入稽核庫密碼與各來源節點的連線資訊
# 注意：.env 已被 .gitignore 排除，切勿提交真實憑證
```

---

## 2. 啟動本地堆疊

```bash
docker compose -f deploy/docker-compose.yml up -d
```

啟動後：

- **稽核庫** 在初始化時自動套用 `audit-store/01_schema.sql`，建立 `argus_audit`
  schema、5 張中介表、當年度 12 個月分割表，以及 `argus_writer` / `argus_reader`
  兩個最小權限角色。
- **Kafka** 與 **Kafka Connect (Debezium)** 就緒後，Connect REST API 在
  `http://localhost:8083`。

確認三個服務皆 healthy：

```bash
docker compose -f deploy/docker-compose.yml ps
curl -s http://localhost:8083/connector-plugins | head    # 確認 Debezium plugin 已載入
```

驗證稽核庫 schema：

```bash
docker exec -it argus-audit-store \
  psql -U argus -d argus_audit_db -c "\dt argus_audit.*"
```

---

## 3. 來源端前置設定 (Source Prerequisites)

> log-based CDC 需在來源 DB 開啟對應機制，否則連接器無資料可讀。

### 3a. PostgreSQL 來源

1. `postgresql.conf` 設定並重啟：
   ```
   wal_level = logical
   max_replication_slots = 10
   max_wal_senders = 10
   ```
2. 建立具備複製權限的帳號 (對應 `.env` 的 `SRC_PG_USER`)：
   ```sql
   CREATE ROLE debezium WITH LOGIN REPLICATION PASSWORD '<secret>';
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO debezium;
   ```
3. **對每張受稽核表設定 `REPLICA IDENTITY FULL`** (才能取得 UPDATE/DELETE 的完整
   OLD 值)：
   ```sql
   ALTER TABLE public.user_accounts REPLICA IDENTITY FULL;
   ```

### 3b. MSSQL 來源

1. 確認 **SQL Server Agent 正在運行** (CDC capture/cleanup 作業依賴它)。
2. 於來源資料庫啟用 CDC：
   ```sql
   EXEC sys.sp_cdc_enable_db;
   EXEC sys.sp_cdc_enable_table
        @source_schema = N'dbo',
        @source_name   = N'user_accounts',
        @role_name     = NULL;
   ```
3. 建立供連接器使用的登入帳號 (對應 `.env` 的 `SRC_MSSQL_USER`)，授予讀取 CDC 表權限。

---

## 4. 註冊 Debezium 連接器

連接器設定使用 `${...}` 佔位符，從 `.env` 帶入。以 `envsubst` 展開後 POST 到
Connect API：

```bash
set -a; source deploy/.env; set +a

envsubst < deploy/connectors/postgres-source.json \
  | curl -s -X POST -H "Content-Type: application/json" \
         --data @- http://localhost:8083/connectors

envsubst < deploy/connectors/mssql-source.json \
  | curl -s -X POST -H "Content-Type: application/json" \
         --data @- http://localhost:8083/connectors
```

檢查狀態 (應為 `RUNNING`)：

```bash
curl -s http://localhost:8083/connectors/argus-src-postgres/status | jq
curl -s http://localhost:8083/connectors/argus-src-mssql/status | jq
```

---

## 5. 驗證資料流

列出 Kafka topics，應出現以 `argus.src.pg01.*` / `argus.src.mssql01.*` 命名的變更
topics：

```bash
docker exec -it argus-kafka \
  /kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

# 觀察某張表的變更事件 (Debezium envelope)
docker exec -it argus-kafka \
  /kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic argus.src.pg01.public.user_accounts --from-beginning --max-messages 1
```

在來源表做一筆 INSERT/UPDATE/DELETE，即可在對應 topic 看到含 `before`/`after` 的事件。

---

## 6. 停止 / 清理

```bash
docker compose -f deploy/docker-compose.yml down        # 停止, 保留資料 volume
docker compose -f deploy/docker-compose.yml down -v     # 連同 volume 一併刪除
```

---

## 下一步 (Next)

- **Standardizer 服務** (Phase 0 收尾)：FastAPI/Kafka consumer，消費上述 topics，
  套用 `argus_audit.schema_type_map` 正規化，冪等寫入 `argus_audit.audit_event`
  (以 `argus_writer` 角色連線)。
- **生產化**：以 `pg_partman` 自動維護月分割、依 `retention_days` 過期清理；
  將 `.env` 密碼改由 secret manager 注入；Kafka/Connect 改多節點與 TLS。

技術選型理由與 schema 細節見
[`architecture/phase-0-change-tracking.md`](./architecture/phase-0-change-tracking.md)。
