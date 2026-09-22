"""自動查房：依使用者設定的時間規則，定期對病人執行所有啟用中的工具，整理發現、更新警示並產生查房報告。

查房報告與警示存入資料庫；記憶體保留「本次模擬」的警示狀態與最近報告，供每次查房比對與畫面快速讀取。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from ..bus import EventBus
from ..config import Settings
from ..repositories import agent_records as records
from ..repositories.agent_records import TRIGGER_LABEL
from ..simulator.engine import SimulationEngine
from ..skills.manager import SkillManager
from ..tools.base import SEVERITY_LABEL, SEVERITY_ORDER
from ..tools.context import PatientContext
from ..tools.registry import ToolRegistry
from .llm import LLMClient, friendly_error

SEV_ICON = {"critical": "🔴", "warning": "🟠", "info": "🔵"}

ROUND_SYSTEM = """你是麻醉科 AI 查房助理，負責把自動查房的工具判讀結果整理成給麻醉醫師看的查房摘要。
資料全部來自模擬系統（非真實病人）。只能使用提供的資料，不可編造數值、病史或未提供的檢查。
輸出使用繁體中文 Markdown，不要加前言或結語，直接輸出摘要內容。"""


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


@dataclass
class AlertState:
    key: str
    pid: str
    bed: str
    tool_id: str
    tool_name: str
    severity: str
    title: str
    detail: str
    suggestion: str
    first_seen: float
    last_seen: float
    sim_first: float
    sim_last: float
    status: str = "active"  # active / resolved
    acknowledged: bool = False
    resolved_at: float | None = None
    rounds_seen: int = 1
    missed: int = 0  # 連續幾次查房沒再出現（避免數值在門檻附近跳動時警示反覆出現／消失）
    db_id: int | None = None

    @property
    def id(self) -> str:
        return records.code("AL", self.db_id, 5) if self.db_id else ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("db_id")
        d["id"] = self.id
        d["severity_label"] = SEVERITY_LABEL[self.severity]
        return d


@dataclass
class PatientRound:
    pid: str
    bed: str
    label: str
    severity: str
    findings: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    new_count: int = 0
    tool_errors: list[str] = field(default_factory=list)


class RoundManager:
    def __init__(self, engine: SimulationEngine, registry: ToolRegistry, skills: SkillManager, llm: LLMClient,
                 settings: Settings, bus: EventBus, sessionmaker, recorder=None):
        self.engine = engine
        self.registry = registry
        self.skills = skills
        self.llm = llm
        self.settings = settings
        self.bus = bus
        self.sm = sessionmaker
        self.recorder = recorder
        self.reports: list[dict] = []  # 最近的報告（新→舊）
        self.alerts: dict[str, AlertState] = {}
        self.patient_status: dict[str, dict] = {}
        self.started_wall = time.time()
        self.last_full_round_wall: float | None = None
        self.last_recheck_wall = 0.0
        self.fired_slots: set[str] = set()
        self.lock = asyncio.Lock()
        self.busy = False

    @property
    def run_id(self) -> int | None:
        return self.recorder.run_id if self.recorder else None

    async def startup(self) -> None:
        await records.close_active_alerts(self.sm)
        self.reports = await records.list_reports(self.sm, 60)

    async def reset_run(self) -> None:
        """模擬重置：結束本次模擬的警示（資料庫保留紀錄），清空記憶體狀態。"""
        now = time.time()
        closing = []
        for a in self.alerts.values():
            if a.status == "active":
                a.status, a.resolved_at = "resolved", now
                closing.append(a)
        await records.save_alerts(self.sm, [a for a in closing if a.db_id], self.run_id)
        self.alerts.clear()
        self.patient_status.clear()

    # ---------- 排程 ----------
    def _in_window(self, dt: datetime, cfg: dict) -> bool:
        if not cfg["window_enabled"]:
            return True
        start, end = cfg["window_start"], cfg["window_end"]
        now = dt.strftime("%H:%M")
        return start <= now < end if start <= end else (now >= start or now < end)

    def next_due(self) -> float | None:
        cfg = self.settings.section("rounds")
        if not cfg["enabled"]:
            return None
        now = datetime.now()
        if cfg["mode"] == "interval":
            base = self.last_full_round_wall or self.started_wall
            due = datetime.fromtimestamp(base) + timedelta(minutes=cfg["interval_minutes"])
            # 已經逾期時保留原本的到期時間，不要改成「現在」：loop() 會拿自己取樣的時間跟這個
            # 回傳值比較，改成現在會讓 now >= due 永遠差幾微秒不成立，固定間隔查房因此不會觸發。
            # 對外顯示由 schedule_info() 的 max(0, …) 處理。
            for _ in range(2 * 24 * 60):
                if self._in_window(due, cfg):
                    return due.timestamp()
                due += timedelta(minutes=1)
            return None
        for day in (0, 1):
            date = (now + timedelta(days=day)).date()
            for hhmm in cfg["times"]:
                h, m = map(int, hhmm.split(":"))
                slot = datetime.combine(date, datetime.min.time()).replace(hour=h, minute=m)
                key = slot.strftime("%Y-%m-%d %H:%M")
                if key in self.fired_slots:
                    continue
                if slot >= now - timedelta(minutes=1) and self._in_window(slot, cfg):
                    return slot.timestamp()
        return None

    def schedule_info(self) -> dict:
        due = self.next_due()
        cfg = self.settings.section("rounds")
        return {
            "enabled": cfg["enabled"],
            "mode": cfg["mode"],
            "next_due": due,
            "seconds_to_next": None if due is None else max(0, round(due - time.time())),
            "last_round": self.last_full_round_wall,
            "busy": self.busy,
        }

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                cfg = self.settings.section("rounds")
                due = self.next_due()
                now = time.time()  # 取樣要在 next_due() 之後，否則逾期時差幾微秒就判斷不成立
                if due is not None and now >= due:
                    if cfg["mode"] == "schedule":
                        self.fired_slots.add(datetime.fromtimestamp(due).strftime("%Y-%m-%d %H:%M"))
                    await self.run_round("scheduled", scope=cfg["scope"])
                    continue
                recheck = cfg["critical_recheck_minutes"]
                if cfg["enabled"] and recheck > 0 and now - self.last_recheck_wall >= recheck * 60:
                    critical = [pid for pid, st in self.patient_status.items()
                                if st["severity"] == "critical" and pid in self.engine.patients]
                    if critical and self.last_full_round_wall and now - self.last_full_round_wall >= recheck * 60:
                        self.last_recheck_wall = now
                        await self.run_round("recheck", pids=critical, ai_summary="off")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 排程不能因單次錯誤停止
                print(f"[rounds] 排程錯誤：{type(exc).__name__}: {exc}")

    # ---------- 查房 ----------
    async def run_round(self, trigger: str = "manual", scope: str = "all", pids: list[str] | None = None,
                        ai_summary: str | None = None) -> dict:
        async with self.lock:
            self.busy = True
            try:
                return await self._run_round(trigger, scope, pids, ai_summary)
            finally:
                self.busy = False

    async def _run_round(self, trigger, scope, pids, ai_summary) -> dict:
        started = time.time()
        if self.recorder:
            await self.recorder.flush()  # 確保本次模擬與病人已寫入資料庫
        patients = self.engine.sorted_patients()
        if pids:
            wanted = set(pids)
            patients = [p for p in patients if p.pid in wanted]
        elif scope in ("OR", "PACU"):
            patients = [p for p in patients if p.location == scope]
        await self.bus.publish("round_started", {"trigger": trigger, "count": len(patients),
                                                 "label": TRIGGER_LABEL.get(trigger, trigger)})
        sim_now = self.engine.t
        checked = set()
        seen_keys = set()
        rows: list[PatientRound] = []
        new_alerts: list[AlertState] = []
        touched: dict[str, AlertState] = {}
        finding_alerts: list[tuple[dict, AlertState]] = []
        statuses: list[dict] = []
        tools_run = 0
        enabled_tools = [t for t in self.registry.list() if self.registry.enabled(t.id)]
        for i, p in enumerate(patients):
            ctx = PatientContext(p)
            checked.add(p.pid)
            findings, errors = [], []
            for tool in enabled_tools:
                res = self.registry.run(tool, ctx)
                if res.applicable:
                    tools_run += 1
                if not res.ok:
                    errors.append(f"{tool.name}：{res.error}")
                findings.extend(res.findings)
            row = PatientRound(p.pid, p.bed, ctx.label(), "normal", tool_errors=errors)
            for f in sorted(findings, key=lambda f: -SEVERITY_ORDER[f.severity]):
                d = f.to_dict()
                d["new"] = False
                if f.severity in ("warning", "critical"):
                    key = f"{p.pid}|{f.tool_id}|{f.title}"
                    seen_keys.add(key)
                    alert = self.alerts.get(key)
                    if alert is None or alert.status == "resolved":
                        alert = AlertState(key, p.pid, p.bed, f.tool_id, f.tool_name, f.severity, f.title, f.detail,
                                           f.suggestion, started, started, sim_now, sim_now)
                        self.alerts[key] = alert
                        new_alerts.append(alert)
                        d["new"] = True
                        row.new_count += 1
                    else:
                        if SEVERITY_ORDER[f.severity] > SEVERITY_ORDER[alert.severity]:
                            alert.acknowledged = False
                            new_alerts.append(alert)
                        alert.severity, alert.detail, alert.suggestion = f.severity, f.detail, f.suggestion
                        alert.last_seen, alert.sim_last, alert.bed = started, sim_now, p.bed
                        alert.rounds_seen += 1
                        alert.missed = 0
                    touched[key] = alert
                    finding_alerts.append((d, alert))
                row.findings.append(d)
            if findings:
                row.severity = max((f.severity for f in findings), key=lambda s: SEVERITY_ORDER[s])
            row.skills = [{"id": s["id"], "name": s["name"]} for s in self.skills.match_findings(findings)]
            rows.append(row)
            status = {
                "severity": row.severity,
                "critical": sum(f.severity == "critical" for f in findings),
                "warning": sum(f.severity == "warning" for f in findings),
                "info": sum(f.severity == "info" for f in findings),
                "titles": [f.title for f in findings if f.severity != "info"][:4],
                "round_id": None,
                "checked_at": started,
            }
            self.patient_status[p.pid] = status
            statuses.append(status)
            if i % 10 == 9:
                await asyncio.sleep(0)

        resolved = []
        for alert in self.alerts.values():
            if alert.status != "active":
                continue
            gone = alert.pid not in self.engine.patients
            if not gone and alert.pid in checked and alert.key not in seen_keys:
                alert.missed += 1
                touched[alert.key] = alert
            if gone or alert.missed >= 2:
                alert.status = "resolved"
                alert.resolved_at = started
                resolved.append(alert)
                touched[alert.key] = alert
        for pid in list(self.patient_status):
            if pid not in self.engine.patients:
                del self.patient_status[pid]
        await records.save_alerts(self.sm, list(touched.values()), self.run_id)
        for d, alert in finding_alerts:
            d["alert_id"] = alert.id
            d["acknowledged"] = alert.acknowledged
        if len(self.alerts) > 800:
            for key in [k for k, a in self.alerts.items() if a.status == "resolved"][:300]:
                del self.alerts[key]

        order = {"critical": 0, "warning": 1, "info": 2, "normal": 3}
        rows.sort(key=lambda r: (order[r.severity], -len(r.findings), r.bed))
        report = {
            "id": None,
            "db_id": None,
            "trigger": trigger,
            "trigger_label": TRIGGER_LABEL.get(trigger, trigger),
            "scope": "指定病人" if pids else {"all": "全部病人", "OR": "手術室", "PACU": "恢復室"}.get(scope, scope),
            "wall_time": started,
            "sim_time": sim_now,
            "duration_ms": 0,
            "patients_checked": len(patients),
            "tools_run": tools_run,
            "n_critical": sum(r.severity == "critical" for r in rows),
            "n_warning": sum(r.severity == "warning" for r in rows),
            "n_info": sum(r.severity == "info" for r in rows),
            "new_alerts": len([a for a in new_alerts if a.rounds_seen == 1]),
            "resolved_alerts": len(resolved),
            "resolved": [{"bed": a.bed, "pid": a.pid, "title": a.title} for a in resolved][:20],
            "patients": [asdict(r) for r in rows if r.findings or r.tool_errors],
            "summary_md": "",
            "summary_source": "template",
            "summary_status": "done",
            "summary_error": None,
            "summary_model": None,
        }
        report["summary_md"] = self.template_summary(report)
        report["duration_ms"] = round((time.time() - started) * 1000)

        mode = ai_summary or self.settings.section("rounds")["ai_summary"]
        flagged = report["n_critical"] + report["n_warning"] > 0
        want_ai = self.llm.available and mode != "off" and (mode == "always" or flagged)
        if want_ai:
            report["summary_status"] = "pending"

        report["db_id"] = await records.insert_report(self.sm, report, self.run_id)
        report["id"] = records.code("R", report["db_id"], 5)
        for status in statuses:
            status["round_id"] = report["id"]
        self.reports.insert(0, report)
        del self.reports[60:]
        if trigger != "recheck" and not pids:
            self.last_full_round_wall = started

        await self.bus.publish("round_completed", self.brief(report))
        for alert in new_alerts:
            await self.bus.publish("alert", alert.to_dict())
        if want_ai:
            asyncio.create_task(self._ai_summary(report))
        return report

    # ---------- 報告 ----------
    def brief(self, report: dict) -> dict:
        return {k: report[k] for k in ("id", "trigger", "trigger_label", "scope", "wall_time", "sim_time", "duration_ms",
                                       "patients_checked", "tools_run", "n_critical", "n_warning", "n_info",
                                       "new_alerts", "resolved_alerts", "summary_source", "summary_status")}

    def template_summary(self, report: dict) -> str:
        lines = [
            f"**{report['trigger_label']}｜模擬時間 {_hhmm(report['sim_time'])}｜{report['scope']}**",
            "",
            f"共查看 **{report['patients_checked']}** 位病人、執行 {report['tools_run']} 次工具判讀："
            f"🔴 危急 **{report['n_critical']}** 位、🟠 警示 **{report['n_warning']}** 位；"
            f"新出現 {report['new_alerts']} 項問題，已緩解 {report['resolved_alerts']} 項。",
        ]
        info_rows = []
        for row in report["patients"]:
            serious = [f for f in row["findings"] if f["severity"] != "info"]
            if not serious:
                info_rows.append(row)
                continue
            new_tag = "　🆕 新出現" if row["new_count"] else ""
            lines += ["", f"#### {SEV_ICON[row['severity']]} {row['label']}{new_tag}"]
            for f in serious:
                lines.append(f"- **{f['title']}**：{f['detail']}（{f['tool_name']}）")
            tips = []
            for f in serious:
                if f["suggestion"] and f["suggestion"] not in tips:
                    tips.append(f["suggestion"])
            if tips:
                lines.append(f"- 建議：{tips[0]}")
            for s in row["skills"][:2]:
                skill = self.skills.get(s["id"])
                if skill:
                    items = SkillManager.checklist(skill, 3)
                    if items:
                        lines.append(f"- 依技能「{skill['name']}」：" + "；".join(items))
        if info_rows:
            lines += ["", "#### 🔵 可安排事項"]
            for row in info_rows[:8]:
                for f in row["findings"]:
                    lines.append(f"- {row['bed']}（{row['pid']}）{f['title']}：{f['detail']}")
        if report["resolved"]:
            lines += ["", "#### ✅ 已緩解"]
            lines += [f"- {r['bed']}（{r['pid']}）{r['title']}" for r in report["resolved"][:8]]
        stable = report["patients_checked"] - report["n_critical"] - report["n_warning"]
        lines += ["", f"其餘 {stable} 位病人目前無警示。"]
        return "\n".join(lines)

    async def _ai_summary(self, report: dict) -> None:
        try:
            payload = self._ai_payload(report)
            always = self.skills.always_for_rounds()
            system = ROUND_SYSTEM
            if always:
                system += "\n\n" + "\n\n".join(f"<skill name=\"{s['name']}\">\n{s['body']}\n</skill>" for s in always)
            response = await self.llm.create(
                system=system,
                messages=[{"role": "user", "content": payload}],
                max_tokens=8000,
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("AI 拒絕產生此摘要")
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            if not text:
                raise RuntimeError("AI 未回傳內容")
            report["summary_md"] = text
            report["summary_source"] = "ai"
            report["summary_model"] = response.model
            report["summary_status"] = "done"
        except Exception as exc:
            report["summary_status"] = "failed"
            report["summary_error"] = friendly_error(exc)
        try:
            await records.update_report(self.sm, report["db_id"], summary_md=report["summary_md"],
                                        summary_source=report["summary_source"], summary_status=report["summary_status"],
                                        summary_error=report["summary_error"], summary_model=report.get("summary_model"))
        except Exception as exc:
            print(f"[rounds] 儲存 AI 摘要失敗：{type(exc).__name__}: {exc}")
        await self.bus.publish("round_summary", {**self.brief(report), "summary_md": report["summary_md"],
                                                 "summary_error": report["summary_error"]})

    def _ai_payload(self, report: dict) -> str:
        flagged = [r for r in report["patients"] if any(f["severity"] != "info" for f in r["findings"])][:15]
        info_rows = [r for r in report["patients"] if r not in flagged][:10]
        patients = []
        skill_ids = []
        for row in flagged:
            p = self.engine.get(row["pid"])
            entry = {"床位": row["bed"], "病號": row["pid"], "病人": row["label"], "整體嚴重度": SEVERITY_LABEL.get(row["severity"], row["severity"])}
            if p:
                d = self.engine.detail(p.pid)
                entry.update({
                    "ASA": d["asa"], "共病": d["comorbidities"], "麻醉": d["anes_label"], "階段": d["phase_label"],
                    "在此區域分鐘": d["minutes"], "生命徵象": d["vitals"], "節律": d["rhythm"],
                    "出血與尿量": d["fluids"],
                })
            entry["發現"] = [{"嚴重度": f["severity_label"], "標題": f["title"], "內容": f["detail"],
                            "工具": f["tool_name"], "新出現": f["new"], "工具建議": f["suggestion"]} for f in row["findings"]]
            entry["適用技能"] = [s["name"] for s in row["skills"]]
            skill_ids += [s["id"] for s in row["skills"]]
            patients.append(entry)
        data = {
            "查房": {"編號": report["id"], "類型": report["trigger_label"], "範圍": report["scope"],
                   "模擬時間": _hhmm(report["sim_time"]), "查看人數": report["patients_checked"],
                   "危急人數": report["n_critical"], "警示人數": report["n_warning"],
                   "新問題數": report["new_alerts"], "已緩解": report["resolved"]},
            "需要注意的病人": patients,
            "提示事項": [{"床位": r["bed"], "病號": r["pid"], "內容": [f["title"] + "：" + f["detail"] for f in r["findings"]]} for r in info_rows],
        }
        skill_texts = []
        for sid in dict.fromkeys(skill_ids):
            s = self.skills.get(sid)
            if s:
                skill_texts.append(f"<skill name=\"{s['name']}\">\n{s['body']}\n</skill>")
        parts = ["以下是本次自動查房的結果（JSON）：", "```json", json.dumps(data, ensure_ascii=False, indent=1, default=str), "```"]
        if skill_texts:
            parts += ["", "以下是與這些病人相關的處置技能，撰寫建議時請依照：", *skill_texts]
        parts += ["", "請撰寫本次查房摘要。"]
        return "\n".join(parts)

    # ---------- 查詢 ----------
    def latest(self, include_recheck: bool = False) -> dict | None:
        for r in self.reports:
            if include_recheck or r["trigger"] != "recheck":
                return r
        return None

    async def list_reports(self, limit: int = 60) -> list[dict]:
        return await records.list_reports(self.sm, limit)

    async def get_report(self, round_id: str) -> dict | None:
        cached = next((r for r in self.reports if r["id"] == round_id), None)
        if cached:
            return cached
        db_id = records.parse_code("R", round_id)
        return await records.get_report(self.sm, db_id) if db_id else None

    def list_alerts(self, status: str = "active", severity: str | None = None) -> list[dict]:
        items = [a for a in self.alerts.values() if (status == "all" or a.status == status)
                 and (severity in (None, "all") or a.severity == severity)]
        items.sort(key=lambda a: (-SEVERITY_ORDER[a.severity], a.acknowledged, -a.last_seen))
        return [a.to_dict() for a in items]

    def active_alert_count(self) -> int:
        return sum(1 for a in self.alerts.values() if a.status == "active")

    async def acknowledge(self, alert_id: str | None = None, pid: str | None = None) -> int:
        changed = [a for a in self.alerts.values()
                   if a.status == "active" and ((alert_id and a.id == alert_id) or (pid and a.pid == pid))]
        for a in changed:
            a.acknowledged = True
        await records.acknowledge_alerts(self.sm, [a.db_id for a in changed if a.db_id])
        return len(changed)
