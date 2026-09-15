"""產生虛構病人基本資料（姓名皆為隨機組合並遮蔽，非真實病人）。"""
from __future__ import annotations

import random

SURNAMES = list("陳林黃張李王吳劉蔡楊許鄭謝洪郭邱曾廖賴徐周葉蘇莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余盧梁趙顏柯翁魏孫戴范方宋鄧")
GIVEN_LAST = list("明華玲芳偉婷雄豪惠君傑宏珍怡安文德美蓉誠翔慧琪國英")

ANES_TYPES = {
    "GA_ETT": {"label": "全身麻醉（氣管內管）", "cls": "GA", "airway": "ETT"},
    "GA_LMA": {"label": "全身麻醉（喉罩）", "cls": "GA", "airway": "LMA"},
    "TIVA": {"label": "全靜脈麻醉（TIVA）", "cls": "GA", "airway": "ETT"},
    "GA_NB": {"label": "全身麻醉＋神經阻斷", "cls": "GA", "airway": "ETT"},
    "SA": {"label": "脊椎麻醉", "cls": "NEURAXIAL", "airway": "NC"},
    "EA": {"label": "硬脊膜外麻醉", "cls": "NEURAXIAL", "airway": "NC"},
    "MAC": {"label": "監測麻醉照護（靜脈鎮靜）", "cls": "MAC", "airway": "NC"},
}

# name, specialty, duration(min), anesthesia options, bleeding risk, foley, weight
SURGERIES = [
    ("腹腔鏡膽囊切除術", "一般外科", (60, 120), ["GA_ETT"], "low", False, 9),
    ("腹腔鏡大腸切除術", "大腸直腸外科", (150, 300), ["GA_ETT"], "mid", True, 6),
    ("全膝關節置換術", "骨科", (90, 150), ["SA", "GA_LMA"], "mid", True, 7),
    ("全髖關節置換術", "骨科", (100, 180), ["SA", "GA_ETT"], "mid", True, 5),
    ("脊椎融合手術", "神經外科", (180, 360), ["GA_ETT", "TIVA"], "high", True, 5),
    ("開顱腫瘤切除術", "神經外科", (240, 420), ["TIVA"], "high", True, 3),
    ("冠狀動脈繞道手術", "心臟血管外科", (240, 360), ["GA_ETT"], "high", True, 2),
    ("剖腹產", "婦產科", (45, 90), ["SA"], "mid", True, 6),
    ("子宮全切除術", "婦產科", (90, 180), ["GA_ETT"], "mid", True, 4),
    ("甲狀腺切除術", "一般外科", (90, 150), ["GA_ETT"], "low", False, 5),
    ("經尿道前列腺刮除術", "泌尿科", (60, 90), ["SA"], "low", True, 5),
    ("腹腔鏡胃袖狀切除術", "一般外科", (120, 200), ["GA_ETT"], "low", True, 3),
    ("肝臟部分切除術", "一般外科", (240, 420), ["GA_ETT"], "high", True, 3),
    ("白內障手術", "眼科", (20, 45), ["MAC"], "none", False, 6),
    ("乳房部分切除術", "乳房外科", (60, 120), ["GA_LMA"], "low", False, 5),
    ("肩關節鏡手術", "骨科", (60, 120), ["GA_NB"], "low", False, 5),
    ("腹腔鏡腎臟切除術", "泌尿科", (150, 240), ["GA_ETT"], "mid", True, 3),
    ("扁桃腺切除術", "耳鼻喉科", (40, 70), ["GA_ETT"], "low", False, 4),
    ("腹股溝疝氣修補術", "一般外科", (45, 90), ["GA_LMA", "SA"], "low", False, 6),
    ("大腸鏡檢查合併息肉切除", "胃腸肝膽科", (25, 50), ["MAC"], "none", False, 5),
]

ALLERGY_CHOICES = ["Penicillin", "Sulfa 類藥物", "NSAIDs", "乳膠（Latex）", "顯影劑（Iodine）", "Morphine"]


def _chance(rng: random.Random, p: float) -> bool:
    return rng.random() < max(0.0, min(1.0, p))


