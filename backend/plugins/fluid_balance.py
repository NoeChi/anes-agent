"""Python 外掛工具範例：術中輸液平衡。

給會寫程式的人：在 plugins/ 資料夾放一個 .py 檔，定義繼承 BaseTool 的類別，
重新啟動（或在「工具庫」按「重新載入」）後就會出現在工具庫，並在查房時自動執行。

可用的病人資料（ctx）：
  ctx.vitals            最新生命徵象 dict（hr, sbp, dbp, map, spo2, etco2, rr, temp, bis, ppeak, pain）
  ctx.weight / age / sex / asa / comorbidities / surgery / location / phase
  ctx.ebl / ctx.urine / ctx.fluids   累計出血、尿量、輸入量（mL）
  ctx.labs              最近檢驗值 dict（可能為 None）
  ctx.series(field, 分鐘) / ctx.change_over(field, 分鐘) / ctx.sustained_minutes(field, op, 值)
  ctx.features          機器學習特徵 dict
"""
from app.tools.base import BaseTool, Finding, ParamSpec


class FluidBalance(BaseTool):
    id = "plugin_fluid_balance"
    name = "術中輸液平衡"
    description = "計算（輸液＋輸血）−（出血＋尿量），以 mL/kg 表示，提醒輸液過多或不足。"
    how_it_works = "計算：淨平衡 = 輸入量 − 出血量 − 尿量，再除以體重。高於上限 → 輸液可能過多；低於下限 → 可能容積不足。"
    locations = ("OR",)
    params = [
        ParamSpec("high", "正平衡上限", 40, unit="mL/kg", min=10, max=100),
        ParamSpec("low", "負平衡下限", -10, unit="mL/kg", min=-50, max=0),
    ]

    def run(self, ctx, params):
        out = ctx.ebl + (ctx.urine or 0)
        balance = ctx.fluids - out
        per_kg = balance / ctx.weight
        findings = []
        if per_kg > params["high"]:
            findings.append(Finding("warning", "輸液正平衡偏多", f"淨平衡 +{balance:.0f} mL（{per_kg:+.0f} mL/kg）",
                                    "評估是否有輸液過多（肺水腫、組織水腫）；考慮目標導向輸液策略。", {"balance_ml_kg": round(per_kg, 1)}))
        elif per_kg < params["low"]:
            findings.append(Finding("warning", "輸液負平衡", f"淨平衡 {balance:.0f} mL（{per_kg:+.0f} mL/kg）",
                                    "出血與尿量超過輸入量，評估容積狀態並補充輸液或血品。", {"balance_ml_kg": round(per_kg, 1)}))
        summary = f"輸入 {ctx.fluids:.0f} mL，輸出 {out:.0f} mL，淨平衡 {per_kg:+.0f} mL/kg"
        return self.result(ctx, summary, findings, {"balance_ml": round(balance), "balance_ml_kg": round(per_kg, 1)})
