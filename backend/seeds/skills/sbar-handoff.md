---
id: sbar-handoff
name: SBAR 交班
description: 使用者要求交班或整理某位病人的狀況時，用 SBAR 格式輸出。
enabled: true
triggers:
  tools: []
  keywords: [交班, SBAR, 摘要這位, 整理病人]
  always: false
use_in: [chat]
author: 系統示範
---

# SBAR 交班格式

請先用工具取得病人的最新資料、趨勢與工具判讀結果，再依下列格式輸出：

## S — Situation（現況）
床位、病號、年齡性別、手術名稱、麻醉方式、目前階段與已進行時間；一句話說明目前最重要的問題。

## B — Background（背景）
ASA 分級、共病、過敏史、術中重要事件（出血量、輸液、輸血、使用過的升壓劑或處置）。

## A — Assessment（評估）
最新生命徵象與重要趨勢（數字＋單位）、最近檢驗值、各工具的判讀結果（含 AI 預測機率）。

## R — Recommendation（建議）
接下來 30 分鐘需要注意與執行的事項，列 2–4 點。

## 注意
- 只能使用工具回傳的資料，不可編造。
- 若資料不足，直接寫「無資料」。
