# 🩺 麻醉 AI 查房助理（Demo）

一套可以展示的**麻醉科 AI Agent 系統**：AI 助理依照使用者設定的時間，定期「查房」50 位即時模擬的麻醉病人，使用使用者提供的**工具**（規則、臨床評分、機器學習、深度學習模型）判讀病況，依照**技能**（SOP）撰寫建議，並能與使用者對話互動。

**技術架構：前端 Vue 3・後端 FastAPI・資料庫 PostgreSQL（SQLAlchemy ORM + Alembic）**

> ⚠️ 所有病人資料皆為電腦模擬。本系統僅供展示與教育用途，**不是醫療器材，請勿用於真實病人**。

---

## 一、開始使用（不需要會寫程式）

事前準備：安裝 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（只需要裝一次）。

1. **啟動**：macOS 雙擊 `start.command`；Windows 雙擊 `start.bat`
   - 會自動開啟 Docker、建立資料庫與系統；第一次需要下載與建置，約 3–8 分鐘
2. **瀏覽器會自動打開** `http://127.0.0.1:8000`
3. （選用）到「⚙️ 設定」輸入 **Claude API 金鑰**，開啟完整 AI 對話與 AI 查房摘要；不輸入也能以「離線模式」展示
4. **關閉**：雙擊 `stop.command`（Windows：`stop.bat`）。所有資料保留在資料庫，下次啟動可繼續使用

---

## 二、系統功能

| 功能 | 說明 |
|---|---|
| 📊 **即時監控** | 50 位模擬病人（手術室＋恢復室），生命徵象每秒更新；卡片顏色顯示 AI 查房結果；點開可看趨勢圖、工具判讀、模擬處置 |
| 🩺 **AI 自動查房** | 可設定「每隔 N 分鐘」或「每天固定時間點」查房、限定時段與範圍、危急病人額外複查；每次查房產生報告、更新警示、跳出通知 |
| 💬 **AI 助理對話** | 查詢病人、解讀結果、立即查房、修改查房設定、調整工具門檻、建立規則與技能；建議處置時需使用者按「確認」才執行 |
| 🧰 **工具庫** | 內建 12 個規則工具、4 個臨床評分、3 個 AI 模型（機器學習／深度學習），全部可調門檻、啟用／停用 |
| ➕ **免寫程式新增工具** | 表單組合條件建立規則；選擇預測目標＋特徵＋演算法（含神經網路）即可訓練 AI 模型；也可上傳模型檔 |
| 📘 **技能庫** | 用一般文字撰寫 SOP，綁定觸發工具或關鍵字；內建 8 個示範技能 |
| 🎬 **情境演練** | 一鍵製造惡性高熱、急性出血、過敏性休克等 17 種事件；調整模擬速度；匯出資料集 CSV |
| 🗄️ **資料庫** | 設定、規則、技能、AI 模型、查房報告、警示、對話、處置建議，以及即時生命徵象資料集全部存在 PostgreSQL |

### 內建示範工具

| 類別 | 工具 |
|---|---|
| 規則式 | 低血壓偵測、高血壓偵測、心跳與心律監測、血氧監測、通氣監測、惡性高熱早期警訊、麻醉深度（BIS）、體溫、尿量、出血量、檢驗值判讀、恢復室疼痛評估 |
| 臨床評分 | 休克指數、Aldrete 恢復室轉出評分、早期預警分數（NEWS 改良）、Apfel PONV 風險 |
| 機器學習 | 低血壓預測 AI（梯度提升樹，預測 5 分鐘內低血壓）、多參數異常偵測 AI（孤立森林，非監督式） |
| 深度學習 | 病況惡化預測神經網路（讀取 15 分鐘生命徵象序列，預測 10 分鐘內惡化） |
| 自訂規則（示範） | 高齡病人血壓過高、糖尿病病人血糖控制、EtCO₂ 快速上升、恢復室停留過久 |
| 自訂 AI 模型（示範） | 低血氧預警模型（隨機森林，用免寫程式訓練功能建立） |
| Python 外掛（示範） | 術中輸液平衡（`backend/plugins/fluid_balance.py`） |

### 內建示範技能

