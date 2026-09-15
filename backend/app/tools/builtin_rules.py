"""內建規則式工具（Rule-based）。門檻值都可以在「工具庫」頁面直接修改。"""
from __future__ import annotations

from .base import BaseTool, Finding, ParamSpec


def _where(ctx) -> str:
    return "術中" if ctx.location == "OR" else "恢復室"


class IOHDetector(BaseTool):
    id = "ioh_detector"
    name = "低血壓偵測"
    category = "rule"
    description = "偵測平均動脈壓（MAP）低於門檻並持續一段時間，或相對術前基準下降過多。"
    how_it_works = ("規則：MAP 低於門檻且持續達設定分鐘數 → 警示；低於危急門檻或持續 5 分鐘以上 → 危急。"
                    "MAP 比術前基準下降超過設定百分比也會提醒（高血壓病人尤其重要）。")
    params = [
        ParamSpec("map_threshold", "MAP 門檻", 65, unit="mmHg", min=40, max=90),
        ParamSpec("critical_map", "危急 MAP 門檻", 55, unit="mmHg", min=30, max=80),
        ParamSpec("duration_min", "持續時間", 1, unit="分鐘", min=0, max=30, step=0.5),
        ParamSpec("drop_pct", "相對術前基準下降", 30, unit="%", min=10, max=60),
    ]

    def run(self, ctx, prm):
        mapv = ctx.vitals["map"]
        if mapv is None:
            return self.result(ctx, "無 MAP 資料")
        base = ctx.baseline_map
        drop = (1 - mapv / base) * 100
        dur = ctx.sustained_minutes("map", "<", prm["map_threshold"])
        findings = []
        if mapv < prm["map_threshold"] and dur >= prm["duration_min"]:
            sev = "critical" if mapv < prm["critical_map"] or dur >= 5 else "warning"
            findings.append(Finding(
                sev, f"{_where(ctx)}低血壓",
                f"MAP {mapv} mmHg，低於 {prm['map_threshold']:.0f} mmHg 已約 {dur:.1f} 分鐘（術前基準 {base:.0f}，下降 {drop:.0f}%）",
                "確認量測正確；評估麻醉深度、出血與容積狀態；考慮升壓劑（Phenylephrine/Norepinephrine）或輸液。",
                {"map": mapv, "below_minutes": round(dur, 1), "baseline_map": round(base)},
            ))
        elif drop >= prm["drop_pct"] and ctx.phase != "induction":
            findings.append(Finding(
                "warning", "血壓較術前明顯下降",
                f"MAP {mapv} mmHg，較術前基準 {base:.0f} 下降 {drop:.0f}%",
                "雖未低於絕對門檻，仍建議評估器官灌流，特別是高血壓或冠心病病人。",
                {"map": mapv, "drop_pct": round(drop)},
            ))
        return self.result(ctx, f"MAP {mapv} mmHg（基準 {base:.0f}，變化 {-drop:+.0f}%）", findings,
                           {"map": mapv, "below_minutes": round(dur, 1), "drop_pct": round(drop)})


class HypertensionDetector(BaseTool):
    id = "htn_detector"
    name = "高血壓偵測"
    category = "rule"
    description = "偵測收縮壓過高或 MAP 明顯高於術前基準。"
    how_it_works = "規則：收縮壓高於門檻，或 MAP 高於基準設定百分比，且持續達設定分鐘數 → 警示。"
    params = [
        ParamSpec("sbp_threshold", "收縮壓門檻", 170, unit="mmHg", min=130, max=220),
        ParamSpec("rise_pct", "MAP 高於基準", 30, unit="%", min=10, max=60),
        ParamSpec("duration_min", "持續時間", 2, unit="分鐘", min=0, max=30, step=0.5),
    ]

    def run(self, ctx, prm):
        sbp, mapv = ctx.vitals["sbp"], ctx.vitals["map"]
        if sbp is None:
            return self.result(ctx, "無血壓資料")
        rise = (mapv / ctx.baseline_map - 1) * 100
        dur_sbp = ctx.sustained_minutes("sbp", ">", prm["sbp_threshold"])
        dur_map = ctx.sustained_minutes("map", ">", ctx.baseline_map * (1 + prm["rise_pct"] / 100))
        findings = []
        if max(dur_sbp, dur_map) >= prm["duration_min"] and (sbp > prm["sbp_threshold"] or rise > prm["rise_pct"]):
            sev = "critical" if sbp >= 200 else "warning"
            findings.append(Finding(
                sev, f"{_where(ctx)}高血壓",
                f"血壓 {sbp}/{ctx.vitals['dbp']}（MAP {mapv}，高於基準 {rise:.0f}%）",
                "評估疼痛與麻醉深度；排除膀胱脹、高碳酸血症；必要時給予降壓藥（Nicardipine/Labetalol）。",
                {"sbp": sbp, "map": mapv, "rise_pct": round(rise)},
            ))
        return self.result(ctx, f"血壓 {sbp}/{ctx.vitals['dbp']}", findings, {"sbp": sbp, "rise_pct": round(rise)})