def generate_profile(rng: random.Random, pid: str) -> dict:
    name, specialty, (dmin, dmax), anes_opts, bleed, foley, _ = rng.choices(
        SURGERIES, weights=[s[-1] for s in SURGERIES]
    )[0]

    if specialty == "婦產科" or name.startswith("乳房"):
        sex = "F"
    elif "前列腺" in name:
        sex = "M"
    else:
        sex = rng.choice("MF")

    if name == "剖腹產":
        age = rng.randint(22, 42)
    elif name == "扁桃腺切除術":
        age = rng.randint(18, 45)
    elif name in ("冠狀動脈繞道手術", "全膝關節置換術", "經尿道前列腺刮除術", "白內障手術"):
        age = rng.randint(55, 88)
    else:
        age = int(rng.triangular(20, 90, 62))

    height = rng.gauss(170 if sex == "M" else 158, 6)
    bmi = rng.uniform(36, 48) if "胃袖狀" in name else max(16.5, rng.gauss(24.5, 4.0))
    weight = bmi * (height / 100) ** 2

    comorb = []
    over = max(0, age - 30)
    if _chance(rng, 0.08 + 0.009 * over):
        comorb.append("高血壓")
    if _chance(rng, 0.05 + 0.005 * over) or ("胃袖狀" in name and _chance(rng, 0.4)):
        comorb.append("糖尿病")
    if name == "冠狀動脈繞道手術" or (age > 50 and _chance(rng, 0.03 + 0.004 * (age - 50))):
        comorb.append("冠狀動脈疾病")
    if age > 50 and _chance(rng, 0.07):
        comorb.append("慢性阻塞性肺病")
    if age > 45 and _chance(rng, 0.04 + 0.003 * (age - 45)):
        comorb.append("慢性腎臟病")
    if bmi >= 30:
        comorb.append("肥胖")
        if _chance(rng, 0.45):
            comorb.append("阻塞性睡眠呼吸中止")
    if age > 65 and _chance(rng, 0.08):
        comorb.append("心房顫動病史")
    if _chance(rng, 0.04):
        comorb.append("氣喘")

    serious = len([c for c in comorb if c in ("冠狀動脈疾病", "慢性腎臟病", "慢性阻塞性肺病")])
    if not comorb and age < 60:
        asa = 1
    elif serious == 0 and len(comorb) <= 1 and bmi < 40:
        asa = 2
    else:
        asa = 3
    if asa == 3 and (len(comorb) >= 4 or name in ("冠狀動脈繞道手術", "肝臟部分切除術") and len(comorb) >= 3):
        asa = 4

    anes_code = rng.choice(anes_opts)
    anes = ANES_TYPES[anes_code]

    sbp = rng.gauss(120 + 0.35 * over + (15 if "高血壓" in comorb else 0), 10)
    dbp = rng.gauss(72 + 0.1 * over + (8 if "高血壓" in comorb else 0), 7)
    baseline = {
        "hr": round(rng.gauss(76 - 0.1 * over, 9)),
        "sbp": round(max(95, min(185, sbp))),
        "dbp": round(max(55, min(105, dbp))),
        "spo2": round(rng.uniform(92, 95) if "慢性阻塞性肺病" in comorb else rng.uniform(96, 99)),
        "rr": round(rng.uniform(12, 18)),
        "temp": round(rng.uniform(36.5, 37.1), 1),
    }
    labs0 = {
        "hb": round(rng.gauss(13.8 if sex == "M" else 12.4, 1.2) - (1.5 if "慢性腎臟病" in comorb else 0), 1),
        "k": round(rng.uniform(4.4, 5.1) if "慢性腎臟病" in comorb else rng.uniform(3.6, 4.6), 1),
        "glucose": round(rng.uniform(110, 160) if "糖尿病" in comorb else rng.uniform(85, 120)),
        "lactate": round(rng.uniform(0.7, 1.4), 1),
        "na": round(rng.uniform(136, 143)),
    }

    allergies = ["無已知過敏"] if rng.random() < 0.8 else rng.sample(ALLERGY_CHOICES, k=1)
    masked_name = rng.choice(SURNAMES) + "Ｏ" + rng.choice(GIVEN_LAST)

    return {
        "pid": pid,
        "mrn": f"8{rng.randint(1000000, 9999999)}",
        "name": masked_name,
        "sex": sex,
        "age": age,
        "height_cm": round(height),
        "weight_kg": round(weight, 1),
        "bmi": round(bmi, 1),
        "asa": asa,
        "comorbidities": comorb,
        "allergies": allergies,
        "smoker": _chance(rng, 0.3 if sex == "M" else 0.05),
        "ponv_history": _chance(rng, 0.12),
        "surgery": name,
        "specialty": specialty,
        "planned_min": rng.randint(dmin, dmax),
        "bleed": bleed,
        "foley": foley,
        "anes_code": anes_code,
        "anes_label": anes["label"],
        "anes_class": anes["cls"],
        "airway": anes["airway"],
        "volatile": anes_code in ("GA_ETT", "GA_LMA", "GA_NB"),
        "baseline": baseline,
        "labs0": labs0,
    }
