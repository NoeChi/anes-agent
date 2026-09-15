"""工具（Tool）的共同介面。

所有工具（規則、臨床評分、機器學習、深度學習、使用者自訂規則、上傳模型、Python 外掛）都實作
`BaseTool.run(ctx, params)`，回傳 ToolResult。Agent 查房時會對每位病人執行所有啟用中的工具。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
SEVERITY_LABEL = {"info": "提示", "warning": "警示", "critical": "危急"}

CATEGORY_LABEL = {
    "rule": "規則式",
    "score": "臨床評分",
    "ml": "機器學習",
    "dl": "深度學習",
    "custom_rule": "自訂規則",
    "custom_model": "自訂 AI 模型",
    "plugin": "Python 外掛",
}


@dataclass
class Finding:
    severity: str  # info / warning / critical
    title: str
    detail: str
    suggestion: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    tool_id: str = ""
    tool_name: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity_label"] = SEVERITY_LABEL[self.severity]
        return d


@dataclass
class ToolResult:
    tool_id: str
    tool_name: str
    patient_id: str
    ok: bool = True
    applicable: bool = True
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "patient_id": self.patient_id,
            "ok": self.ok,
            "applicable": self.applicable,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "values": self.values,
            "error": self.error,
        }


@dataclass
class ParamSpec:
    key: str
    label: str
    default: Any
    type: str = "number"  # number / text / bool
    unit: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class BaseTool:
    id: str = ""
    name: str = ""
    category: str = "rule"
    description: str = ""
    how_it_works: str = ""
    locations: tuple[str, ...] = ("OR", "PACU")
    params: list[ParamSpec] = []
    builtin: bool = True

    def applicable(self, ctx) -> tuple[bool, str]:
        if ctx.location not in self.locations:
            where = "、".join("手術室" if l == "OR" else "恢復室" for l in self.locations)
            return False, f"此工具只用於{where}"
        return True, ""

    def run(self, ctx, params: dict) -> ToolResult:  # pragma: no cover - interface
        raise NotImplementedError

    # 小工具
    def result(self, ctx, summary: str = "", findings: list[Finding] | None = None, values: dict | None = None) -> ToolResult:
        findings = findings or []
        for f in findings:
            f.tool_id = self.id
            f.tool_name = self.name
        return ToolResult(self.id, self.name, ctx.pid, summary=summary, findings=findings, values=values or {})

    def describe(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "category_label": CATEGORY_LABEL.get(self.category, self.category),
            "description": self.description,
            "how_it_works": self.how_it_works,
            "locations": list(self.locations),
            "params": [p.to_dict() for p in self.params],
            "builtin": self.builtin,
        }
