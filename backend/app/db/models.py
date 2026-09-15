"""資料表定義（SQLAlchemy 2.0 ORM）。

分成三群：
- 設定與知識：app_settings、tool_configs、rules、skills、ml_models
- 即時模擬資料集：simulation_runs、patients、vital_signs、lab_results、clinical_events、interventions、patient_notes
- AI Agent 紀錄：round_reports、alerts、action_proposals、chat_messages
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, BigIntPK, JSONType, TimestampMixin


# ---------------------------------------------------------------- 設定與知識
class AppSetting(Base):
    """系統設定（llm / rounds / simulation），每個區塊一列。"""
    __tablename__ = "app_settings"

    section: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ToolConfig(Base):
    """工具的啟用狀態與使用者調整過的參數（沒有列＝啟用且使用預設值）。"""
    __tablename__ = "tool_configs"

    tool_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Rule(TimestampMixin, Base):
    """免寫程式建立的自訂規則。"""
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(10))
    logic: Mapped[str] = mapped_column(String(5))
    conditions: Mapped[list] = mapped_column(JSONType)
    locations: Mapped[list] = mapped_column(JSONType)
    message: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(40), default="使用者")


class Skill(TimestampMixin, Base):
    """技能（給 AI 的 SOP）。"""
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger_tools: Mapped[list] = mapped_column(JSONType, default=list)
    keywords: Mapped[list] = mapped_column(JSONType, default=list)
    always: Mapped[bool] = mapped_column(Boolean, default=False)
    use_in: Mapped[list] = mapped_column(JSONType, default=list)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(40), default="使用者")


class MLModel(TimestampMixin, Base):
    """機器學習／深度學習模型：說明（meta）與模型檔（artifact，joblib 位元組）。"""
    __tablename__ = "ml_models"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20))  # builtin / no-code-trainer / upload
    kind: Mapped[str] = mapped_column(String(20))  # classifier / anomaly
    meta: Mapped[dict] = mapped_column(JSONType)
    artifact: Mapped[bytes] = mapped_column(LargeBinary)


# ---------------------------------------------------------------- 即時模擬資料集
class SimulationRun(Base):
    """一次模擬（系統啟動或按下重置就開始新的一次）。"""
    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sim_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    n_patients: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(Integer)

    patients: Mapped[list[Patient]] = relationship(back_populates="run", passive_deletes=True)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("run_id", "pid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id", ondelete="CASCADE"), index=True)
    pid: Mapped[str] = mapped_column(String(10))
    mrn: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(20))
    sex: Mapped[str] = mapped_column(String(1))
    age: Mapped[int] = mapped_column(Integer)
    height_cm: Mapped[int] = mapped_column(Integer)
    weight_kg: Mapped[float] = mapped_column(Float)
    bmi: Mapped[float] = mapped_column(Float)
    asa: Mapped[int] = mapped_column(Integer)
    surgery: Mapped[str] = mapped_column(String(60))
    specialty: Mapped[str] = mapped_column(String(40))
    anes_code: Mapped[str] = mapped_column(String(10))
    anes_label: Mapped[str] = mapped_column(String(40))
    comorbidities: Mapped[list] = mapped_column(JSONType, default=list)
    allergies: Mapped[list] = mapped_column(JSONType, default=list)
    profile: Mapped[dict] = mapped_column(JSONType)
    location: Mapped[str] = mapped_column(String(10))
    bed: Mapped[str] = mapped_column(String(10))
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pacu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discharged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[SimulationRun] = relationship(back_populates="patients")


class VitalSign(Base):
    """生命徵象時間序列（約每 5 秒模擬時間一筆）。"""
    __tablename__ = "vital_signs"
    __table_args__ = (Index("ix_vital_signs_patient_time", "patient_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String(10))
    bed: Mapped[str] = mapped_column(String(10))
    phase: Mapped[str] = mapped_column(String(12))
    hr: Mapped[float | None] = mapped_column(Float)
    sbp: Mapped[float | None] = mapped_column(Float)
    dbp: Mapped[float | None] = mapped_column(Float)
    map: Mapped[float | None] = mapped_column(Float)
    spo2: Mapped[float | None] = mapped_column(Float)
    etco2: Mapped[float | None] = mapped_column(Float)
    rr: Mapped[float | None] = mapped_column(Float)
    temp: Mapped[float | None] = mapped_column(Float)
    bis: Mapped[float | None] = mapped_column(Float)
    ppeak: Mapped[float | None] = mapped_column(Float)
    pain: Mapped[float | None] = mapped_column(Float)
    ebl_ml: Mapped[float | None] = mapped_column(Float)
    urine_ml: Mapped[float | None] = mapped_column(Float)
    fluids_ml: Mapped[float | None] = mapped_column(Float)
    case_min: Mapped[float | None] = mapped_column(Float)
    event_level: Mapped[float] = mapped_column(Float, default=0.0)  # 模擬器內部真實事件強度（標籤用，AI 看不到）


class LabResult(Base):
    __tablename__ = "lab_results"
    __table_args__ = (Index("ix_lab_results_patient_time", "patient_id", "drawn_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    drawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(40))
    ph: Mapped[float | None] = mapped_column(Float)
    paco2: Mapped[float | None] = mapped_column(Float)
    pao2: Mapped[float | None] = mapped_column(Float)
    hco3: Mapped[float | None] = mapped_column(Float)
    be: Mapped[float | None] = mapped_column(Float)
    hb: Mapped[float | None] = mapped_column(Float)
    k: Mapped[float | None] = mapped_column(Float)
    na: Mapped[float | None] = mapped_column(Float)
    glucose: Mapped[float | None] = mapped_column(Float)
    lactate: Mapped[float | None] = mapped_column(Float)
    ica: Mapped[float | None] = mapped_column(Float)


class ClinicalEvent(Base):
    """模擬器內部的真實臨床事件（資料集的「答案」）。"""
    __tablename__ = "clinical_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    event_uid: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(40))
    injected: Mapped[bool] = mapped_column(Boolean, default=False)
    peak: Mapped[float] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    treatments: Mapped[list] = mapped_column(JSONType, default=list)


class Intervention(Base):
    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    performed_by: Mapped[str] = mapped_column(String(40))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    affected: Mapped[list] = mapped_column(JSONType, default=list)


class PatientNote(Base):
    __tablename__ = "patient_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(40))
    noted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- AI Agent 紀錄
class RoundReport(Base):
    __tablename__ = "round_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id", ondelete="SET NULL"), index=True)
    trigger: Mapped[str] = mapped_column(String(20))
    scope: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sim_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    patients_checked: Mapped[int] = mapped_column(Integer)
    tools_run: Mapped[int] = mapped_column(Integer)
    n_critical: Mapped[int] = mapped_column(Integer)
    n_warning: Mapped[int] = mapped_column(Integer)
    n_info: Mapped[int] = mapped_column(Integer)
    new_alerts: Mapped[int] = mapped_column(Integer)
    resolved_alerts: Mapped[int] = mapped_column(Integer)
    resolved: Mapped[list] = mapped_column(JSONType, default=list)
    patients: Mapped[list] = mapped_column(JSONType, default=list)
    summary_md: Mapped[str] = mapped_column(Text, default="")
    summary_source: Mapped[str] = mapped_column(String(10), default="template")
    summary_status: Mapped[str] = mapped_column(String(10), default="done")
    summary_error: Mapped[str | None] = mapped_column(Text)
    summary_model: Mapped[str | None] = mapped_column(String(40))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id", ondelete="SET NULL"), index=True)
    key: Mapped[str] = mapped_column(String(200), index=True)
    pid: Mapped[str] = mapped_column(String(10))
    bed: Mapped[str] = mapped_column(String(10))
    tool_id: Mapped[str] = mapped_column(String(80))
    tool_name: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text, default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sim_first: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sim_last: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rounds_seen: Mapped[int] = mapped_column(Integer, default=1)
    missed: Mapped[int] = mapped_column(Integer, default=0)


class ActionProposal(Base):
    """AI 提出、等待使用者確認的處置建議。"""
    __tablename__ = "action_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id", ondelete="SET NULL"), index=True)
    pid: Mapped[str] = mapped_column(String(10))
    bed: Mapped[str] = mapped_column(String(10))
    intervention: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20))
    session_id: Mapped[str | None] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(12), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(Text)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSONType, default=list)
    mode: Mapped[str | None] = mapped_column(String(10))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


COUNTED_TABLES = [SimulationRun, Patient, VitalSign, LabResult, ClinicalEvent, Intervention, PatientNote,
                  RoundReport, Alert, ActionProposal, ChatMessage, Rule, Skill, MLModel, ToolConfig, AppSetting]
