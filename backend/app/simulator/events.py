"""臨床事件（病況變化）與處置的定義。

每個事件描述：在哪些情境可能發生、對生理數值的影響（effects），以及哪些處置有效（treatments，數字為效果強度 0~1）。
effects 的鍵：
  hr / spo2 / etco2 / rr / bis / ppeak / pain：絕對值增減
  map_pct：平均動脈壓百分比變化（-0.3 = 下降 30%）
  temp_rate：每分鐘體溫變化（°C）
  ebl_rate：每分鐘額外出血量（mL）
  uo_factor：尿量倍率增減（-0.8 = 減少 80%）
  k / glucose / lactate：檢驗值增減
  hr_noise：心跳不規則程度
  ponv：噁心嘔吐
  rhythm：心電圖節律描述
"""
from __future__ import annotations

EVENTS: dict[str, dict] = {
    "hypotension": {
        "label": "術中低血壓",
        "locations": {"OR"},
        "onset": (2, 5), "duration": (20, 50), "weight": 5.0,
        "effects": {"map_pct": -0.34, "hr": 6},
        "treatments": {"vasopressor": 0.65, "fluid_bolus": 0.3, "reduce_anesthetic": 0.3},
        "desc": "血壓逐漸下降（麻醉藥物血管擴張、相對低血容）。",
    },
    "hypertension": {
        "label": "術中高血壓",
        "locations": {"OR"},
        "onset": (2, 5), "duration": (15, 40), "weight": 2.0,
        "effects": {"map_pct": 0.3, "hr": 12},
        "treatments": {"antihypertensive": 0.75, "increase_anesthetic": 0.4, "analgesic": 0.3},
        "desc": "手術刺激或疼痛導致血壓上升。",
    },
    "hemorrhage": {
        "label": "急性出血",
        "locations": {"OR"},
        "requires": "bleed_risk",
        "onset": (5, 10), "duration": None, "weight": 1.2,
        "effects": {"ebl_rate": 90, "map_pct": -0.32, "hr": 35, "lactate": 3.0, "spo2": -1},
        "treatments": {"surgical_control": 0.55, "transfusion": 0.35, "fluid_bolus": 0.15, "vasopressor": 0.15},
        "desc": "持續大量出血，心跳上升、血壓下降、乳酸上升；不處理不會自行緩解。",
    },
    "bradycardia": {
        "label": "心搏過緩",
        "locations": {"OR", "PACU"},
        "onset": (1, 2), "duration": (5, 20), "weight": 2.0,
        "effects": {"hr": -32, "map_pct": -0.12, "rhythm": "竇性心搏過緩"},
        "treatments": {"atropine": 0.85},
        "desc": "迷走神經反射或藥物造成心跳變慢。",
    },
    "desaturation": {
        "label": "低血氧（支氣管痙攣）",
        "locations": {"OR"}, "anes": {"GA"},
        "onset": (1, 3), "duration": (15, 40), "weight": 1.5,
        "effects": {"spo2": -13, "etco2": 9, "ppeak": 14, "hr": 12},
        "treatments": {"bronchodilator": 0.6, "airway_management": 0.45, "increase_anesthetic": 0.2},
        "desc": "氣道阻力上升，血氧下降、呼氣末二氧化碳上升。",
    },
    "malignant_hyperthermia": {
        "label": "惡性高熱",
        "locations": {"OR"}, "anes": {"GA"}, "requires": "volatile",
        "onset": (10, 15), "duration": None, "weight": 0.05,
        "effects": {"etco2": 38, "temp_rate": 0.07, "hr": 45, "k": 2.2, "lactate": 5.0, "map_pct": 0.05,
                    "rhythm": "竇性心搏過速"},
        "treatments": {"dantrolene": 0.9, "stop_volatile": 0.25, "cooling": 0.2},
        "desc": "罕見但致命：EtCO₂ 急速上升、心搏過速、體溫上升、高血鉀。",
    },
    "anaphylaxis": {
        "label": "過敏性休克",
        "locations": {"OR"},
        "onset": (1, 3), "duration": None, "weight": 0.1,
        "effects": {"map_pct": -0.5, "hr": 40, "spo2": -9, "ppeak": 12, "etco2": -8, "rhythm": "竇性心搏過速"},
        "treatments": {"epinephrine": 0.8, "fluid_bolus": 0.2, "airway_management": 0.1},
        "desc": "給藥後血壓驟降、心搏過速、氣道壓上升。",
    },
    "light_anesthesia": {
        "label": "麻醉深度過淺",
        "locations": {"OR"}, "anes": {"GA"}, "phases": {"maintenance"},
        "onset": (2, 4), "duration": (10, 25), "weight": 2.0,
        "effects": {"bis": 28, "hr": 18, "map_pct": 0.22},
        "treatments": {"increase_anesthetic": 0.85, "analgesic": 0.3},
        "desc": "BIS 上升、心跳血壓上升，有術中知曉風險。",
    },
    "deep_anesthesia": {
        "label": "麻醉過深",
        "locations": {"OR"}, "anes": {"GA"}, "phases": {"maintenance"},
        "onset": (3, 6), "duration": (15, 40), "weight": 1.5,
        "effects": {"bis": -17, "map_pct": -0.14, "hr": -5},
        "treatments": {"reduce_anesthetic": 0.85},
        "desc": "BIS 過低合併血壓下降。",
    },
    "hypothermia": {
        "label": "低體溫",
        "locations": {"OR"},
        "onset": (5, 10), "duration": (60, 120), "weight": 1.5,
        "effects": {"temp_rate": -0.045},
        "treatments": {"warming": 0.85},
        "desc": "體溫持續下降。",
    },
    "hyperkalemia": {
        "label": "高血鉀",
        "locations": {"OR"}, "requires": "ckd",
        "onset": (8, 15), "duration": None, "weight": 0.4,
        "effects": {"k": 2.4, "hr": -10, "rhythm": "高尖 T 波"},
        "treatments": {"calcium_insulin": 0.85},
        "desc": "血鉀上升，心電圖出現高尖 T 波。",
    },
    "hyperglycemia": {
        "label": "高血糖",
        "locations": {"OR", "PACU"}, "requires": "dm",
        "onset": (15, 25), "duration": None, "weight": 1.2,
        "effects": {"glucose": 170},
        "treatments": {"insulin": 0.8},
        "desc": "糖尿病病人手術壓力下血糖上升。",
    },
    "oliguria": {
        "label": "寡尿",
        "locations": {"OR"}, "requires": "foley",
        "onset": (10, 20), "duration": (40, 90), "weight": 1.0,
        "effects": {"uo_factor": -0.8},
        "treatments": {"fluid_bolus": 0.5, "vasopressor": 0.2},
        "desc": "尿量明顯減少。",
    },
    "atrial_fibrillation": {
        "label": "新發心房顫動",
        "locations": {"OR", "PACU"}, "requires": "age55",
        "onset": (1, 2), "duration": (20, 60), "weight": 1.0,
        "effects": {"hr": 50, "map_pct": -0.12, "hr_noise": 9, "rhythm": "心房顫動"},
        "treatments": {"antiarrhythmic": 0.75},
        "desc": "心跳快且不規則。",
    },
    "pacu_pain": {
        "label": "術後疼痛控制不佳",
        "locations": {"PACU"},
        "onset": (3, 6), "duration": (30, 60), "weight": 3.0,
        "effects": {"pain": 5, "hr": 16, "map_pct": 0.14, "rr": 5},
        "treatments": {"analgesic": 0.75},
        "desc": "疼痛分數上升，伴隨心跳血壓上升。",
    },
    "ponv": {
        "label": "術後噁心嘔吐",
        "locations": {"PACU"},
        "onset": (2, 5), "duration": (15, 40), "weight": 2.0,
        "effects": {"ponv": 1, "hr": 8, "map_pct": 0.04},
        "treatments": {"antiemetic": 0.85},
        "desc": "病人噁心、嘔吐。",
    },
    "resp_depression": {
        "label": "鴉片類藥物呼吸抑制",
        "locations": {"PACU"},
        "onset": (4, 8), "duration": (30, 60), "weight": 1.0,
        "effects": {"rr": -9, "spo2": -10, "etco2": 14, "pain": -2},
        "treatments": {"naloxone": 0.8, "airway_management": 0.45},
        "desc": "呼吸變慢變淺，血氧下降、二氧化碳上升。",
    },
}

