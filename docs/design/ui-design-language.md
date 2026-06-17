# Argus-DB — UI 設計語言 (Design Language)

> 平台的視覺識別準則。所有前端介面 (React + TypeScript + Tailwind CSS) 都**必須**
> 遵循本文件定義的 token 與元件規範。
> 正式參考稿：[`mockups/global-schema-console.html`](./mockups/global-schema-console.html)
> (「全局結構中控台」原始 mockup，請以瀏覽器開啟檢視)。

---

## 1. 美學定位

**Dark terminal / CRT「戰情室」HUD**。整體呈現如一個高密度的監控終端機：

- 掃描線 (scanlines) 與 CRT 微閃爍 (flicker)
- 背景幽靈資料流 (phantom data streams)、全域像素網格 (global grid)
- 浮動 HUD 視窗，四角帶定位括號 (corner brackets)
- glitch 標題文字、blinking 狀態指示燈
- 全大寫 (uppercase) 介面文字、等寬字型

---

## 2. 色彩 Token

| Token | Hex | 用途 |
|---|---|---|
| `background` | `#050608` | 最底層背景 |
| `surface` | `#0d1117` | 一般表面 |
| `surface-container-lowest` | `#0a0c10` | 容器階層 (最低) |
| `surface-container-low` | `#11151a` | 容器階層 |
| `surface-container-high` | `#1c2128` | 容器階層 (最高) |
| **`primary`** | **`#d4ff00`** | **主色 — 霓虹萊姆綠**，重點/啟用/hover |
| `primary-fixed` | `#caf300` | 主色變體 |
| `secondary-fixed` | `#58a6ff` | 次色 — 藍，連結/關聯/標記 |
| `on-surface` | `#c9d1d9` | 主要文字 |
| `on-surface-variant` | `#8b949e` | 次要/弱化文字 |
| `outline-variant` | `#2a3441` | 邊框/分隔線 |
| `error` | `#ff7b72` | 錯誤/唯讀警示 |

---

## 3. 字型 (Typography)

字族：**`Geist Mono`** (monospace) — 全介面統一使用。

| 樣式 | 大小 / 行高 | 字重 | 特徵 |
|---|---|---|---|
| `headline-lg` | 24 / 32 | 700 | letter-spacing 0.1em |
| `headline-md` | 16 / 24 | 700 | letter-spacing 0.15em |
| `data-lg` | 14 / 24 | 600 | letter-spacing 0.05em |
| `data-md` | 12 / 18 | 400 | 資料表格 |
| `body-lg` | 14 / 24 | 400 | 內文 |
| `body-md` | 13 / 20 | 400 | 內文 (預設) |
| `label-caps` | 10 / 16 | 700 | letter-spacing 0.25em，全大寫標籤 |

---

## 4. 形狀與間距 (Shape & Spacing)

- **`border-radius: 0`** — 全域無圓角，鋭利邊緣。
- 邊框一律 **`1px`** 細線，色用 `outline-variant`。
- 網格基本單位 **4px**；版面採無外距、HUD 浮動視窗鋪滿視口。

---

## 5. 招牌元件 (Signature Components)

- **Floating window**：半透明 `surface` + `backdrop-blur`，四角 `hud-corner` 藍色括號。
- **`trigger-btn`**：透明底 + 細邊框，hover 反白為實心萊姆綠 (或藍色 `.secondary`)。
- **`READ_ONLY` badge**：`error` 色細邊框標籤，標示唯讀資料來源。
- **Kernel / Telemetry feed**：終端機式逐行日誌、blinking 游標。
- **Relation map**：向量關聯圖 (PK/FK)，搭配靶心格線背景。
- **狀態指示燈**：`blink` 動畫小方塊 (如 `CDC_ACTV`)。

---

## 6. 實作指引 (Implementation Notes)

- 將 mockup 的 `tailwind.config` token 集 (色彩、字型、fontSize、borderRadius、spacing)
  移植進專案的 `tailwind.config.ts`，作為單一真實來源。
- CRT/scanline/glitch 等效果以一層獨立 CSS (`@layer`) 實作，避免污染元件邏輯。
- 元件以 React + TypeScript 建構，樣式優先用 Tailwind utility，複雜效果才落 CSS。

### 無障礙 (Accessibility) — 必須遵守

- 確保文字與背景對比度足夠 (尤其 `on-surface-variant` 於深底上的小字)。
- **尊重 `prefers-reduced-motion`**：偵測到時關閉 flicker / scanline / phantom-stream /
  blink 等動畫，提供靜態版本。
- blinking 不可作為唯一的資訊傳達手段 (需搭配文字/顏色)。
