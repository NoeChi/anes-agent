"""免寫程式的自訂規則。

使用者在網頁上用表單組合條件（例如「年齡 ≥ 70」且「收縮壓 > 170 持續 3 分鐘」），存進資料庫的 rules 資料表，
系統會自動變成一個可在查房時執行的工具。
"""
from __future__ import annotations

import re
import time

from .base import SEVERITY_ORDER, BaseTool, Finding
from .context import OPS, PatientContext


def _vital(key):
    return lambda c: c.vitals.get(key)


def _has(name):
    return lambda c: name in c.comorbidities


def _shock_index(c):
    hr, sbp = c.vitals["hr"], c.vitals["sbp"]
    return round(hr / sbp, 2) if hr and sbp else None


# key: (中文名稱, 單位, 型態, 分組, 取值函式, 是否有歷史資料可判斷持續時間／趨勢)
RULE_FIELDS: dict[str, tuple] = {
    "hr": ("心跳", "次/分", "number", "生命徵象", _vital("hr"), True),
    "sbp": ("收縮壓", "mmHg", "number", "生命徵象", _vital("sbp"), True),
    "dbp": ("舒張壓", "mmHg", "number", "生命徵象", _vital("dbp"), True),
    "map": ("平均動脈壓 MAP", "mmHg", "number", "生命徵象", _vital("map"), True),
    "spo2": ("血氧 SpO₂", "%", "number", "生命徵象", _vital("spo2"), True),
    "etco2": ("呼氣末二氧化碳 EtCO₂", "mmHg", "number", "生命徵象", _vital("etco2"), True),
    "rr": ("呼吸速率", "次/分", "number", "生命徵象", _vital("rr"), True),
    "temp": ("體溫", "°C", "number", "生命徵象", _vital("temp"), True),
    "bis": ("BIS 麻醉深度", "", "number", "生命徵象", _vital("bis"), True),
    "ppeak": ("氣道峰壓", "cmH₂O", "number", "生命徵象", _vital("ppeak"), True),
    "pain": ("疼痛分數", "0–10", "number", "生命徵象", _vital("pain"), True),
    "lab_k": ("血鉀 K", "mmol/L", "number", "檢驗（2 小時內）", lambda c: c.lab("k"), False),
    "lab_glucose": ("血糖", "mg/dL", "number", "檢驗（2 小時內）", lambda c: c.lab("glucose"), False),
    "lab_hb": ("血紅素 Hb", "g/dL", "number", "檢驗（2 小時內）", lambda c: c.lab("hb"), False),
    "lab_lactate": ("乳酸 Lactate", "mmol/L", "number", "檢驗（2 小時內）", lambda c: c.lab("lactate"), False),
    "lab_ph": ("血液 pH", "", "number", "檢驗（2 小時內）", lambda c: c.lab("ph"), False),
    "lab_na": ("血鈉 Na", "mmol/L", "number", "檢驗（2 小時內）", lambda c: c.lab("na"), False),
    "shock_index": ("休克指數", "", "number", "計算值", _shock_index, False),
    "map_drop_pct": ("MAP 較術前下降", "%", "number", "計算值",
                     lambda c: round((1 - c.vitals["map"] / c.baseline_map) * 100) if c.vitals["map"] else None, False),
    "ebl": ("累計出血量", "mL", "number", "計算值", lambda c: round(c.ebl), True),
    "ebl_pct": ("出血量佔總血量", "%", "number", "計算值", lambda c: round(c.ebl / c.ebv * 100, 1), False),
    "urine_rate": ("近 1 小時尿量", "mL/kg/h", "number", "計算值",
                   lambda c: None if c.urine_rate(60) is None else round(c.urine_rate(60), 2), False),
    "minutes_in_location": ("在目前區域的分鐘數", "分鐘", "number", "計算值", lambda c: round(c.minutes_in_location), False),
    "age": ("年齡", "歲", "number", "病人特性", lambda c: c.age, False),
    "weight": ("體重", "kg", "number", "病人特性", lambda c: c.weight, False),
    "bmi": ("BMI", "", "number", "病人特性", lambda c: c.profile["bmi"], False),
    "asa": ("ASA 分級", "", "number", "病人特性", lambda c: c.asa, False),
    "has_htn": ("有高血壓", "", "bool", "病人特性", _has("高血壓"), False),
    "has_dm": ("有糖尿病", "", "bool", "病人特性", _has("糖尿病"), False),
    "has_cad": ("有冠狀動脈疾病", "", "bool", "病人特性", _has("冠狀動脈疾病"), False),
    "has_ckd": ("有慢性腎臟病", "", "bool", "病人特性", _has("慢性腎臟病"), False),
    "has_copd": ("有慢性阻塞性肺病", "", "bool", "病人特性", _has("慢性阻塞性肺病"), False),
    "has_osa": ("有睡眠呼吸中止", "", "bool", "病人特性", _has("阻塞性睡眠呼吸中止"), False),
    "location": ("所在區域", "", "select", "情境", lambda c: c.location, False),
    "phase": ("麻醉階段", "", "select", "情境", lambda c: c.phase, False),
    "anes_class": ("麻醉方式", "", "select", "情境", lambda c: c.anes_class, False),
    "sex": ("性別", "", "select", "病人特性", lambda c: c.sex, False),
    "rhythm": ("心電圖節律", "", "text", "生命徵象", lambda c: c.rhythm, False),
}