例行查房報告格式、術中低血壓處置、大量出血處置、惡性高熱處置、低血氧與通氣異常處置、恢復室轉出評估、SBAR 交班、過敏性休克處置。

---

## 三、5 分鐘展示流程

1. 「AI 查房」→ 查房間隔設為 **1 分鐘**
2. 「情境演練」→ 點 **惡性高熱**（或急性出血），記下被選中的床位
3. 「即時監控」→ 觀察該病人 EtCO₂、心跳、體溫逐漸上升
4. 下一次自動查房時，AI 標示危急、跳出通知，並依「惡性高熱處置」技能撰寫建議
5. 右側 AI 助理：「OR-xx 怎麼了？該怎麼處理？」→ AI 提出處置建議卡片 → 按「確認執行」→ 生命徵象恢復
6. 對 AI 說：「幫我建立規則：糖尿病病人血糖超過 250 列為危急」→ 到工具庫看到新規則

---

## 四、系統架構

```mermaid
flowchart LR
  subgraph FE[前端 Vue 3]
    UI[頁面與元件] <--> STORE[Pinia 即時狀態]
  end
  subgraph BE[後端 FastAPI]
    API[REST /api] --- WS[WebSocket /ws]
    SIM[即時模擬器<br>50 位病人] --> REC[資料紀錄服務]
    SIM --> CTX[病人資料介面]
    CTX --> TOOLS[工具庫<br>規則／評分／ML／DL]
    SCHED[查房排程] --> ROUND[查房引擎]
    TOOLS --> ROUND
    SKILLS[技能庫] --> ROUND
    CHAT[AI 助理<br>工具呼叫代理迴圈] --> TOOLS
    ROUND --> LLM[Claude]
    CHAT --> LLM
    REPO[Repositories<br>SQLAlchemy ORM]
    REC --> REPO
    ROUND --> REPO
    CHAT --> REPO
  end
  DB[(PostgreSQL)]
  UI <-->|HTTP / WebSocket| API
  REPO <--> DB
```

- **前後端只透過 `/api/*`（REST）與 `/ws`（WebSocket）溝通。** 正式執行時由 FastAPI 提供 Vue 建置後的網頁（`frontend/dist`）。
- **AI 看不到模擬器內部的「答案」**：工具只能讀取生命徵象、檢驗、病人資料，必須自己推斷病況；真實事件另存在 `clinical_events` 資料表，可用來驗證 AI。
- **沒有 API 金鑰也能運作**：查房、工具、警示照常；摘要改用範本，對話改用關鍵字理解。
- AI 模型：Claude Opus 5（可在設定改為 Sonnet 5／Haiku 4.5），使用 adaptive thinking，並啟用伺服器端 refusal fallback。

### 資料夾

```
anes-agent/
├── start.command / start.bat / stop.command / stop.bat   一鍵啟動／關閉（Docker）
├── docker-compose.yml       PostgreSQL + 應用程式
├── Dockerfile               建置 Vue 前端 → 放進 Python 執行環境
├── frontend/                前端（Vue 3 + TypeScript + Vite + Vue Router + Pinia）
│   └── src/
│       ├── api/             API 呼叫、型別、WebSocket
│       ├── stores/          即時狀態
│       ├── views/           7 個頁面
│       ├── components/      病人卡片、病人視窗、規則建立器、模型訓練、技能編輯器、聊天面板…
│       └── utils/           圖表、Markdown、格式化
└── backend/                 後端（FastAPI + SQLAlchemy 2.0 async + Alembic）
    ├── app/
    │   ├── main.py          建立應用程式、掛載路由與前端
    │   ├── state.py         組裝各服務、背景工作（模擬、查房排程、資料紀錄）
    │   ├── api/             路由：patients、simulation、tools、skills、rounds、settings、chat、export、ws
    │   ├── db/              ORM 資料表（models.py）、連線、自動遷移、示範資料匯入
    │   ├── repositories/    資料存取（knowledge、agent_records、dataset）
    │   ├── services/        recorder：把即時模擬資料批次寫入資料庫
    │   ├── simulator/       病人產生、生理模擬、臨床事件與處置
    │   ├── tools/           工具介面、內建規則、臨床評分、免寫程式規則引擎、AI 模型工具、工具庫
    │   ├── ml/              特徵計算、訓練資料產生、模型訓練
    │   ├── skills/          技能解析與觸發
    │   └── agent/           Claude 連線、查房引擎、AI 助理、離線模式、處置確認
    ├── migrations/          Alembic 資料庫遷移
    ├── seeds/               第一次啟動匯入的示範規則、技能、AI 模型
    ├── plugins/             Python 外掛工具
    └── tests/               自動化測試（使用獨立的 PostgreSQL 測試資料庫）
```

