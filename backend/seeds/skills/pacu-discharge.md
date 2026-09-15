---
id: pacu-discharge
name: 恢復室轉出評估
description: 恢復室病人的轉出條件、疼痛與噁心嘔吐控制。
enabled: true
triggers:
  tools: [aldrete, pacu_pain, apfel_ponv]
  keywords: [轉出, 恢復室, Aldrete, 疼痛, 噁心]
  always: false
use_in: [rounds, chat]
author: 系統示範
---

# 恢復室轉出評估

## 轉出條件
- Aldrete 評分 ≥ 9（活動力、呼吸、循環、意識、血氧各 0–2 分）
- 疼痛分數 ≤ 4，無持續噁心嘔吐
- 生命徵象穩定超過 15–30 分鐘，無活動性出血
- 脊椎麻醉病人感覺／運動阻斷已明顯消退

## 建議處置
- 符合條件：提示可請麻醉醫師確認後轉回病房，並完成交班。
- 疼痛 ≥ 7：多模式止痛（Fentanyl 25 mcg IV 逐次、Acetaminophen、區域阻斷），給藥後注意呼吸。
- 噁心嘔吐：Ondansetron 4 mg IV；已用過則換 Dexamethasone 或其他機轉藥物。
- 恢復延遲：找出低分項目（呼吸、意識、循環）的原因，延長觀察。

## 回報重點
Aldrete 分數與各項、疼痛分數、在恢復室的時間、是否可轉出。
