"""AI 助理對話：Claude + 工具呼叫的代理迴圈；沒有 API 金鑰時交給離線模式。

畫面上的對話紀錄存入資料庫（chat_messages）；送給 Claude 的完整上下文（含工具呼叫與思考區塊）保留在記憶體。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime

from ..bus import EventBus
from ..repositories import agent_records as records
from ..simulator.engine import SimulationEngine
from ..skills.manager import SkillManager
from .llm import LLMClient, friendly_error
from .offline import OfflineResponder
from .toolbox import AgentToolbox, ToolError

MAX_STEPS = 16
MAX_HISTORY_MESSAGES = 120

SYSTEM_PROMPT = """你是「麻醉 AI 查房助理」，在麻醉科展示系統中協助麻醉醫師與護理師。
系統中有 50 位**模擬**病人（手術室 OR 與恢復室 PACU），生命徵象即時更新；所有資料皆為模擬，不是真實病人。

## 你可以做的事
- 查詢病人清單、單一病人詳情與生命徵象趨勢
- 執行工具庫的工具（規則、臨床評分、機器學習／深度學習模型、使用者自訂規則）並解讀結果
- 讀取技能（SOP）並依內容給建議；也可以替使用者撰寫或修改技能
- 查看或立即執行查房、查看與確認警示
- 依使用者要求修改自動查房設定（頻率、時間點、時段、範圍）、調整工具門檻、建立自訂規則
- 提出處置建議（propose_intervention），由使用者在畫面上確認後才會執行

## 工作原則
1. 回答前先用工具取得資料。數值附上單位與時間，不可編造工具沒有回傳的資料。
2. 使用繁體中文，精簡條列；病人以「床位（病號）」稱呼。
3. 涉及處置流程時，先從技能清單找相關技能並用 load_skill 載入，依其內容回答。
4. 你的建議是決策輔助，最後由臨床人員判斷。危急狀況放在最前面並清楚標示。
5. 修改設定、建立規則或技能時：指示明確就直接執行並回報結果；有歧義時先簡短確認。
6. 使用者用口語描述病人（「5 號床」「OR 5」「剛才出血那位」）時，先用 list_patients 找到正確病號。
7. AI 模型的預測要說明是預測機率，需臨床確認。

## 可用技能（需要時用 load_skill 讀取完整內容）
{skills}
"""


class ChatSession:
    def __init__(self, sid: str):
        self.id = sid
        self.messages: list[dict] = []
        self.lock = asyncio.Lock()
        self.updated = time.time()


class ChatAgent:
    def __init__(self, llm: LLMClient, toolbox: AgentToolbox, skills: SkillManager, offline: OfflineResponder,
                 bus: EventBus, engine: SimulationEngine, sessionmaker):
        self.llm = llm
        self.toolbox = toolbox
        self.skills = skills
        self.offline = offline
        self.bus = bus
        self.engine = engine
        self.sm = sessionmaker
        self.sessions: dict[str, ChatSession] = {}

    def session(self, sid: str | None) -> ChatSession:
        sid = (sid or uuid.uuid4().hex[:12])[:40]
        if sid not in self.sessions:
            self.sessions[sid] = ChatSession(sid)
        return self.sessions[sid]

    async def history(self, sid: str) -> list[dict]:
        return await records.list_chat_messages(self.sm, sid)

    async def reset(self, sid: str) -> None:
        self.sessions.pop(sid, None)
        await records.delete_chat_session(self.sm, sid)

    async def handle(self, sid: str | None, text: str) -> dict:
        session = self.session(sid)
        text = text.strip()[:4000]
        async with session.lock:
            await records.add_chat_message(self.sm, session.id, "user", text)
            if self.llm.available:
                result = await self._handle_llm(session, text)
            else:
                result = await self.offline.respond(session.id, text)
                result["mode"] = "offline"
            await records.add_chat_message(self.sm, session.id, "assistant", result["reply"], result.get("steps", []),
                                           result["mode"], result.get("error"))
            session.updated = time.time()
            result["session_id"] = session.id
            return result

    async def _emit(self, sid: str, step: dict) -> None:
        await self.bus.publish("chat_step", {"session_id": sid, **step})

    async def _handle_llm(self, session: ChatSession, text: str) -> dict:
        note = ""
        if len(session.messages) > MAX_HISTORY_MESSAGES:
            session.messages = []
            note = "（對話過長，已自動開啟新的對話脈絡）\n\n"
        stamp = datetime.fromtimestamp(self.engine.t).strftime("%H:%M")
        messages = list(session.messages) + [{"role": "user", "content": f"[目前模擬時間 {stamp}]\n{text}"}]
        system = SYSTEM_PROMPT.format(skills=self.skills.catalog_text())
        tools = self.toolbox.definitions()
        steps: list[dict] = []
        response = None
        try:
            for _ in range(MAX_STEPS):
                response = await self.llm.create(system=system, messages=messages, tools=tools)
                if response.stop_reason == "refusal":
                    return {"reply": note + "AI 無法回應這個請求，請換個方式描述。", "steps": steps, "mode": "ai"}
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason == "pause_turn":
                    continue
                if response.stop_reason != "tool_use":
                    break
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    step = {"id": block.id, "tool": block.name, "label": self.toolbox.step_label(block.name, block.input),
                            "status": "running"}
                    await self._emit(session.id, step)
                    try:
                        output = await self.toolbox.execute(block.name, block.input, session.id)
                        is_error = False
                        step["status"] = "done"
                    except ToolError as exc:
                        output = f"錯誤：{exc}"
                        is_error = True
                        step["status"] = "error"
                        step["error"] = str(exc)
                    except Exception as exc:  # 工具內部錯誤回報給模型，而不是中斷對話
                        output = f"工具執行失敗：{type(exc).__name__}: {exc}"
                        is_error = True
                        step["status"] = "error"
                        step["error"] = output
                    steps.append(step)
                    await self._emit(session.id, step)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error})
                messages.append({"role": "user", "content": results})
            else:
                note += "（已達單次工具呼叫上限，以下為目前結果）\n\n"
        except Exception as exc:
            return {"reply": f"⚠️ {friendly_error(exc)}", "steps": steps, "mode": "ai", "error": friendly_error(exc)}

        reply = "".join(b.text for b in response.content if b.type == "text").strip() if response else ""
        if response is not None and response.stop_reason == "max_tokens":
            reply += "\n\n（回覆因長度上限被截斷）"
        if messages[-1]["role"] == "user":
            # 迴圈因步數上限結束，最後一則是工具結果；補一則說明讓歷史保持「使用者/助理」交替
            messages.append({"role": "assistant", "content": reply or "（未完成）"})
        session.messages = messages
        return {"reply": note + (reply or "（AI 沒有產生文字回覆）"), "steps": steps, "mode": "ai",
                "model": getattr(response, "model", None)}