class HeartRateMonitor(BaseTool):
    id = "hr_monitor"
    name = "心跳與心律監測"
    category = "rule"
    description = "偵測心搏過緩、心搏過速與心律異常（如心房顫動、高尖 T 波）。"
    how_it_works = "規則：心跳低於／高於門檻持續達設定時間 → 警示；超過危急門檻 → 危急。心電圖節律異常 → 警示。"
    params = [
        ParamSpec("low", "心搏過緩門檻", 45, unit="次/分", min=30, max=60),
        ParamSpec("high", "心搏過速門檻", 120, unit="次/分", min=90, max=160),
        ParamSpec("critical_low", "危急過緩", 40, unit="次/分", min=20, max=50),
        ParamSpec("critical_high", "危急過速", 140, unit="次/分", min=110, max=200),
        ParamSpec("duration_min", "持續時間", 1, unit="分鐘", min=0, max=10, step=0.5),
    ]

    def run(self, ctx, prm):
        hr = ctx.vitals["hr"]
        if hr is None:
            return self.result(ctx, "無心跳資料")
        findings = []
        if hr < prm["low"] and ctx.sustained_minutes("hr", "<", prm["low"]) >= prm["duration_min"]:
            sev = "critical" if hr < prm["critical_low"] else "warning"
            findings.append(Finding(sev, "心搏過緩", f"心跳 {hr} 次/分（{ctx.rhythm}），血壓 {ctx.vitals['sbp']}/{ctx.vitals['dbp']}",
                                    "暫停手術刺激（如牽拉、氣腹）；評估藥物影響；心跳合併低血壓時給予 Atropine。", {"hr": hr}))
        elif hr > prm["high"] and ctx.sustained_minutes("hr", ">", prm["high"]) >= prm["duration_min"]:
            sev = "critical" if hr > prm["critical_high"] else "warning"
            findings.append(Finding(sev, "心搏過速", f"心跳 {hr} 次/分（{ctx.rhythm}），血壓 {ctx.vitals['sbp']}/{ctx.vitals['dbp']}",
                                    "排除麻醉過淺、疼痛、出血／低血容、發燒與惡性高熱；依原因處理。", {"hr": hr}))
        if ctx.rhythm == "心房顫動":
            findings.append(Finding("warning", "心律不整：心房顫動", f"心電圖顯示心房顫動，心跳 {hr} 次/分",
                                    "評估血行動力學是否穩定；不穩定考慮同步電擊，穩定可考慮速率控制（Amiodarone）。", {"rhythm": ctx.rhythm}))
        elif ctx.rhythm == "高尖 T 波":
            findings.append(Finding("warning", "心電圖：高尖 T 波", "出現高尖 T 波，需排除高血鉀",
                                    "立即抽血檢驗血鉀；若確認高血鉀，給予鈣劑與胰島素／葡萄糖。", {"rhythm": ctx.rhythm}))
        return self.result(ctx, f"心跳 {hr} 次/分，{ctx.rhythm}", findings, {"hr": hr, "rhythm": ctx.rhythm})