### 資料表

| 分類 | 資料表 | 內容 |
|---|---|---|
| 設定與知識 | `app_settings`、`tool_configs` | 查房／模擬／AI 設定；工具啟用狀態與門檻 |
| | `rules`、`skills`、`ml_models` | 自訂規則、技能（SOP）、AI 模型（說明＋模型檔） |
| 即時資料集 | `simulation_runs`、`patients` | 每次模擬、病人基本資料與進出手術室／恢復室時間 |
| | `vital_signs` | 生命徵象時間序列（每 5 秒模擬時間一筆） |
| | `lab_results`、`interventions`、`patient_notes` | 檢驗、處置、備註 |
| | `clinical_events` | 模擬器內部的真實事件（AI 看不到，供驗證） |
| AI Agent 紀錄 | `round_reports`、`alerts` | 查房報告（含逐位病人發現與摘要）、警示歷程 |
| | `action_proposals`、`chat_messages` | AI 處置建議與使用者決定、對話紀錄 |

---

## 五、給開發者

### 開發模式（不透過 Docker 跑應用程式）

```bash
docker compose up -d db                # 只啟動 PostgreSQL（連接埠 55432）

cd backend
uv run python -m app                   # 後端 http://127.0.0.1:8000（啟動時自動遷移並匯入示範資料）
uv run pytest -q                       # 測試（自動建立 anes_test 資料庫）

cd ../frontend
npm install
npm run dev                            # 前端開發伺服器，/api 與 /ws 會轉到後端
npm run build                          # 建置到 frontend/dist，由後端提供
```

環境變數：`DATABASE_URL`（預設 `postgresql+asyncpg://anes:anes@127.0.0.1:55432/anes`）、`ANTHROPIC_API_KEY`、`PORT`、`HOST`、`NO_BROWSER=1`、`ANES_FRONTEND_DIR`。

### 資料庫遷移

修改 `backend/app/db/models.py` 後：

```bash
cd backend
uv run alembic revision --autogenerate -m "說明變更"
uv run alembic upgrade head            # 系統啟動時也會自動執行
```

測試 `test_migrations_match_models` 會檢查 ORM 與遷移檔是否一致。

### 重新訓練內建模型

```bash
cd backend
uv run python -m app.ml.trainer        # 寫入 seeds/models/builtin，下次啟動自動更新資料庫
```

### 新增 Python 外掛工具

在 `backend/plugins/` 放一個 `.py` 檔，繼承 `BaseTool` 並實作 `run(ctx, params)`，重新啟動或在工具庫按「重新載入」。範例見 `backend/plugins/fluid_balance.py`。

```python
from app.tools.base import BaseTool, Finding, ParamSpec

class MyTool(BaseTool):
    id = "plugin_my_tool"
    name = "我的工具"
    description = "工具用途"
    params = [ParamSpec("threshold", "門檻", 100, unit="mmHg")]

    def run(self, ctx, params):
        findings = []
        if ctx.vitals["sbp"] > params["threshold"]:
            findings.append(Finding("warning", "標題", "內容", "建議"))
        return self.result(ctx, "摘要", findings)
```

### 示範資料格式

- 規則：`backend/seeds/rules/*.json`（欄位與網頁「新增規則」相同）
- 技能：`backend/seeds/skills/*.md`（開頭 YAML：`id`、`name`、`description`、`triggers`、`use_in`，下面是 Markdown 內容）
- 模型：`backend/seeds/models/{builtin,custom}/*.json` + 同名 `.joblib`

示範資料只在資料表為空時匯入；之後在網頁上新增、修改、刪除的內容都存在資料庫。
