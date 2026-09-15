"""臨床評分工具（計算型）。"""
from __future__ import annotations

from .base import BaseTool, Finding, ParamSpec


class ShockIndex(BaseTool):
    id = "shock_index"
    name = "休克指數"
    category = "score"
    description = "休克指數 = 心跳 ÷ 收縮壓，用來早期察覺出血或休克。"
    how_it_works = "計算：心跳 ÷ 收縮壓。一般 < 0.7 正常；超過警示門檻 → 警示；超過危急門檻 → 危急。"
    params = [
        ParamSpec("warning", "警示門檻", 1.0, min=0.7, max=1.5, step=0.05),
        ParamSpec("critical", "危急門檻", 1.4, min=1.0, max=2.5, step=0.05),
    ]

    def run(self, ctx, prm):
        hr, sbp = ctx.vitals["hr"], ctx.vitals["sbp"]
        if not hr or not sbp:
            return self.result(ctx, "資料不足")
        si = hr / sbp
        findings = []
        if si >= prm["warning"]:
            sev = "critical" if si >= prm["critical"] else "warning"
            findings.append(Finding(sev, "休克指數升高", f"休克指數 {si:.2f}（心跳 {hr} ÷ 收縮壓 {sbp}）",
                                    "評估出血、低血容與心輸出；檢查出血量與 Hb，準備輸液或輸血。", {"shock_index": round(si, 2)}))
        return self.result(ctx, f"休克指數 {si:.2f}", findings, {"shock_index": round(si, 2)})


class AldreteScore(BaseTool):
    id = "aldrete"
    name = "Aldrete 恢復室轉出評分"
    category = "score"
    locations = ("PACU",)
    description = "依活動力、呼吸、循環、意識、血氧五項（各 0–2 分）評估是否可轉出恢復室。"
    how_it_works = ("計算五項分數加總（滿分 10）。總分 ≥ 轉出門檻、疼痛 ≤ 4、無噁心嘔吐且在恢復室 ≥ 30 分鐘 → 提示可轉出；"
                    "在恢復室超過 45 分鐘仍 ≤ 7 分 → 警示恢復延遲。")
    params = [ParamSpec("discharge", "可轉出分數", 9, min=7, max=10)]

    def run(self, ctx, prm):
        v = ctx.vitals
        m = ctx.minutes_in_location
        if ctx.anes_class == "NEURAXIAL":
            activity = 0 if m < 30 else (1 if m < 50 else 2)
        else:
            activity = 1 if m < 10 else 2
        rr, spo2 = v["rr"] or 0, v["spo2"] or 0
        respiration = 0 if (rr < 8 or spo2 < 88) else (1 if (rr < 10 or (v["etco2"] or 0) > 50) else 2)
        dev = abs(v["sbp"] - ctx.baseline["sbp"]) / ctx.baseline["sbp"] if v["sbp"] else 1
        circulation = 2 if dev <= 0.2 else (1 if dev <= 0.5 else 0)
        if ctx.anes_class == "GA":
            consciousness = 0 if m < 10 else (1 if m < 25 else 2)
        else:
            consciousness = 1 if m < 10 else 2
        oxygen = 2 if spo2 >= 92 else (1 if spo2 >= 90 else 0)
        parts = {"活動力": activity, "呼吸": respiration, "循環": circulation, "意識": consciousness, "血氧": oxygen}
        total = sum(parts.values())
        detail = "、".join(f"{k}{s}" for k, s in parts.items())
        findings = []
        pain = v["pain"] if v["pain"] is not None else 0
        if total >= prm["discharge"] and pain <= 4 and not ctx.ponv and m >= 30:
            findings.append(Finding("info", "符合恢復室轉出條件", f"Aldrete {total}/10（{detail}），疼痛 {pain}/10，在恢復室 {m:.0f} 分鐘",
                                    "確認麻醉醫師評估後可安排轉回病房。", {"aldrete": total}))
        elif total <= 7 and m >= 45:
            findings.append(Finding("warning", "恢復延遲", f"在恢復室 {m:.0f} 分鐘，Aldrete 僅 {total}/10（{detail}）",
                                    "找出低分項目原因（呼吸、循環、意識），考慮延長觀察或進一步處置。", {"aldrete": total}))
        return self.result(ctx, f"Aldrete {total}/10（{detail}）", findings, {"aldrete": total, **parts})