class SpO2Monitor(BaseTool):
    id = "spo2_monitor"
    name = "血氧監測"
    category = "rule"
    description = "偵測血氧飽和度（SpO₂）下降。"
    how_it_works = "規則：SpO₂ 低於門檻持續達設定時間 → 警示；低於危急門檻 → 危急。"
    params = [
        ParamSpec("threshold", "SpO₂ 門檻", 92, unit="%", min=85, max=97),
        ParamSpec("critical", "危急 SpO₂", 88, unit="%", min=70, max=92),
        ParamSpec("duration_min", "持續時間", 0.5, unit="分鐘", min=0, max=10, step=0.5),
    ]

    def run(self, ctx, prm):
        spo2 = ctx.vitals["spo2"]
        if spo2 is None:
            return self.result(ctx, "無血氧資料")
        findings = []
        if spo2 < prm["threshold"] and ctx.sustained_minutes("spo2", "<", prm["threshold"]) >= prm["duration_min"]:
            sev = "critical" if spo2 < prm["critical"] else "warning"
            tip = ("提高 FiO₂ 至 100%；檢查氣管內管位置、分泌物與支氣管痙攣（聽診、氣道壓）；考慮肺擴張。"
                   if ctx.location == "OR" and ctx.anes_class == "GA"
                   else "給予氧氣、喚醒病人並鼓勵深呼吸；評估鴉片類藥物呼吸抑制，必要時給 Naloxone。")
            findings.append(Finding(sev, "血氧下降", f"SpO₂ {spo2}%（呼吸 {ctx.vitals['rr']} 次/分，EtCO₂ {ctx.vitals['etco2']}）", tip, {"spo2": spo2}))
        return self.result(ctx, f"SpO₂ {spo2}%", findings, {"spo2": spo2})


class VentilationMonitor(BaseTool):
    id = "ventilation_monitor"
    name = "通氣監測（EtCO₂／呼吸／氣道壓）"
    category = "rule"
    description = "偵測二氧化碳滯留、通氣不足、呼吸過慢與氣道壓過高。"
    how_it_works = ("規則：EtCO₂ 高於門檻 → 警示；全身麻醉中 EtCO₂ 過低（疑管路脫落）→ 警示；"
                    "自主呼吸病人呼吸速率過慢 → 警示；氣道峰壓過高 → 警示。")
    params = [
        ParamSpec("etco2_high", "EtCO₂ 上限", 50, unit="mmHg", min=40, max=70),
        ParamSpec("etco2_low", "EtCO₂ 下限（全麻）", 25, unit="mmHg", min=10, max=32),
        ParamSpec("rr_low", "呼吸速率下限", 8, unit="次/分", min=4, max=12),
        ParamSpec("ppeak_high", "氣道峰壓上限", 30, unit="cmH₂O", min=20, max=45),
    ]

    def run(self, ctx, prm):
        v = ctx.vitals
        findings = []
        ga_vent = ctx.location == "OR" and ctx.anes_class == "GA" and ctx.phase in ("maintenance", "induction")
        if v["etco2"] is not None:
            if v["etco2"] > prm["etco2_high"] and ctx.sustained_minutes("etco2", ">", prm["etco2_high"]) >= 1:
                sev = "critical" if v["etco2"] >= 60 else "warning"
                findings.append(Finding(sev, "二氧化碳滯留", f"EtCO₂ {v['etco2']} mmHg（呼吸 {v['rr']} 次/分）",
                                        "全麻中調高通氣量；自主呼吸病人評估呼吸抑制；若無法解釋的上升合併心跳體溫上升，需排除惡性高熱。",
                                        {"etco2": v["etco2"]}))
            elif ga_vent and ctx.phase == "maintenance" and v["etco2"] < prm["etco2_low"]:
                findings.append(Finding("warning", "EtCO₂ 過低", f"EtCO₂ {v['etco2']} mmHg",
                                        "檢查呼吸管路是否脫落或漏氣；排除過度通氣、心輸出量驟降或肺栓塞。", {"etco2": v["etco2"]}))
        if not ga_vent and v["rr"] is not None and v["rr"] < prm["rr_low"] and ctx.sustained_minutes("rr", "<", prm["rr_low"]) >= 1:
            sev = "critical" if v["rr"] < 6 else "warning"
            findings.append(Finding(sev, "呼吸過慢", f"呼吸速率 {v['rr']} 次/分（SpO₂ {v['spo2']}%）",
                                    "喚醒病人、給予氧氣；評估鴉片類／鎮靜藥物影響，必要時給 Naloxone 並準備呼吸道支持。", {"rr": v["rr"]}))
        if v["ppeak"] is not None and v["ppeak"] > prm["ppeak_high"]:
            sev = "critical" if v["ppeak"] >= 35 else "warning"
            findings.append(Finding(sev, "氣道壓過高", f"氣道峰壓 {v['ppeak']} cmH₂O",
                                    "檢查管路扭折、分泌物、支氣管痙攣或肌肉鬆弛不足；聽診雙側呼吸音。", {"ppeak": v["ppeak"]}))
        summary = f"EtCO₂ {v['etco2']}、呼吸 {v['rr']}" + (f"、氣道壓 {v['ppeak']}" if v["ppeak"] is not None else "")
        return self.result(ctx, summary, findings, {"etco2": v["etco2"], "rr": v["rr"], "ppeak": v["ppeak"]})