SELECT_OPTIONS = {
    "location": [["OR", "手術室"], ["PACU", "恢復室"]],
    "phase": [["induction", "麻醉誘導"], ["maintenance", "麻醉維持"], ["emergence", "手術結束／甦醒"], ["pacu", "恢復室"]],
    "anes_class": [["GA", "全身麻醉"], ["NEURAXIAL", "脊椎／硬膜外麻醉"], ["MAC", "靜脈鎮靜"]],
    "sex": [["M", "男"], ["F", "女"]],
}

OPERATORS = {
    "number": [[">", "大於"], [">=", "大於等於"], ["<", "小於"], ["<=", "小於等於"], ["==", "等於"], ["!=", "不等於"],
               ["rises_by", "在 N 分鐘內上升超過"], ["falls_by", "在 N 分鐘內下降超過"]],
    "bool": [["is_true", "是"], ["is_false", "否"]],
    "select": [["==", "是"], ["!=", "不是"]],
    "text": [["contains", "包含文字"], ["==", "等於"], ["!=", "不等於"]],
}


class RuleError(ValueError):
    pass


def field_catalog() -> dict:
    return {
        "fields": [
            {"key": k, "label": v[0], "unit": v[1], "type": v[2], "group": v[3], "history": v[5],
             "options": SELECT_OPTIONS.get(k)}
            for k, v in RULE_FIELDS.items()
        ],
        "operators": OPERATORS,
    }


def validate_rule(spec: dict) -> dict:
    name = str(spec.get("name", "")).strip()
    if not name:
        raise RuleError("請輸入規則名稱")
    if len(name) > 40:
        raise RuleError("規則名稱請在 40 字以內")
    severity = spec.get("severity", "warning")
    if severity not in SEVERITY_ORDER:
        raise RuleError("嚴重度只能是 提示／警示／危急")
    logic = spec.get("logic", "all")
    if logic not in ("all", "any"):
        raise RuleError("條件組合只能是「全部符合」或「任一符合」")
    conditions = spec.get("conditions") or []
    if not 1 <= len(conditions) <= 10:
        raise RuleError("請設定 1 到 10 個條件")
    clean_conditions = []
    for i, cond in enumerate(conditions, 1):
        field = cond.get("field")
        if field not in RULE_FIELDS:
            raise RuleError(f"第 {i} 個條件：請選擇欄位")
        ftype = RULE_FIELDS[field][2]
        op = cond.get("op")
        if op not in {o[0] for o in OPERATORS[ftype]}:
            raise RuleError(f"第 {i} 個條件：比較方式不適用於「{RULE_FIELDS[field][0]}」")
        c = {"field": field, "op": op}
        if ftype == "number":
            try:
                c["value"] = float(cond.get("value"))
            except (TypeError, ValueError):
                raise RuleError(f"第 {i} 個條件：「{RULE_FIELDS[field][0]}」的數值必須是數字") from None
        elif ftype in ("select", "text"):
            value = str(cond.get("value", "")).strip()
            if not value:
                raise RuleError(f"第 {i} 個條件：請填入比較值")
            c["value"] = value
        if op in ("rises_by", "falls_by"):
            if not RULE_FIELDS[field][5]:
                raise RuleError(f"第 {i} 個條件：「{RULE_FIELDS[field][0]}」沒有趨勢資料")
            try:
                c["window_min"] = max(1.0, min(60.0, float(cond.get("window_min") or 10)))
            except (TypeError, ValueError):
                raise RuleError(f"第 {i} 個條件：時間窗必須是數字") from None
        elif cond.get("duration_min") not in (None, "", 0, "0") and RULE_FIELDS[field][5] and op in OPS:
            try:
                c["duration_min"] = max(0.0, min(60.0, float(cond["duration_min"])))
            except (TypeError, ValueError):
                raise RuleError(f"第 {i} 個條件：持續時間必須是數字") from None
        clean_conditions.append(c)
    locations = [l for l in spec.get("locations", ["OR", "PACU"]) if l in ("OR", "PACU")] or ["OR", "PACU"]
    rule_id = spec.get("id") or f"rule_{int(time.time() * 1000):x}"
    if not re.fullmatch(r"rule_[0-9a-z_]+", rule_id):
        raise RuleError("規則代碼格式錯誤")
    return {
        "id": rule_id,
        "name": name,
        "description": str(spec.get("description", "")).strip()[:300],
        "severity": severity,
        "logic": logic,
        "conditions": clean_conditions,
        "locations": locations,
        "message": str(spec.get("message", "")).strip()[:300],
        "suggestion": str(spec.get("suggestion", "")).strip()[:500],
        "author": str(spec.get("author", "使用者")).strip()[:40] or "使用者",
        "updated_at": time.strftime("%Y-%m-%d %H:%M"),
    }


