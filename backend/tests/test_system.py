"""系統測試：模擬器、工具、規則、技能、資料庫持久化、查房、離線對話、AI 代理迴圈（以假 LLM 測試）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.repositories import agent_records
from app.simulator.engine import SimulationEngine
from app.skills.manager import SkillManager
from app.tools.context import PatientContext
from app.tools.rule_engine import CustomRuleTool, RuleError, validate_rule


# ---------------------------------------------------------------- 不需要資料庫
def test_simulator_keeps_50_patients_with_turnover():
    eng = SimulationEngine(seed=1)
    assert len(eng.patients) == 50
    first_ids = set(eng.patients)
    for _ in range(1500):
        eng.step(10)
    assert len(eng.patients) == 50
    assert set(eng.patients) != first_ids, "長時間模擬後應有病人轉出、新病人進入"
    for p in eng.patients.values():
        v = p.vitals()
        assert 25 <= v["hr"] <= 220 and 50 <= v["spo2"] <= 100


def test_intervention_treats_event():
    eng = SimulationEngine(seed=3)
    p = next(p for p in eng.sorted_patients() if p.eligible("bradycardia"))
    ok, _ = eng.inject_event(p.pid, "bradycardia")
    assert ok
    for _ in range(30):
        eng.step(10)
    low_hr = p.vitals()["hr"]
    eng.apply_intervention(p.pid, "atropine")
    for _ in range(40):
        eng.step(10)
    assert p.vitals()["hr"] > low_hr + 10


def test_engine_outbox_only_when_recording():
    eng = SimulationEngine(seed=5, record=True)
    events, vitals = eng.drain_outbox()
    kinds = {k for k, _ in events}
    assert {"run_start", "admit", "event_start"} <= kinds
    assert len(vitals) >= 50 * 150
    assert eng.drain_outbox() == ([], [])
    quiet = SimulationEngine(seed=5)
    assert quiet.drain_outbox() == ([], [])


def test_rule_validation_and_evaluation():
    with pytest.raises(RuleError):
        validate_rule({"name": "", "conditions": []})
    spec = validate_rule({
        "name": "心跳偏快", "severity": "warning", "logic": "all",
        "conditions": [{"field": "hr", "op": ">", "value": 0}, {"field": "location", "op": "==", "value": "OR"}],
    })
    tool = CustomRuleTool(spec)
    eng = SimulationEngine(seed=4)
    p = next(p for p in eng.patients.values() if p.location == "OR")
    assert tool.run(PatientContext(p), {}).findings


# ---------------------------------------------------------------- 資料庫與 API
def test_database_seeded_and_tools_run(state):
    categories = {t.category for t in state.registry.list()}
    assert {"rule", "score", "ml", "dl", "custom_rule", "custom_model", "plugin"} <= categories
    eng = SimulationEngine(seed=2)
    for _ in range(60):
        eng.step(5)
    for p in eng.patients.values():
        for res in state.registry.run_all(PatientContext(p), only_enabled=False):
            assert res.ok, f"{res.tool_id} 在 {p.pid} 發生錯誤：{res.error}"


def test_skills_loaded_from_database(state):
    assert len(state.skills.list()) >= 8
    matched = state.skills.match_findings([{"tool_id": "ioh_detector", "title": "術中低血壓", "detail": ""}])
    assert any(s["id"] == "ioh-management" for s in matched)
    assert SkillManager.checklist(state.skills.get("ioh-management"))


def test_recorder_persists_realtime_dataset(state, run):
    run(state.recorder.flush)
    counts = run(state.db.table_counts, True)
    assert counts["simulation_runs"] >= 1
    assert counts["patients"] >= 50
    assert counts["vital_signs"] >= 50 * 150
    assert counts["clinical_events"] >= 1
    assert state.recorder.last_error is None


def test_round_report_and_alerts_persisted(client, state, run):
    r = client.post("/api/rounds/run", json={"scope": "all"}).json()
    assert r["patients_checked"] == 50 and r["tools_run"] > 500 and r["id"].startswith("R")
    assert client.get(f"/api/rounds/{r['id']}").json()["summary_md"]
    assert any(x["id"] == r["id"] for x in client.get("/api/rounds").json())
    alerts = client.get("/api/alerts").json()
    assert all(a["id"].startswith("AL") for a in alerts)
    stored = run(agent_records.get_report, state.db.sessionmaker, agent_records.parse_code("R", r["id"]))
    assert stored["patients_checked"] == 50


def test_settings_persist_to_database(client, state, run):
    s = client.put("/api/settings/rounds", json={"mode": "schedule", "times": ["23:59", "8:05"]}).json()
    assert s["rounds"]["times"] == ["08:05", "23:59"]
    assert client.put("/api/settings/rounds", json={"interval_minutes": 0}).status_code == 400
    fresh = Settings(state.db.sessionmaker)
    run(fresh.load)
    assert fresh.section("rounds")["times"] == ["08:05", "23:59"]
    client.put("/api/settings/rounds", json={"mode": "interval", "interval_minutes": 2})
    assert client.get("/api/state").json()["schedule"]["next_due"] is not None


def test_tool_config_persists(client, state, run):
    client.put("/api/tools/ioh_detector", json={"enabled": False, "params": {"map_threshold": 60}})
    fresh = Settings(state.db.sessionmaker)
    run(fresh.load)
    assert fresh.tool_enabled("ioh_detector") is False and fresh.tool_params("ioh_detector")["map_threshold"] == 60
    client.put("/api/tools/ioh_detector", json={"enabled": True, "params": {"map_threshold": 65}})


def test_offline_chat_history_persisted(client):
    res = client.post("/api/chat", json={"session_id": "t", "message": "把查房改成每 4 分鐘"}).json()
    assert res["mode"] == "offline" and "4" in res["reply"]
    assert client.get("/api/settings").json()["rounds"]["interval_minutes"] == 4
    pid = client.get("/api/patients").json()[0]["pid"]
    res = client.post("/api/chat", json={"session_id": "t", "message": f"{pid} 狀況"}).json()
    assert pid in res["reply"]
    history = client.get("/api/chat/t").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    client.delete("/api/chat/t")
    assert client.get("/api/chat/t").json()["messages"] == []


def test_custom_rule_and_skill_roundtrip(client):
    spec = {"name": "測試用規則", "severity": "info", "logic": "all",
            "conditions": [{"field": "age", "op": ">=", "value": 0}], "locations": ["OR", "PACU"]}
    saved = client.post("/api/rules", json=spec).json()
    assert saved["id"] in [t["id"] for t in client.get("/api/tools").json()]
    assert client.post("/api/rules/test", json=spec).json()["matches"]
    assert client.delete(f"/api/tools/{saved['id']}").status_code == 200

    skill = client.post("/api/skills", json={"name": "測試技能", "description": "測試", "body": "# 測試\n- 項目",
                                             "triggers": {"tools": [], "keywords": ["測試"], "always": False},
                                             "use_in": ["chat"]}).json()
    assert any(s["id"] == skill["id"] for s in client.get("/api/skills").json())
    assert client.delete(f"/api/skills/{skill['id']}").status_code == 200


def test_action_proposal_confirm_flow(client, state, run):
    pid = client.get("/api/patients").json()[0]["pid"]
    action = run(state.actions.create, pid, "fluid_bolus", "測試建議", "chat", "t")
    assert action["id"].startswith("A") and state.actions.pending_count() == 1
    assert any(a["id"] == action["id"] for a in client.get("/api/actions?status=pending").json())
    resolved = client.post(f"/api/actions/{action['id']}", json={"confirm": True}).json()
    assert resolved["status"] == "confirmed" and state.actions.pending_count() == 0


def test_agent_loop_with_fake_llm(state, run):
    """不需要 API 金鑰：用假的 LLM 驗證「呼叫工具 → 回傳結果 → 產生回答」的代理迴圈。"""

    class FakeLLM:
        available = True

        def __init__(self):
            self.calls = []

        async def create(self, *, system, messages, tools=None, **kw):
            self.calls.append(messages)
            if len(self.calls) == 1:
                block = SimpleNamespace(type="tool_use", id="tu1", name="update_round_settings", input={"interval_minutes": 7})
                return SimpleNamespace(content=[block], stop_reason="tool_use", model="fake")
            result = messages[-1]["content"][0]
            assert result["type"] == "tool_result" and not result["is_error"]
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="已改為每 7 分鐘")], stop_reason="end_turn", model="fake")

    real = state.chat.llm
    state.chat.llm = FakeLLM()
    try:
        res = run(state.chat.handle, "fake", "改成每 7 分鐘查房")
    finally:
        state.chat.llm = real
    assert res["mode"] == "ai" and res["reply"] == "已改為每 7 分鐘"
    assert res["steps"][0]["tool"] == "update_round_settings"
    assert state.settings.section("rounds")["interval_minutes"] == 7


def test_ai_round_summary_with_fake_llm(state, run):
    captured = {}

    class FakeLLM:
        available = True

        async def create(self, *, system, messages, **kw):
            captured["system"] = system
            captured["prompt"] = messages[0]["content"]
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="### 測試摘要")], stop_reason="end_turn", model="fake")

    report = state.rounds.latest()
    assert report is not None
    real = state.rounds.llm
    state.rounds.llm = FakeLLM()
    try:
        run(state.rounds._ai_summary, report)
    finally:
        state.rounds.llm = real
    stored = run(agent_records.get_report, state.db.sessionmaker, report["db_id"])
    assert stored["summary_source"] == "ai" and stored["summary_md"] == "### 測試摘要"
    assert "查房" in captured["prompt"] and "例行查房報告格式" in captured["system"]


def test_train_custom_model_stored_in_database(client):
    meta = client.post("/api/ml/train", json={"name": "測試模型", "target": "y_brady5", "algorithm": "logreg",
                                              "features": ["hr_now", "hr_slope5", "map_now"]}).json()
    assert meta["metrics"]["auc"] is not None
    assert meta["id"] in [t["id"] for t in client.get("/api/tools").json()]
    assert client.delete(f"/api/tools/{meta['id']}").status_code == 200


def test_export_and_state(client):
    csv = client.get("/api/export/vitals.csv?minutes=10")
    assert csv.status_code == 200 and csv.text.count("\n") > 50
    st = client.get("/api/state").json()
    assert st["db"]["ok"] and st["db"]["backend"].startswith("PostgreSQL")
    assert client.get("/api/unknown-endpoint").status_code == 404


def test_migrations_match_models():
    """資料表結構（ORM）與 Alembic 遷移檔一致。"""
    from alembic import command
    from alembic.config import Config

    from app.config import BASE_DIR
    from conftest import TEST_DATABASE_URL

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    cfg.attributes["configure_logger"] = False
    command.check(cfg)