class MHEarlyWarning(BaseTool):
    id = "mh_early_warning"
    name = "惡性高熱早期警訊"
    category = "rule"
    locations = ("OR",)
    description = "綜合 EtCO₂ 上升、心搏過速、體溫上升與高血鉀，早期辨識惡性高熱。"
    how_it_works = ("多條件規則：EtCO₂ 超過門檻且 15 分鐘內明顯上升為必要條件；再計算其他徵象"
                    "（心跳上升、體溫上升、血鉀高）。必要條件＋2 項以上 → 危急；＋1 項 → 警示。")
    params = [
        ParamSpec("etco2_threshold", "EtCO₂ 門檻", 50, unit="mmHg", min=40, max=70),
        ParamSpec("etco2_rise", "15 分鐘 EtCO₂ 上升", 8, unit="mmHg", min=3, max=30),
    ]

    def applicable(self, ctx):
        ok, why = super().applicable(ctx)
        if ok and ctx.anes_class != "GA":
            return False, "只適用全身麻醉病人"
        return ok, why

    def run(self, ctx, prm):
        v = ctx.vitals
        et_rise = ctx.change_over("etco2", 15) or 0
        hr_rise = ctx.change_over("hr", 15) or 0
        t_rise = ctx.change_over("temp", 30) or 0
        k = ctx.lab("k", 60)
        core = v["etco2"] is not None and v["etco2"] >= prm["etco2_threshold"] and et_rise >= prm["etco2_rise"]
        signs = []
        if hr_rise >= 20 or (v["hr"] or 0) > 110:
            signs.append(f"心跳 {v['hr']}（15 分鐘 {hr_rise:+.0f}）")
        if t_rise >= 0.3 or (v["temp"] or 0) >= 38.3:
            signs.append(f"體溫 {v['temp']}°C（30 分鐘 {t_rise:+.1f}）")
        if k is not None and k >= 5.5:
            signs.append(f"血鉀 {k}")
        findings = []
        if core and signs:
            sev = "critical" if len(signs) >= 2 else "warning"
            findings.append(Finding(
                sev, "疑似惡性高熱",
                f"EtCO₂ {v['etco2']} mmHg（15 分鐘上升 {et_rise:.0f}），合併：" + "、".join(signs),
                "立即停止揮發性麻醉氣體與 Succinylcholine、呼叫支援；Dantrolene 2.5 mg/kg IV；高流量 100% 氧氣過度換氣；積極降溫並處理高血鉀。",
                {"etco2": v["etco2"], "etco2_rise": round(et_rise, 1), "signs": signs},
            ))
        return self.result(ctx, f"EtCO₂ 15 分鐘變化 {et_rise:+.0f}，附帶徵象 {len(signs)} 項", findings,
                           {"etco2_rise": round(et_rise, 1), "sign_count": len(signs)})