class EarlyWarningScore(BaseTool):
    id = "early_warning"
    name = "早期預警分數（NEWS 改良）"
    category = "score"
    description = "依呼吸、血氧、收縮壓、心跳、體溫計分，總分越高代表惡化風險越高。適用恢復室與非全身麻醉病人。"
    how_it_works = ("計算：參考 NEWS2，每項 0–3 分後加總（不含意識與給氧項目）。總分 ≥ 警示門檻 → 警示；"
                    "≥ 危急門檻 → 危急。使用呼吸器的全身麻醉病人不適用。")
    params = [
        ParamSpec("warning", "警示總分", 5, min=3, max=10),
        ParamSpec("critical", "危急總分", 7, min=5, max=15),
    ]

    def applicable(self, ctx):
        ok, why = super().applicable(ctx)
        if ok and ctx.location == "OR" and ctx.anes_class == "GA":
            return False, "全身麻醉（呼吸器）病人不適用"
        return ok, why

    @staticmethod
    def _points(v):
        rr, spo2, sbp, hr, temp = v["rr"], v["spo2"], v["sbp"], v["hr"], v["temp"]
        pts = {}
        pts["呼吸"] = 3 if rr <= 8 else 1 if rr <= 11 else 0 if rr <= 20 else 2 if rr <= 24 else 3
        pts["血氧"] = 3 if spo2 <= 91 else 2 if spo2 <= 93 else 1 if spo2 <= 95 else 0
        pts["收縮壓"] = 3 if sbp <= 90 else 2 if sbp <= 100 else 1 if sbp <= 110 else 0 if sbp <= 219 else 3
        pts["心跳"] = 3 if hr <= 40 else 1 if hr <= 50 else 0 if hr <= 90 else 1 if hr <= 110 else 2 if hr <= 130 else 3
        pts["體溫"] = 3 if temp <= 35.0 else 1 if temp <= 36.0 else 0 if temp <= 38.0 else 1 if temp <= 39.0 else 2
        return pts

    def run(self, ctx, prm):
        v = ctx.vitals
        if None in (v["rr"], v["spo2"], v["sbp"], v["hr"], v["temp"]):
            return self.result(ctx, "資料不足")
        pts = self._points(v)
        total = sum(pts.values())
        detail = "、".join(f"{k}{s}" for k, s in pts.items() if s)
        findings = []
        if total >= prm["warning"]:
            sev = "critical" if total >= prm["critical"] else "warning"
            findings.append(Finding(sev, "早期預警分數偏高", f"總分 {total}（{detail}）",
                                    "提高監測頻率並請麻醉醫師評估；找出得分最高的生理異常優先處理。", {"score": total}))
        return self.result(ctx, f"早期預警分數 {total}" + (f"（{detail}）" if detail else ""), findings, {"score": total, **pts})


class ApfelScore(BaseTool):
    id = "apfel_ponv"
    name = "Apfel 術後噁心嘔吐風險"
    category = "score"
    description = "依女性、不吸菸、PONV 病史、術後使用鴉片類四項，估計術後噁心嘔吐（PONV）風險。"
    how_it_works = ("計算：每項 1 分，0–4 分對應風險約 10%／21%／39%／61%／79%。手術結束前或剛到恢復室時，"
                    "分數 ≥ 門檻 → 提示預防性止吐；恢復室病人實際出現噁心嘔吐 → 警示。")
    params = [ParamSpec("threshold", "高風險分數", 3, min=1, max=4)]
    RISK = [10, 21, 39, 61, 79]

    def run(self, ctx, prm):
        prof = ctx.profile
        factors = {
            "女性": ctx.sex == "F",
            "不吸菸": not prof["smoker"],
            "PONV／暈車病史": prof["ponv_history"],
            "術後鴉片類止痛": ctx.anes_class == "GA" or prof["planned_min"] >= 120,
        }
        score = sum(factors.values())
        risk = self.RISK[score]
        present = "、".join(k for k, v in factors.items() if v) or "無"
        findings = []
        if ctx.location == "PACU" and ctx.ponv:
            findings.append(Finding("warning", "出現術後噁心嘔吐", f"病人目前噁心嘔吐（Apfel {score} 分，風險約 {risk}%）",
                                    "給予止吐藥（如 Ondansetron 4 mg IV），若已預防使用則換不同機轉藥物；注意呼吸道保護。",
                                    {"apfel": score}))
        elif score >= prm["threshold"] and (ctx.phase == "emergence" or (ctx.location == "PACU" and ctx.minutes_in_location < 20)):
            findings.append(Finding("info", "PONV 高風險", f"Apfel {score} 分（{present}），風險約 {risk}%",
                                    "確認已給予預防性止吐（Dexamethasone、Ondansetron），減少鴉片類使用。", {"apfel": score}))
        return self.result(ctx, f"Apfel {score} 分，PONV 風險約 {risk}%（{present}）", findings, {"apfel": score, "risk_pct": risk})


def builtin_score_tools() -> list[BaseTool]:
    return [ShockIndex(), AldreteScore(), EarlyWarningScore(), ApfelScore()]