INTERVENTIONS: dict[str, dict] = {
    "vasopressor": {"label": "升壓劑（Phenylephrine / Norepinephrine）", "transient": ({"map_pct": 0.12, "hr": -3}, 300)},
    "fluid_bolus": {"label": "輸液 Bolus 250 mL", "fluids": 250, "transient": ({"map_pct": 0.05}, 600)},
    "transfusion": {"label": "輸血 PRBC 1U（約 250 mL）", "blood": 250, "transient": ({"map_pct": 0.06}, 900)},
    "surgical_control": {"label": "通知外科醫師止血"},
    "atropine": {"label": "Atropine 0.5 mg IV", "transient": ({"hr": 15}, 300)},
    "airway_management": {"label": "氣道處置／FiO₂ 提高至 100%", "transient": ({"spo2": 2}, 600)},
    "bronchodilator": {"label": "支氣管擴張劑（Salbutamol 吸入）"},
    "dantrolene": {"label": "Dantrolene 2.5 mg/kg IV"},
    "stop_volatile": {"label": "停用揮發性麻醉氣體，改 TIVA"},
    "cooling": {"label": "主動降溫"},
    "epinephrine": {"label": "Epinephrine 50 mcg IV", "transient": ({"map_pct": 0.2, "hr": 10}, 300)},
    "increase_anesthetic": {"label": "加深麻醉（提高濃度／追加藥物）", "transient": ({"bis": -8, "map_pct": -0.05}, 600)},
    "reduce_anesthetic": {"label": "減淺麻醉（降低濃度）", "transient": ({"bis": 6, "map_pct": 0.05}, 600)},
    "warming": {"label": "主動保暖（熱風毯／輸液加溫）"},
    "calcium_insulin": {"label": "Calcium gluconate＋Insulin/Glucose"},
    "insulin": {"label": "Regular Insulin IV"},
    "antiarrhythmic": {"label": "抗心律不整藥物（Amiodarone）"},
    "antihypertensive": {"label": "降壓藥（Nicardipine / Labetalol）", "transient": ({"map_pct": -0.1}, 600)},
    "analgesic": {"label": "止痛藥（Fentanyl 25 mcg IV）", "transient": ({"pain": -2}, 1200)},
    "antiemetic": {"label": "止吐藥（Ondansetron 4 mg IV）"},
    "naloxone": {"label": "Naloxone 0.04 mg IV", "transient": ({"rr": 4}, 600)},
    "draw_abg": {"label": "抽血檢驗（ABG／電解質／血糖）"},
}


def event_catalog() -> list[dict]:
    return [
        {
            "id": key,
            "label": spec["label"],
            "desc": spec["desc"],
            "locations": sorted(spec["locations"]),
            "treatments": [
                {"id": t, "label": INTERVENTIONS[t]["label"], "efficacy": eff}
                for t, eff in spec["treatments"].items()
            ],
        }
        for key, spec in EVENTS.items()
    ]


def intervention_catalog() -> list[dict]:
    return [{"id": key, "label": spec["label"]} for key, spec in INTERVENTIONS.items()]
