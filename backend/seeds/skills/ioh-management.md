---
id: ioh-management
name: 術中低血壓處置
description: 當偵測到或 AI 預測術中低血壓時，依本流程評估原因並提出處置建議。
enabled: true
triggers:
  tools: [ioh_detector, ioh_predictor, shock_index]
  keywords: [低血壓, 血壓低, 血壓下降, hypotension]
  always: false
use_in: [rounds, chat]
author: 系統示範
---

# 術中低血壓處置（IOH）

## 定義
- MAP < 65 mmHg，或收縮壓較術前基準下降 > 20–30%。
- 持續時間越久，急性腎損傷與心肌損傷風險越高（MAP < 65 累積超過 10 分鐘即有意義）。

## 評估步驟
1. 確認量測正確（壓脈帶大小、動脈導管高度與波形）。
2. 看**趨勢**：是突然下降還是逐漸下降？心跳同時上升（低血容／出血）還是下降（迷走、藥物）？
3. 查出血量、尿量、輸液量與最近一次 Hb。
4. 評估麻醉深度（BIS 是否過低、麻醉氣體濃度是否過高）。
5. 考慮其他原因：過敏反應、氣胸、心肌缺血、手術壓迫大血管、氣腹壓力。

## 建議處置
- 心跳正常或偏慢：Phenylephrine 50–100 mcg IV 或 Ephedrine 5–10 mg IV。
- 疑似低血容：輸液 bolus 250 mL，評估反應。
- BIS < 40 或麻醉過深：降低麻醉藥物濃度。
- 持續需要升壓劑：考慮 Norepinephrine 輸注，並尋找根本原因。
- AI 預測高風險但尚未低血壓：提早備妥升壓劑、檢視麻醉深度，縮短血壓量測間隔。

## 回報重點
寫出 MAP 數值、低於門檻的持續分鐘數、相對術前基準的下降比例，以及最可能的原因。
