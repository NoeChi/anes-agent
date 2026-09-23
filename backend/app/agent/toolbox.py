"""AI 助理可以使用的工具（給 Claude 的 function calling 定義與執行）。

資料查詢方法（patient_rows、patient_detail…）回傳 Python 物件，離線模式也共用這些方法。
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import numpy as np

from ..bus import EventBus
from ..config import Settings, SettingsError
from ..simulator.engine import Patient, SimulationEngine
from ..simulator.events import INTERVENTIONS
from ..skills.manager import SkillError, SkillManager
from ..tools.base import SEVERITY_LABEL
from ..tools.context import PatientContext
from ..tools.registry import ToolRegistry
from ..tools.rule_engine import OPERATORS, RULE_FIELDS, RuleError
from .actions import ActionStore
from .rounds import RoundManager

TREND_FIELDS = ["hr", "sbp", "dbp", "map", "spo2", "etco2", "rr", "temp", "bis", "pain"]
FIELD_LABEL = {"hr": "心跳", "sbp": "收縮壓", "dbp": "舒張壓", "map": "MAP", "spo2": "SpO₂", "etco2": "EtCO₂",
               "rr": "呼吸", "temp": "體溫", "bis": "BIS", "pain": "疼痛"}


class ToolError(Exception):
    pass


def hhmm(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts).strftime("%H:%M")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _definitions() -> list[dict]:
    patient_id = {"type": "string", "description": "病號（如 P012）或床位（如 OR-05、PACU-03）"}
    all_ops = sorted({o[0] for ops in OPERATORS.values() for o in ops})
    field_lines = "；".join(f"{k}={v[0]}（{v[2]}）" for k, v in RULE_FIELDS.items())
    return [
        {
            "name": "list_patients",
            "description": "列出目前病人清單：床位、病號、年齡性別、手術、麻醉階段、主要生命徵象，以及最近查房的警示狀態。"
                           "使用者用床位或口語描述病人時，先用此工具找到正確病號。",
            "input_schema": {"type": "object", "properties": {
                "location": {"type": "string", "enum": ["all", "OR", "PACU"], "description": "all=全部、OR=手術室、PACU=恢復室"},
                "only_with_alerts": {"type": "boolean", "description": "只列出最近查房有危急或警示的病人"},
            }},
        },
        {
            "name": "get_patient",
            "description": "取得單一病人完整資料：基本資料、共病、過敏、手術與麻醉方式、最新生命徵象、藥物、輸液／出血／尿量、最近檢驗、處置紀錄、備註與進行中警示。",
            "input_schema": {"type": "object", "properties": {"patient_id": patient_id}, "required": ["patient_id"]},
        },
        {
            "name": "get_vital_trend",
            "description": "取得病人近 N 分鐘的生命徵象趨勢（每分鐘一筆），並附最小值、最大值、起訖變化。",
            "input_schema": {"type": "object", "properties": {
                "patient_id": patient_id,
                "minutes": {"type": "integer", "minimum": 5, "maximum": 180, "description": "預設 30"},
                "fields": {"type": "array", "items": {"type": "string", "enum": TREND_FIELDS}, "description": "不填則回傳主要欄位"},
            }, "required": ["patient_id"]},
        },
        {
            "name": "list_tools",
            "description": "列出工具庫所有工具（規則、臨床評分、機器學習、深度學習、自訂規則、自訂模型、Python 外掛）：代碼、名稱、類別、是否啟用、參數與目前數值。",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "run_tools",
            "description": "對指定病人立即執行工具並回傳判讀結果（含 AI 模型預測機率）。tool_ids 不填則執行所有啟用中的工具。",
            "input_schema": {"type": "object", "properties": {
                "patient_id": patient_id,
                "tool_ids": {"type": "array", "items": {"type": "string"}},
            }, "required": ["patient_id"]},
        },
        {
            "name": "update_tool",
            "description": "修改工具的啟用狀態或參數（例如把 ioh_detector 的 map_threshold 改為 60）。請先用 list_tools 確認工具代碼與參數名稱。",
            "input_schema": {"type": "object", "properties": {
                "tool_id": {"type": "string"},
                "enabled": {"type": "boolean"},
                "params": {"type": "object", "description": "參數名稱→數值"},
            }, "required": ["tool_id"]},
        },
        {
            "name": "create_rule",
            "description": "建立免寫程式的自訂規則工具，建立後查房時會自動執行。"
                           f"可用欄位：{field_lines}。"
                           "number 欄位的 op 可用 > >= < <= == != rises_by falls_by（後兩者需 window_min）；"
                           "bool 欄位用 is_true / is_false（不需 value）；select 欄位用 == / !=，"
                           "location 值為 OR/PACU，phase 值為 induction/maintenance/emergence/pacu，anes_class 值為 GA/NEURAXIAL/MAC，sex 值為 M/F；"
                           "text 欄位用 contains / == / !=。生命徵象欄位可加 duration_min 表示需持續幾分鐘。"
                           "message 可用 {欄位代碼} 帶入目前數值。",
            "input_schema": {"type": "object", "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                "logic": {"type": "string", "enum": ["all", "any"], "description": "all=全部條件符合、any=任一符合"},
                "conditions": {"type": "array", "items": {"type": "object", "properties": {
                    "field": {"type": "string", "enum": list(RULE_FIELDS)},
                    "op": {"type": "string", "enum": all_ops},
                    "value": {"type": ["number", "string", "null"]},
                    "duration_min": {"type": "number"},
                    "window_min": {"type": "number"},
                }, "required": ["field", "op"]}},
                "locations": {"type": "array", "items": {"type": "string", "enum": ["OR", "PACU"]}},
                "message": {"type": "string"},
                "suggestion": {"type": "string"},
            }, "required": ["name", "severity", "logic", "conditions"]},
        },
        {
            "name": "list_skills",
            "description": "列出所有技能（SOP）：代碼、名稱、用途、觸發工具與關鍵字、是否啟用。",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "load_skill",
            "description": "讀取技能完整內容。回答處置流程或需要依 SOP 的問題前，先載入相關技能。",
            "input_schema": {"type": "object", "properties": {"skill_id": {"type": "string"}}, "required": ["skill_id"]},
        },
        {
            "name": "save_skill",
            "description": "建立或修改技能（SOP 文件）。body 用 Markdown，建議包含「何時使用」「評估步驟」「建議處置」「回報重點」。"
                           "修改既有技能時提供 skill_id（先 load_skill 取得原內容）。trigger_tools 填工具代碼，查房時該工具有發現就會套用此技能。",
            "input_schema": {"type": "object", "properties": {
                "skill_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "body": {"type": "string"},
                "trigger_tools": {"type": "array", "items": {"type": "string"}},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "use_in": {"type": "array", "items": {"type": "string", "enum": ["rounds", "chat"]}},
            }, "required": ["name", "description", "body"]},
        },
        {
            "name": "get_latest_round",
            "description": "取得最近一次查房報告：時間、危急與警示人數、查房摘要，以及每位有發現病人的判讀結果。",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_alerts",
            "description": "列出進行中的警示（依嚴重度排序），含首次出現時間與是否已確認。"
                           "這是跨查房追蹤的清單：警示要連續兩輪查房都沒再出現才會緩解，所以可能包含最近一次查房已判定正常的病人。"
                           "要回答「目前哪些病人危急」請改用 list_patients 或 get_latest_round。",
            "input_schema": {"type": "object", "properties": {
                "severity": {"type": "string", "enum": ["all", "critical", "warning"]},
            }},
        },
        {
            "name": "acknowledge_alerts",
            "description": "把某位病人所有進行中的警示標記為「已確認」（使用者表示已知道或已處理時使用）。",
            "input_schema": {"type": "object", "properties": {"patient_id": patient_id}, "required": ["patient_id"]},
        },
        {
            "name": "run_round_now",
            "description": "立即執行一次查房：對範圍內病人執行所有啟用中的工具，回傳各病人的發現。",
            "input_schema": {"type": "object", "properties": {
                "scope": {"type": "string", "enum": ["all", "OR", "PACU"]},
            }},
        },
        {
            "name": "get_round_settings",
            "description": "查看自動查房設定（模式、間隔或時間點、時段、範圍、AI 摘要、危急複查）與下一次查房時間。",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "update_round_settings",
            "description": "修改自動查房設定，只需提供要改的欄位。mode=interval：每隔 interval_minutes 分鐘查房；"
                           "mode=schedule：每天在 times 的時間點（HH:MM）查房。window_enabled/window_start/window_end 限定查房時段；"
                           "scope 查房範圍；ai_summary：off 不用 AI 摘要、when_findings 有發現才用、always 每次都用；"
                           "critical_recheck_minutes：危急病人額外複查間隔（0 關閉）；enabled：是否啟用自動查房。",
            "input_schema": {"type": "object", "properties": {
                "enabled": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["interval", "schedule"]},
                "interval_minutes": {"type": "number", "minimum": 0.5, "maximum": 720},
                "times": {"type": "array", "items": {"type": "string", "description": "HH:MM"}},
                "window_enabled": {"type": "boolean"},
                "window_start": {"type": "string"},
                "window_end": {"type": "string"},
                "scope": {"type": "string", "enum": ["all", "OR", "PACU"]},
                "ai_summary": {"type": "string", "enum": ["off", "when_findings", "always"]},
                "critical_recheck_minutes": {"type": "number", "minimum": 0, "maximum": 60},
            }},
        },
        {
            "name": "propose_intervention",
            "description": "向使用者提出一項處置建議。此工具不會直接執行：畫面會出現確認按鈕，由使用者決定是否執行。"
                           "可用處置：" + "；".join(f"{k}={v['label']}" for k, v in INTERVENTIONS.items()),
            "input_schema": {"type": "object", "properties": {
                "patient_id": patient_id,
                "intervention": {"type": "string", "enum": list(INTERVENTIONS)},
                "reason": {"type": "string", "description": "建議理由（附關鍵數值）"},
            }, "required": ["patient_id", "intervention", "reason"]},
        },
        {
            "name": "add_patient_note",
            "description": "在病人紀錄新增一筆 AI 助理備註。",
            "input_schema": {"type": "object", "properties": {
                "patient_id": patient_id, "note": {"type": "string"},
            }, "required": ["patient_id", "note"]},
        },
    ]


STEP_LABELS = {
    "list_patients": "查看病人清單",
    "get_patient": "查看病人 {patient_id}",
    "get_vital_trend": "查看 {patient_id} 生命徵象趨勢",
    "list_tools": "查看工具庫",
    "run_tools": "對 {patient_id} 執行工具判讀",
    "update_tool": "修改工具 {tool_id}",
    "create_rule": "建立自訂規則「{name}」",
    "list_skills": "查看技能清單",
    "load_skill": "讀取技能 {skill_id}",
    "save_skill": "儲存技能「{name}」",
    "get_latest_round": "查看最近查房報告",
    "list_alerts": "查看警示",
    "acknowledge_alerts": "確認 {patient_id} 的警示",
    "run_round_now": "立即執行查房",
    "get_round_settings": "查看查房設定",
    "update_round_settings": "修改查房設定",
    "propose_intervention": "建議處置（{patient_id}）",
    "add_patient_note": "新增 {patient_id} 備註",
}


class AgentToolbox:
    def __init__(self, engine: SimulationEngine, registry: ToolRegistry, skills: SkillManager, rounds: RoundManager,
                 actions: ActionStore, settings: Settings, bus: EventBus):
        self.engine = engine
        self.registry = registry
        self.skills = skills
        self.rounds = rounds
        self.actions = actions
        self.settings = settings
        self.bus = bus
        self._definitions = _definitions()

    def definitions(self) -> list[dict]:
        return self._definitions

    @staticmethod
    def step_label(name: str, args: dict) -> str:
        template = STEP_LABELS.get(name, name)
        try:
            return template.format(**{k: v for k, v in args.items() if isinstance(v, (str, int, float))})
        except (KeyError, IndexError):
            return re.sub(r"\{\w+\}", "", template)

    # ---------- 共用資料方法 ----------
    def resolve(self, ref: str) -> Patient:
        ref = str(ref or "").strip().upper().replace(" ", "")
        p = self.engine.get(ref)
        if p:
            return p
        m = re.fullmatch(r"P?0*(\d{1,4})", ref)
        if m:
            p = self.engine.get(f"P{int(m.group(1)):03d}")
            if p:
                return p
        m = re.fullmatch(r"(OR|PACU)[-_]?0*(\d{1,2})", ref)
        if m:
            p = self.engine.get(f"{m.group(1)}-{int(m.group(2)):02d}")
            if p:
                return p
        raise ToolError(f"找不到病人「{ref}」。病人可能已轉出，請用 list_patients 查詢目前病人。")

    def status_of(self, pid: str) -> dict:
        st = self.rounds.patient_status.get(pid)
        if not st:
            return {"嚴重度": "尚未查房"}
        return {"嚴重度": {"normal": "無警示", **SEVERITY_LABEL}.get(st["severity"], st["severity"]),
                "危急": st["critical"], "警示": st["warning"], "主要問題": st["titles"], "查房時間": hhmm(st["checked_at"])}

    def patient_rows(self, location: str = "all", only_with_alerts: bool = False) -> list[dict]:
        rows = []
        for p in self.engine.sorted_patients():
            if location in ("OR", "PACU") and p.location != location:
                continue
            st = self.rounds.patient_status.get(p.pid, {})
            if only_with_alerts and st.get("severity") not in ("critical", "warning"):
                continue
            b = p.brief()
            v = b["vitals"]
            rows.append({
                "床位": b["bed"], "病號": b["pid"], "病人": f"{b['age']}歲{'男' if b['sex'] == 'M' else '女'}",
                "手術": b["surgery"], "麻醉": b["anes_label"], "階段": f"{b['phase_label']} {b['minutes']} 分鐘",
                "生命徵象": f"HR {v['hr']}｜BP {v['sbp']}/{v['dbp']}（MAP {v['map']}）｜SpO₂ {v['spo2']}｜EtCO₂ {v['etco2']}"
                           + (f"｜BIS {v['bis']}" if v["bis"] is not None else "") + f"｜T {v['temp']}"
                           + (f"｜疼痛 {v['pain']}" if v["pain"] is not None else ""),
                "狀態": self.status_of(p.pid),
            })
        return rows

    def patient_detail(self, p: Patient) -> dict:
        d = self.engine.detail(p.pid)
        d["interventions"] = [{"時間": hhmm(i["t"]), "處置": i["label"], "執行者": i["by"]} for i in d["interventions"]]
        d["notes"] = [{"時間": hhmm(n["t"]), "內容": n["text"], "作者": n["by"]} for n in d["notes"]]
        if d["labs"]:
            d["labs"] = {**d["labs"], "t": hhmm(d["labs"]["t"])}
        d.pop("lab_history", None)
        d["sim_time"] = hhmm(d["sim_time"])
        d["alerts"] = [{"嚴重度": a["severity_label"], "標題": a["title"], "內容": a["detail"], "首次出現": hhmm(a["first_seen"]),
                        "已確認": a["acknowledged"]} for a in self.rounds.list_alerts() if a["pid"] == p.pid]
        return d

    def trend(self, p: Patient, minutes: int = 30, fields: list[str] | None = None) -> dict:
        minutes = int(max(5, min(180, minutes or 30)))
        fields = [f for f in (fields or ["hr", "sbp", "map", "spo2", "etco2", "rr", "temp", "bis", "pain"]) if f in TREND_FIELDS]
        ts, cols = p.history.arrays(since=self.engine.t - minutes * 60)
        if len(ts) < 2:
            return {"說明": "資料不足"}
        grid = np.arange(ts[-1], max(ts[0], ts[-1] - minutes * 60) - 1, -60)[::-1]
        table = []
        stats = {}
        for f in fields:
            x = cols[f]
            m = ~np.isnan(x)
            if m.sum() < 2:
                continue
            vals = np.interp(grid, ts[m], x[m])
            stats[FIELD_LABEL[f]] = {"最低": round(float(x[m].min()), 1), "最高": round(float(x[m].max()), 1),
                                     "起": round(float(vals[0]), 1), "目前": round(float(vals[-1]), 1),
                                     "變化": round(float(vals[-1] - vals[0]), 1)}
        for i, t in enumerate(grid):
            row = {"時間": hhmm(t)}
            for f in fields:
                x = cols[f]
                m = ~np.isnan(x)
                if m.sum() >= 2:
                    row[FIELD_LABEL[f]] = round(float(np.interp(t, ts[m], x[m])), 1 if f == "temp" else 0)
            table.append(row)
        return {"病號": p.pid, "床位": p.bed, "分鐘數": minutes, "統計": stats, "每分鐘": table}

    def run_tools(self, p: Patient, tool_ids: list[str] | None = None) -> list[dict]:
        ctx = PatientContext(p)
        if tool_ids:
            tools = [self.registry.get(t) for t in tool_ids]
            missing = [tid for tid, t in zip(tool_ids, tools) if t is None]
            if missing:
                raise ToolError(f"找不到工具：{', '.join(missing)}（請用 list_tools 查詢代碼）")
        else:
            tools = [t for t in self.registry.list() if self.registry.enabled(t.id)]
        out = []
        for tool in tools:
            res = self.registry.run(tool, ctx)
            item = {"工具": tool.name, "代碼": tool.id, "類別": tool.describe()["category_label"]}
            if not res.applicable:
                item["結果"] = f"不適用：{res.summary}"
            elif not res.ok:
                item["結果"] = f"錯誤：{res.error}"
            else:
                item["結果"] = res.summary
                if res.findings:
                    item["發現"] = [{"嚴重度": f.to_dict()["severity_label"], "標題": f.title, "內容": f.detail, "建議": f.suggestion}
                                  for f in res.findings]
            out.append(item)
        out.sort(key=lambda i: ("發現" not in i, i["結果"].startswith("不適用")))
        return out

    def tools_overview(self) -> list[dict]:
        out = []
        for t in self.registry.list():
            d = self.registry.describe(t)
            out.append({"代碼": d["id"], "名稱": d["name"], "類別": d["category_label"], "啟用": d["enabled"],
                        "用途": d["description"],
                        "參數": [{"名稱": p["key"], "說明": p["label"], "目前": d["param_values"][p["key"]], "單位": p["unit"]}
                               for p in d["params"]]})
        return out

    def round_payload(self, report: dict | None) -> dict:
        if not report:
            return {"說明": "尚未執行過查房"}
        return {
            "編號": report["id"], "類型": report["trigger_label"], "範圍": report["scope"],
            "查房時間": hhmm(report["wall_time"]), "模擬時間": hhmm(report["sim_time"]),
            "查看人數": report["patients_checked"], "危急": report["n_critical"], "警示": report["n_warning"],
            "新問題": report["new_alerts"], "已緩解": report["resolved_alerts"],
            "摘要來源": "AI" if report["summary_source"] == "ai" else "系統範本",
            "摘要": report["summary_md"],
            "病人發現": [{"床位": r["bed"], "病號": r["pid"], "病人": r["label"],
                        "發現": [f"[{f['severity_label']}] {f['title']}：{f['detail']}" for f in r["findings"]],
                        "適用技能": [s["name"] for s in r["skills"]]} for r in report["patients"]][:25],
        }

    # ---------- 執行 ----------
    async def execute(self, name: str, args: dict, session_id: str | None = None) -> str:
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            raise ToolError(f"未知的工具：{name}")
        return _dump(await handler(args or {}, session_id))

    async def _t_list_patients(self, a, _):
        rows = self.patient_rows(a.get("location", "all"), bool(a.get("only_with_alerts")))
        return {"模擬時間": hhmm(self.engine.t), "人數": len(rows), "病人": rows}

    async def _t_get_patient(self, a, _):
        return self.patient_detail(self.resolve(a.get("patient_id")))

    async def _t_get_vital_trend(self, a, _):
        return self.trend(self.resolve(a.get("patient_id")), a.get("minutes") or 30, a.get("fields"))

    async def _t_list_tools(self, a, _):
        return self.tools_overview()

    async def _t_run_tools(self, a, _):
        p = self.resolve(a.get("patient_id"))
        return {"病號": p.pid, "床位": p.bed, "判讀時間": hhmm(self.engine.t), "結果": self.run_tools(p, a.get("tool_ids"))}

    async def _t_update_tool(self, a, _):
        tool_id = a.get("tool_id", "")
        if not self.registry.get(tool_id):
            raise ToolError(f"找不到工具 {tool_id}，請用 list_tools 查詢")
        d = await self.registry.update(tool_id, a.get("enabled"), a.get("params"))
        await self.bus.publish("tools_changed", {"id": tool_id})
        return {"已更新": d["name"], "啟用": d["enabled"], "目前參數": d["param_values"]}

    async def _t_create_rule(self, a, _):
        try:
            spec = await self.registry.add_rule({**a, "author": "AI 助理"})
        except RuleError as exc:
            raise ToolError(f"規則格式錯誤：{exc}") from None
        tool = self.registry.get(spec["id"])
        await self.bus.publish("tools_changed", {"id": spec["id"]})
        return {"已建立規則": spec["name"], "代碼": spec["id"], "判斷邏輯": tool.how_it_works if tool else ""}

    async def _t_list_skills(self, a, _):
        return [{"代碼": s["id"], "名稱": s["name"], "用途": s["description"], "啟用": s["enabled"],
                 "觸發工具": s["triggers"]["tools"], "關鍵字": s["triggers"]["keywords"], "每次查房套用": s["triggers"]["always"]}
                for s in self.skills.list()]

    async def _t_load_skill(self, a, _):
        s = self.skills.get(a.get("skill_id", ""))
        if not s:
            raise ToolError("找不到此技能，請用 list_skills 查詢代碼")
        return {"名稱": s["name"], "內容": s["body"]}

    async def _t_save_skill(self, a, _):
        existing = self.skills.get(a.get("skill_id") or "") or {}
        data = {
            "id": existing.get("id"),
            "name": a.get("name"),
            "description": a.get("description"),
            "body": a.get("body"),
            "enabled": existing.get("enabled", True),
            "triggers": {
                "tools": a.get("trigger_tools", existing.get("triggers", {}).get("tools", [])),
                "keywords": a.get("keywords", existing.get("triggers", {}).get("keywords", [])),
                "always": existing.get("triggers", {}).get("always", False),
            },
            "use_in": a.get("use_in") or existing.get("use_in") or ["rounds", "chat"],
            "author": existing.get("author", "AI 助理"),
        }
        try:
            s = await self.skills.save(data)
        except SkillError as exc:
            raise ToolError(str(exc)) from None
        await self.bus.publish("skills_changed", {"id": s["id"]})
        return {"已儲存技能": s["name"], "代碼": s["id"]}

    async def _t_get_latest_round(self, a, _):
        return self.round_payload(self.rounds.latest())

    async def _t_list_alerts(self, a, _):
        items = self.rounds.list_alerts("active", a.get("severity") or "all")
        return {"進行中警示": len(items), "警示": [
            {"床位": x["bed"], "病號": x["pid"], "嚴重度": x["severity_label"], "標題": x["title"], "內容": x["detail"],
             "工具": x["tool_name"], "首次出現": hhmm(x["first_seen"]), "已確認": x["acknowledged"]} for x in items[:40]]}

    async def _t_acknowledge_alerts(self, a, _):
        p = self.resolve(a.get("patient_id"))
        n = await self.rounds.acknowledge(pid=p.pid)
        await self.bus.publish("alerts_changed", {"pid": p.pid})
        return {"病號": p.pid, "已確認警示數": n}

    async def _t_run_round_now(self, a, _):
        report = await self.rounds.run_round("agent", scope=a.get("scope") or "all", ai_summary="off")
        payload = self.round_payload(report)
        payload.pop("摘要", None)
        return payload

    async def _t_get_round_settings(self, a, _):
        cfg = self.settings.section("rounds")
        info = self.rounds.schedule_info()
        return {"設定": cfg, "下一次查房": hhmm(info["next_due"]) if info["next_due"] else "未排程（自動查房關閉或不在時段內）",
                "距離下一次（秒）": info["seconds_to_next"], "上一次查房": hhmm(info["last_round"])}

    async def _t_update_round_settings(self, a, _):
        allowed = {"enabled", "mode", "interval_minutes", "times", "window_enabled", "window_start", "window_end",
                   "scope", "ai_summary", "critical_recheck_minutes"}
        values = {k: v for k, v in a.items() if k in allowed}
        if not values:
            raise ToolError("沒有提供要修改的設定")
        try:
            cfg = await self.settings.update("rounds", values)
        except SettingsError as exc:
            raise ToolError(str(exc)) from None
        await self.bus.publish("settings_changed", self.settings.public())
        info = self.rounds.schedule_info()
        return {"已更新設定": cfg, "下一次查房": hhmm(info["next_due"]) if info["next_due"] else "未排程"}

    async def _t_propose_intervention(self, a, session_id):
        p = self.resolve(a.get("patient_id"))
        try:
            action = await self.actions.create(p.pid, a.get("intervention", ""), a.get("reason", ""), "chat", session_id)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        await self.bus.publish("pending_action", action)
        return {"狀態": "已送出建議，畫面上會顯示確認按鈕，等待使用者決定", "建議編號": action["id"],
                "病人": f"{p.bed}（{p.pid}）", "處置": action["label"]}

    async def _t_add_patient_note(self, a, _):
        p = self.resolve(a.get("patient_id"))
        note = str(a.get("note", "")).strip()
        if not note:
            raise ToolError("備註內容不可空白")
        self.engine.add_note(p.pid, note, "AI 助理")
        return {"已新增備註": p.pid}