class DepthMonitor(BaseTool):
    id = "depth_monitor"
    name = "麻醉深度監測（BIS）"
    category = "rule"
    locations = ("OR",)
    description = "全身麻醉維持期間偵測 BIS 過高（麻醉過淺）或過低（麻醉過深）。"
    how_it_works = "規則：BIS 高於上限持續達設定時間 → 麻醉可能過淺；低於下限持續 → 麻醉可能過深。只在麻醉維持期判讀。"
    params = [
        ParamSpec("high", "BIS 上限", 60, min=50, max=80),
        ParamSpec("low", "BIS 下限", 35, min=20, max=45),
        ParamSpec("high_min", "過淺持續時間", 2, unit="分鐘", min=0, max=15, step=0.5),
        ParamSpec("low_min", "過深持續時間", 5, unit="分鐘", min=0, max=30, step=0.5),
    ]

    def applicable(self, ctx):
        ok, why = super().applicable(ctx)
        if ok and (ctx.anes_class != "GA" or ctx.phase != "maintenance"):
            return False, "只在全身麻醉維持期判讀"
        return ok, why

    def run(self, ctx, prm):
        bis = ctx.vitals["bis"]
        if bis is None:
            return self.result(ctx, "無 BIS 資料")
        findings = []
        if bis > prm["high"] and ctx.sustained_minutes("bis", ">", prm["high"]) >= prm["high_min"]:
            findings.append(Finding("warning", "麻醉深度可能過淺", f"BIS {bis}（心跳 {ctx.vitals['hr']}，血壓 {ctx.vitals['sbp']}/{ctx.vitals['dbp']}）",
                                    "檢查麻醉氣體濃度或輸注管路；加深麻醉並評估止痛是否足夠，避免術中知曉。", {"bis": bis}))
        elif bis < prm["low"] and ctx.sustained_minutes("bis", "<", prm["low"]) >= prm["low_min"]:
            sev = "warning"
            findings.append(Finding(sev, "麻醉可能過深", f"BIS {bis}（MAP {ctx.vitals['map']}）",
                                    "考慮降低麻醉藥物濃度，特別是合併低血壓或高齡病人。", {"bis": bis}))
        return self.result(ctx, f"BIS {bis}", findings, {"bis": bis})


class TemperatureMonitor(BaseTool):
    id = "temp_monitor"
    name = "體溫監測"
    category = "rule"
    description = "偵測術中／恢復室低體溫與高體溫。"
    how_it_works = "規則：體溫低於下限持續 5 分鐘 → 警示，低於 35°C → 危急；高於上限 → 警示，高於 39.5°C → 危急。"
    params = [
        ParamSpec("low", "低體溫門檻", 36.0, unit="°C", min=34, max=36.5, step=0.1),
        ParamSpec("high", "高體溫門檻", 38.5, unit="°C", min=37.5, max=40, step=0.1),
    ]

    def run(self, ctx, prm):
        temp = ctx.vitals["temp"]
        findings = []
        if temp < prm["low"] and ctx.sustained_minutes("temp", "<", prm["low"]) >= 5:
            sev = "critical" if temp < 35 else "warning"
            findings.append(Finding(sev, "低體溫", f"體溫 {temp}°C",
                                    "使用熱風毯、輸液加溫、提高室溫；低體溫會增加出血、感染與甦醒延遲。", {"temp": temp}))
        elif temp > prm["high"]:
            sev = "critical" if temp > 39.5 else "warning"
            findings.append(Finding(sev, "體溫過高", f"體溫 {temp}°C（心跳 {ctx.vitals['hr']}，EtCO₂ {ctx.vitals['etco2']}）",
                                    "排除惡性高熱、感染／敗血症、過度保暖；必要時主動降溫。", {"temp": temp}))
        trend = ctx.change_over("temp", 30)
        return self.result(ctx, f"體溫 {temp}°C" + (f"（30 分鐘 {trend:+.1f}）" if trend is not None else ""), findings, {"temp": temp})


