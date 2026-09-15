"""離線模式：沒有設定 Claude API 金鑰時，用關鍵字辨識常見問題並直接呼叫工具回答。

目的是讓展示在沒有網路或金鑰時仍能運作；設定金鑰後會改用 Claude 進行完整的自然語言對話。
"""
from __future__ import annotations

import re

from ..config import SettingsError
from ..simulator.engine import Patient
from ..skills.manager import SkillManager
from .toolbox import AgentToolbox, ToolError, hhmm

EXAMPLES = [
    "目前有哪些危急病人？",
    "OR-05 的病人狀況",
    "P012 近 30 分鐘趨勢",
    "幫 P012 跑 AI 預測",
    "立即查房",
    "把查房改成每 3 分鐘",
    "每天 08:00、13:00 查房",
    "列出低血壓的病人",
    "P012 交班",
    "有哪些工具／技能？",
]

TOPICS = {
    "低血壓": ["低血壓", "血壓較術前"],
    "高血壓": ["高血壓"],
    "出血": ["出血", "休克指數", "血紅素"],
    "血氧": ["血氧", "呼吸", "二氧化碳", "氣道"],
    "體溫": ["體溫", "低體溫"],
    "心跳": ["心搏", "心律", "心房顫動"],
    "疼痛": ["疼痛"],
    "噁心": ["噁心", "PONV"],
    "血糖": ["血糖"],
    "麻醉深度": ["麻醉深度", "麻醉可能過深"],
    "尿量": ["尿量"],
    "轉出": ["轉出"],
    "AI 預測": ["AI 預測", "AI 偵測"],
}