def describe_condition(c: dict) -> str:
    label, unit, ftype = RULE_FIELDS[c["field"]][:3]
    ops = dict(OPERATORS[ftype])
    if ftype == "bool":
        return f"{label}：{ops[c['op']]}"
    value = c.get("value")
    if ftype == "select":
        value = dict(SELECT_OPTIONS[c["field"]]).get(value, value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if c["op"] in ("rises_by", "falls_by"):
        verb = "上升" if c["op"] == "rises_by" else "下降"
        return f"{label} 在 {c['window_min']:g} 分鐘內{verb}超過 {value}{unit}"
    text = f"{label} {ops[c['op']]} {value}{unit}"
    if c.get("duration_min"):
        text += f"（持續 {c['duration_min']:g} 分鐘）"
    return text


def evaluate_condition(ctx: PatientContext, c: dict) -> tuple[bool, object]:
    getter = RULE_FIELDS[c["field"]][4]
    actual = getter(ctx)
    op = c["op"]
    if op == "is_true":
        return bool(actual), actual
    if op == "is_false":
        return not actual, actual
    if actual is None:
        return False, None
    if op == "contains":
        return str(c["value"]) in str(actual), actual
    if op in ("rises_by", "falls_by"):
        change = ctx.change_over(c["field"], c["window_min"])
        if change is None:
            return False, actual
        return (change >= c["value"]) if op == "rises_by" else (-change >= c["value"]), actual
    if not OPS[op](actual, c["value"]):
        return False, actual
    if c.get("duration_min"):
        return ctx.sustained_minutes(c["field"], op, c["value"]) >= c["duration_min"], actual
    return True, actual


def _format_message(template: str, ctx: PatientContext) -> str:
    def repl(m):
        key = m.group(1)
        if key in ("pid", "bed", "name"):
            return str(getattr(ctx, key))
        if key in RULE_FIELDS:
            val = RULE_FIELDS[key][4](ctx)
            return "—" if val is None else str(val)
        return m.group(0)

    return re.sub(r"\{(\w+)\}", repl, template)


class CustomRuleTool(BaseTool):
    category = "custom_rule"
    builtin = False

    def __init__(self, spec: dict):
        self.spec = spec
        self.id = spec["id"]
        self.name = spec["name"]
        self.description = spec.get("description") or "使用者自訂規則"
        joiner = "，而且" if spec["logic"] == "all" else "，或"
        self.how_it_works = "當 " + joiner.join(describe_condition(c) for c in spec["conditions"]) + " 時提醒。"
        self.locations = tuple(spec["locations"])
        self.params = []

    def run(self, ctx, params):
        results = [(c, *evaluate_condition(ctx, c)) for c in self.spec["conditions"]]
        hits = [ok for _, ok, _ in results]
        matched = all(hits) if self.spec["logic"] == "all" else any(hits)
        values = {c["field"]: actual for c, _, actual in results}
        findings = []
        if matched:
            met = [describe_condition(c) + f"（目前 {actual}）" for c, ok, actual in results if ok]
            detail = _format_message(self.spec["message"], ctx) if self.spec.get("message") else "符合條件：" + "；".join(met)
            findings.append(Finding(self.spec["severity"], self.name, detail, self.spec.get("suggestion", ""), values))
        summary = "符合" if matched else f"未符合（{sum(hits)}/{len(hits)} 個條件成立）"
        return self.result(ctx, summary, findings, values)

    def describe(self):
        d = super().describe()
        d["spec"] = self.spec
        return d