class UrineOutputMonitor(BaseTool):
    id = "urine_output"
    name = "尿量監測"
    category = "rule"
    locations = ("OR",)
    description = "有導尿管的手術病人，計算近 1 小時尿量（mL/kg/h）。"
    how_it_works = "計算：近 60 分鐘尿量 ÷ 體重 ÷ 時數。低於門檻 → 警示；低於危急門檻 → 危急。手術 60 分鐘後才開始判讀。"
    params = [
        ParamSpec("threshold", "尿量下限", 0.5, unit="mL/kg/h", min=0.1, max=1.5, step=0.1),
        ParamSpec("critical", "危急尿量", 0.3, unit="mL/kg/h", min=0.05, max=1, step=0.05),
    ]

    def applicable(self, ctx):
        ok, why = super().applicable(ctx)
        if ok and not ctx.has_foley:
            return False, "此病人沒有導尿管"
        return ok, why

    def run(self, ctx, prm):
        rate = ctx.urine_rate(60)
        if rate is None or ctx.case_minutes < 60:
            return self.result(ctx, "資料累積中（手術 60 分鐘後判讀）")
        findings = []
        if rate < prm["threshold"]:
            sev = "critical" if rate < prm["critical"] else "warning"
            findings.append(Finding(sev, "尿量過少", f"近 1 小時尿量 {rate:.2f} mL/kg/h（累計 {ctx.urine:.0f} mL）",
                                    "檢查導尿管是否阻塞；評估容積狀態與血壓；考慮輸液挑戰。", {"urine_rate": round(rate, 2)}))
        return self.result(ctx, f"尿量 {rate:.2f} mL/kg/h", findings, {"urine_rate": round(rate, 2)})


class BloodLossMonitor(BaseTool):
    id = "blood_loss"
    name = "出血量監測"
    category = "rule"
    locations = ("OR",)
    description = "依體重估算總血量，計算出血比例與近 15 分鐘出血速度。"
    how_it_works = ("計算：估計總血量 EBV = 體重 × 70（男）或 65（女）mL/kg。累計出血佔 EBV 比例超過門檻 → 警示／危急；"
                    "近 15 分鐘出血超過設定量 → 危急。")
    params = [
        ParamSpec("pct_warning", "出血比例（警示）", 20, unit="%", min=5, max=40),
        ParamSpec("pct_critical", "出血比例（危急）", 30, unit="%", min=10, max=60),
        ParamSpec("rate_ml_15min", "15 分鐘出血量", 300, unit="mL", min=50, max=2000),
    ]

    def run(self, ctx, prm):
        pct = ctx.ebl / ctx.ebv * 100
        recent = ctx.ebl_over(15) or 0
        findings = []
        if recent >= prm["rate_ml_15min"]:
            findings.append(Finding("critical", "快速出血", f"近 15 分鐘出血約 {recent:.0f} mL（累計 {ctx.ebl:.0f} mL，佔血量 {pct:.0f}%）",
                                    "通知外科止血；準備輸血與大量輸血流程；建立足夠靜脈管路並監測 Hb、凝血功能與電解質。",
                                    {"ebl_15min": round(recent), "ebl": round(ctx.ebl), "ebl_pct": round(pct, 1)}))
        elif pct >= prm["pct_warning"]:
            sev = "critical" if pct >= prm["pct_critical"] else "warning"
            findings.append(Finding(sev, "累計出血量偏多", f"累計出血 {ctx.ebl:.0f} mL，約佔估計血量 {pct:.0f}%",
                                    "抽血檢驗 Hb；評估是否需要輸血並維持血行動力學穩定。", {"ebl": round(ctx.ebl), "ebl_pct": round(pct, 1)}))
        return self.result(ctx, f"累計出血 {ctx.ebl:.0f} mL（{pct:.0f}% EBV），近 15 分鐘 {recent:.0f} mL", findings,
                           {"ebl": round(ctx.ebl), "ebl_pct": round(pct, 1), "ebl_15min": round(recent)})