class OfflineResponder:
    def __init__(self, toolbox: AgentToolbox):
        self.tb = toolbox

    # ---------- 解析 ----------
    def find_patient(self, text: str) -> Patient | None:
        eng = self.tb.engine
        for pattern in (r"\b[Pp]\s*0*(\d{1,4})\b",):
            m = re.search(pattern, text)
            if m:
                p = eng.get(f"P{int(m.group(1)):03d}")
                if p:
                    return p
        m = re.search(r"(OR|PACU|or|pacu)\s*[-－_]?\s*0*(\d{1,2})", text)
        if m:
            p = eng.get(f"{m.group(1).upper()}-{int(m.group(2)):02d}")
            if p:
                return p
        m = re.search(r"恢復室\s*0*(\d{1,2})\s*床?", text)
        if m:
            return eng.get(f"PACU-{int(m.group(1)):02d}")
        m = re.search(r"(?:手術室|開刀房)?\s*0*(\d{1,2})\s*(?:號床|床|號房|房)", text)
        if m:
            return eng.get(f"OR-{int(m.group(1)):02d}")
        m = re.search(r"0*(\d{1,3})\s*號", text)
        if m:
            return eng.get(f"P{int(m.group(1)):03d}")
        return None

    # ---------- 回覆 ----------
    async def respond(self, session_id: str, text: str) -> dict:
        steps: list[dict] = []

        def step(label):
            steps.append({"tool": "offline", "label": label, "status": "done"})

        try:
            reply = await self._route(text, step)
        except (ToolError, SettingsError) as exc:
            reply = f"⚠️ {exc}"
        prefix = "🔌 **離線模式**（未設定 Claude API 金鑰，使用關鍵字理解；到「設定」輸入金鑰即可開啟完整 AI 對話）\n\n"
        return {"reply": prefix + reply, "steps": steps}

    async def _route(self, text: str, step) -> str:
        tb = self.tb
        t = text.strip()

        if re.search(r"(幫助|說明|你會|能做|可以做|怎麼用|help|\?$|？$)", t, re.I) and not self.find_patient(t) \
                and not re.search(r"(危急|警示|異常|高風險|病人|工具|技能|查房)", t):
            return self._help()

        # 查房設定
        if re.search(r"(停止|暫停|關閉|取消)\s*(自動)?\s*查房", t):
            await tb.settings.update("rounds", {"enabled": False})
            await tb.bus.publish("settings_changed", tb.settings.public())
            step("關閉自動查房")
            return "已**關閉**自動查房。需要時可說「開啟自動查房」。"
        if re.search(r"(開啟|啟動|恢復|打開)\s*(自動)?\s*查房", t):
            await tb.settings.update("rounds", {"enabled": True})
            await tb.bus.publish("settings_changed", tb.settings.public())
            step("開啟自動查房")
            return "已**開啟**自動查房。" + self._next_round_text()
        m = re.search(r"(?:每|間隔|每隔)\s*(\d+(?:\.\d+)?)\s*(分鐘|分|小時)", t)
        if m and re.search(r"(查房|巡|看|檢查)", t):
            minutes = float(m.group(1)) * (60 if m.group(2) == "小時" else 1)
            await tb.settings.update("rounds", {"mode": "interval", "interval_minutes": minutes, "enabled": True})
            await tb.bus.publish("settings_changed", tb.settings.public())
            step("修改查房設定")
            return f"已將自動查房改為**每 {minutes:g} 分鐘**一次。" + self._next_round_text()
        times = re.findall(r"(\d{1,2})\s*[:：點]\s*(\d{2})?", t)
        if times and re.search(r"(查房|巡)", t) and re.search(r"(每天|時間|點|:|：)", t):
            clean = [f"{int(h):02d}:{mm or '00'}" for h, mm in times if int(h) < 24]
            await tb.settings.update("rounds", {"mode": "schedule", "times": clean, "enabled": True})
            await tb.bus.publish("settings_changed", tb.settings.public())
            step("修改查房時間點")
            return "已改為**每天固定時間點**查房：" + "、".join(sorted(set(clean))) + "。" + self._next_round_text()
        if re.search(r"(查房設定|多久查房|查房頻率|下一次查房|下次查房)", t):
            cfg = tb.settings.section("rounds")
            step("查看查房設定")
            mode = f"每 {cfg['interval_minutes']:g} 分鐘" if cfg["mode"] == "interval" else "每天 " + "、".join(cfg["times"])
            return (f"自動查房：{'開啟' if cfg['enabled'] else '關閉'}｜模式：{mode}｜範圍：{cfg['scope']}"
                    f"｜AI 摘要：{cfg['ai_summary']}｜危急病人複查：每 {cfg['critical_recheck_minutes']:g} 分鐘。" + self._next_round_text())

        # 立即查房
        if re.search(r"(立即|現在|馬上|開始|執行|跑一次|做一次|再)\s*查房|查房一次|巡房", t):
            scope = "OR" if "手術室" in t else "PACU" if "恢復室" in t else "all"
            step("立即執行查房")
            report = await tb.rounds.run_round("agent", scope=scope, ai_summary="off")
            return report["summary_md"]

        # 查房報告
        if re.search(r"(查房報告|查房摘要|上次查房|最近查房|總結|摘要)", t) and not self.find_patient(t):
            report = tb.rounds.latest()
            step("查看最近查房報告")
            if not report:
                return "目前還沒有查房紀錄，可以說「立即查房」。"
            return report["summary_md"]

        # 工具與技能
        if re.search(r"(工具|tool)", t, re.I) and not self.find_patient(t):
            step("查看工具庫")
            lines = ["目前工具庫："]
            for item in tb.tools_overview():
                lines.append(f"- {'✅' if item['啟用'] else '⏸️'} **{item['名稱']}**（{item['類別']}）：{item['用途']}")
            return "\n".join(lines)
        if re.search(r"(技能|skill|SOP)", t, re.I) and not self.find_patient(t):
            step("查看技能清單")
            lines = ["目前技能："]
            for s in tb.skills.list():
                lines.append(f"- {'✅' if s['enabled'] else '⏸️'} **{s['name']}**：{s['description']}")
            return "\n".join(lines)

        patient = self.find_patient(t)
        if patient:
            return await self._patient_reply(patient, t, step)

        # 主題篩選
        for topic, keys in TOPICS.items():
            if topic in t or any(k in t for k in keys[:1]):
                return self._topic_reply(topic, keys, step)

        if re.search(r"(危急|警示|異常|高風險|需要注意|哪些病人|誰|狀況|嚴重)", t):
            return self._alerts_reply(step)

        if re.search(r"(病人|清單|全部|所有)", t):
            rows = tb.patient_rows()
            step("查看病人清單")
            lines = [f"目前共 {len(rows)} 位病人（模擬時間 {hhmm(tb.engine.t)}）：", "",
                     "| 床位 | 病號 | 病人 | 手術 | 階段 | 狀態 |", "|---|---|---|---|---|---|"]
            for r in rows:
                lines.append(f"| {r['床位']} | {r['病號']} | {r['病人']} | {r['手術']} | {r['階段']} | {r['狀態']['嚴重度']} |")
            return "\n".join(lines)

        return "我還沒辦法理解這句話（離線模式只認得常見說法）。\n\n" + self._help()

    def _help(self) -> str:
        return ("我可以協助：查看病人狀況與趨勢、執行工具與 AI 模型判讀、立即查房、修改查房頻率、查看警示、工具與技能清單。\n\n"
                "試試看：\n" + "\n".join(f"- 「{e}」" for e in EXAMPLES))

    def _next_round_text(self) -> str:
        info = self.tb.rounds.schedule_info()
        if not info["next_due"]:
            return ""
        return f"下一次查房約在 {hhmm(info['next_due'])}（{info['seconds_to_next']} 秒後）。"

    def _alerts_reply(self, step) -> str:
        tb = self.tb
        step("查看進行中警示")
        alerts = tb.rounds.list_alerts("active")
        if not alerts:
            latest = tb.rounds.latest()
            return "目前沒有進行中的警示。" + ("" if latest else "（尚未查房，可以說「立即查房」）")
        by_pid: dict[str, list[dict]] = {}
        for a in alerts:
            by_pid.setdefault(a["pid"], []).append(a)
        crit = [pid for pid, items in by_pid.items() if any(a["severity"] == "critical" for a in items)]
        warn = [pid for pid in by_pid if pid not in crit]
        lines = [f"進行中警示：🔴 危急 **{len(crit)}** 位、🟠 警示 **{len(warn)}** 位", ""]
        for group, icon in ((crit, "🔴"), (warn, "🟠")):
            for pid in group:
                items = by_pid[pid]
                ack = "（已確認）" if all(a["acknowledged"] for a in items) else ""
                lines.append(f"- {icon} **{items[0]['bed']}（{pid}）**{ack}：" + "；".join(f"{a['title']}—{a['detail']}" for a in items[:3]))
        lines.append("\n可以說「P0xx 狀況」查看單一病人。")
        return "\n".join(lines)

    def _topic_reply(self, topic: str, keys: list[str], step) -> str:
        tb = self.tb
        step(f"篩選「{topic}」相關病人")
        latest = tb.rounds.latest(include_recheck=True)
        if not latest:
            return "目前還沒有查房資料，可以說「立即查房」。"
        hits = []
        for row in latest["patients"]:
            fs = [f for f in row["findings"] if any(k in f["title"] or k in f["detail"] for k in keys)]
            if fs:
                hits.append((row, fs))
        if not hits:
            return f"最近一次查房（{hhmm(latest['wall_time'])}）沒有「{topic}」相關的發現。"
        lines = [f"最近一次查房（{hhmm(latest['wall_time'])}）與「{topic}」相關的病人共 {len(hits)} 位：", ""]
        for row, fs in hits:
            lines.append(f"- **{row['label']}**：" + "；".join(f"[{f['severity_label']}] {f['title']}—{f['detail']}" for f in fs))
        return "\n".join(lines)

    async def _patient_reply(self, p: Patient, text: str, step) -> str:
        tb = self.tb
        if re.search(r"(趨勢|變化|走勢|過去|近\s*\d+\s*分)", text):
            m = re.search(r"(\d+)\s*分", text)
            minutes = int(m.group(1)) if m else 30
            step(f"查看 {p.pid} 近 {minutes} 分鐘趨勢")
            tr = tb.trend(p, minutes)
            if "統計" not in tr:
                return "資料不足。"
            lines = [f"**{p.bed}（{p.pid}）近 {tr['分鐘數']} 分鐘趨勢**", "", "| 項目 | 起 | 目前 | 變化 | 最低 | 最高 |", "|---|---|---|---|---|---|"]
            for k, s in tr["統計"].items():
                lines.append(f"| {k} | {s['起']} | {s['目前']} | {s['變化']:+} | {s['最低']} | {s['最高']} |")
            return "\n".join(lines)

        if re.search(r"(確認|知道了|已處理)", text):
            n = await tb.rounds.acknowledge(pid=p.pid)
            await tb.bus.publish("alerts_changed", {"pid": p.pid})
            step(f"確認 {p.pid} 的警示")
            return f"已將 {p.bed}（{p.pid}）的 {n} 項警示標記為已確認。"

        detail = tb.patient_detail(p)
        v = detail["vitals"]
        if re.search(r"(預測|AI|模型|機器學習|深度學習)", text, re.I):
            ids = [t.id for t in tb.registry.list() if t.category in ("ml", "dl", "custom_model")]
            step(f"對 {p.pid} 執行 AI 模型")
            results = tb.run_tools(p, ids)
            lines = [f"**{p.bed}（{p.pid}）AI 模型判讀**", ""]
            for r in results:
                lines.append(f"- **{r['工具']}**（{r['類別']}）：{r['結果']}")
                for f in r.get("發現", []):
                    lines.append(f"  - [{f['嚴重度']}] {f['標題']}：{f['內容']}")
            lines.append("\n> AI 預測為機率性判斷，需由臨床人員確認。")
            return "\n".join(lines)

        step(f"查看病人 {p.pid}")
        step(f"對 {p.pid} 執行所有啟用工具")
        results = tb.run_tools(p)
        findings = [(r, f) for r in results for f in r.get("發現", [])]
        vitals = (f"HR {v['hr']}｜BP {v['sbp']}/{v['dbp']}（MAP {v['map']}）｜SpO₂ {v['spo2']}%｜EtCO₂ {v['etco2']}｜RR {v['rr']}"
                  f"｜T {v['temp']}°C" + (f"｜BIS {v['bis']}" if v["bis"] is not None else "") + (f"｜疼痛 {v['pain']}" if v["pain"] is not None else ""))
        header = [
            f"**{p.bed}（{p.pid}）｜{detail['age']}歲{'男' if detail['sex'] == 'M' else '女'}｜ASA {detail['asa']}｜{detail['surgery']}**",
            f"- 麻醉：{detail['anes_label']}，{detail['phase_label']} {detail['minutes']} 分鐘；共病：{'、'.join(detail['comorbidities']) or '無'}；過敏：{'、'.join(detail['allergies'])}",
            f"- 生命徵象：{vitals}；節律：{detail['rhythm']}",
            f"- 出血 {detail['fluids']['ebl_ml']} mL（{detail['fluids']['ebl_pct']}% EBV）｜輸液 {detail['fluids']['crystalloid_ml']} mL"
            + (f"｜尿量 {detail['fluids']['urine_ml']} mL" if detail["fluids"]["urine_ml"] is not None else ""),
        ]
        if re.search(r"(交班|SBAR|sbar)", text):
            labs = detail["labs"]
            lab_text = f"pH {labs['ph']}、K {labs['k']}、血糖 {labs['glucose']}、乳酸 {labs['lactate']}、Hb {labs['hb']}（{labs['t']}）" if labs else "無近期檢驗"
            main = findings[0][1]["標題"] if findings else "目前無工具警示"
            recs = []
            for _, f in findings:
                if f["建議"] and f["建議"] not in recs:
                    recs.append(f["建議"])
            return "\n".join([
                f"### SBAR 交班｜{p.bed}（{p.pid}）",
                f"**S**：{detail['age']}歲{'男' if detail['sex'] == 'M' else '女'}，{detail['surgery']}，{detail['anes_label']}，{detail['phase_label']} {detail['minutes']} 分鐘；主要問題：{main}。",
                f"**B**：ASA {detail['asa']}；共病 {'、'.join(detail['comorbidities']) or '無'}；過敏 {'、'.join(detail['allergies'])}；"
                f"出血 {detail['fluids']['ebl_ml']} mL；處置：{'、'.join(i['處置'] for i in detail['interventions'][-3:]) or '無'}。",
                f"**A**：{vitals}；檢驗：{lab_text}；工具判讀：" + ("；".join(f"{f['標題']}（{f['內容']}）" for _, f in findings[:4]) or "無異常") + "。",
                "**R**：" + ("；".join(recs[:3]) if recs else "持續監測生命徵象。"),
            ])
        lines = header + [""]
        if findings:
            lines.append("**工具判讀發現：**")
            for r, f in findings:
                lines.append(f"- [{f['嚴重度']}] **{f['標題']}**：{f['內容']}（{r['工具']}）")
                if f["建議"]:
                    lines.append(f"  - 建議：{f['建議']}")
            matched = tb.skills.match_findings([{"tool_id": r["代碼"], "title": f["標題"], "detail": f["內容"]} for r, f in findings])
            for s in matched[:2]:
                items = SkillManager.checklist(s, 4)
                if items:
                    lines.append(f"\n**依技能「{s['name']}」：**")
                    lines += [f"- {i}" for i in items]
        else:
            lines.append("✅ 所有啟用中的工具目前都沒有發現異常。")
        return "\n".join(lines)