class LabMonitor(BaseTool):
    id = "lab_monitor"
    name = "檢驗值判讀（血液氣體／電解質）"
    category = "rule"
    description = "判讀最近一次（2 小時內）的血液氣體、血鉀、血糖、乳酸、血紅素。"
    how_it_works = "規則：各檢驗值超出設定範圍即產生警示或危急提醒；超過 2 小時的舊檢驗不判讀。"
    params = [
        ParamSpec("k_high", "血鉀上限", 5.5, unit="mmol/L", min=4.5, max=7, step=0.1),
        ParamSpec("glucose_high", "血糖上限", 180, unit="mg/dL", min=140, max=300),
        ParamSpec("lactate_high", "乳酸上限", 2.0, unit="mmol/L", min=1, max=6, step=0.1),
        ParamSpec("hb_low", "血紅素下限", 8.0, unit="g/dL", min=5, max=11, step=0.1),
    ]

    def run(self, ctx, prm):
        if ctx.lab("k") is None:
            return self.result(ctx, "2 小時內無檢驗資料")
        L = ctx.labs
        age = ctx.labs_age_min
        when = f"（{age:.0f} 分鐘前）"
        findings = []

        def add(sev, title, detail, tip, ev):
            findings.append(Finding(sev, title, detail + when, tip, ev))

        if L["k"] >= prm["k_high"]:
            add("critical" if L["k"] >= 6.0 else "warning", "高血鉀", f"K {L['k']} mmol/L",
                "檢查心電圖；給予 Calcium gluconate、Insulin＋Glucose，考慮過度換氣；停止含鉀輸液。", {"k": L["k"]})
        elif L["k"] < 3.0:
            add("warning", "低血鉀", f"K {L['k']} mmol/L", "評估補充鉀離子並注意心律不整。", {"k": L["k"]})
        if L["glucose"] > prm["glucose_high"]:
            add("critical" if L["glucose"] > 250 else "warning", "高血糖", f"血糖 {L['glucose']} mg/dL",
                "依胰島素流程給予 Regular Insulin，並 1 小時後追蹤血糖。", {"glucose": L["glucose"]})
        elif L["glucose"] < 70:
            add("critical", "低血糖", f"血糖 {L['glucose']} mg/dL", "立即給予 50% 葡萄糖並追蹤。", {"glucose": L["glucose"]})
        if L["lactate"] > prm["lactate_high"]:
            add("critical" if L["lactate"] >= 4 else "warning", "乳酸上升", f"Lactate {L['lactate']} mmol/L",
                "評估組織灌流：出血、低血壓、低心輸出；惡性高熱時亦會上升。", {"lactate": L["lactate"]})
        if L["hb"] < prm["hb_low"]:
            add("critical" if L["hb"] < 7 else "warning", "血紅素偏低", f"Hb {L['hb']} g/dL",
                "評估持續出血與輸血指徵（一般 Hb < 7–8 g/dL 或心臟病人較高門檻）。", {"hb": L["hb"]})
        if L["ph"] < 7.25:
            add("critical" if L["ph"] < 7.15 else "warning", "酸血症", f"pH {L['ph']}，PaCO₂ {L['paco2']}，HCO₃ {L['hco3']}",
                "區分呼吸性或代謝性酸中毒，治療原因（通氣、灌流、乳酸）。", {"ph": L["ph"]})
        summary = f"pH {L['ph']}、K {L['k']}、血糖 {L['glucose']}、乳酸 {L['lactate']}、Hb {L['hb']}{when}"
        return self.result(ctx, summary, findings, {k: L[k] for k in ("ph", "k", "glucose", "lactate", "hb")})


class PacuPainMonitor(BaseTool):
    id = "pacu_pain"
    name = "恢復室疼痛評估"
    category = "rule"
    locations = ("PACU",)
    description = "恢復室病人疼痛分數（0–10）過高時提醒。"
    how_it_works = "規則：疼痛分數達門檻且持續 3 分鐘 → 警示。"
    params = [ParamSpec("threshold", "疼痛分數門檻", 7, min=3, max=10)]

    def run(self, ctx, prm):
        pain = ctx.vitals["pain"]
        if pain is None:
            return self.result(ctx, "無疼痛評分")
        findings = []
        if pain >= prm["threshold"] and ctx.sustained_minutes("pain", ">=", prm["threshold"] - 0.5) >= 3:
            findings.append(Finding("warning", "疼痛控制不佳", f"疼痛分數 {pain}/10（心跳 {ctx.vitals['hr']}，血壓 {ctx.vitals['sbp']}/{ctx.vitals['dbp']}）",
                                    "依多模式止痛給予 Fentanyl 或其他止痛藥，並評估呼吸狀況。", {"pain": pain}))
        return self.result(ctx, f"疼痛 {pain}/10", findings, {"pain": pain})


def builtin_rule_tools() -> list[BaseTool]:
    return [IOHDetector(), HypertensionDetector(), HeartRateMonitor(), SpO2Monitor(), VentilationMonitor(),
            MHEarlyWarning(), DepthMonitor(), TemperatureMonitor(), UrineOutputMonitor(), BloodLossMonitor(),
            LabMonitor(), PacuPainMonitor()]
