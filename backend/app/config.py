"""系統設定：路徑、環境變數、預設值，以及存放在資料庫（app_settings、tool_configs）的使用者設定。"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path

# 專案結構：<專案>/backend（本程式、seeds、plugins）與 <專案>/frontend（Vue 網頁介面）
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
SEEDS_DIR = BASE_DIR / "seeds"
CACHE_DIR = Path(os.environ.get("ANES_CACHE_DIR", BASE_DIR / "cache"))
PLUGINS_DIR = BASE_DIR / "plugins"
FRONTEND_DIST = Path(os.environ.get("ANES_FRONTEND_DIR", PROJECT_DIR / "frontend" / "dist"))
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://anes:anes@127.0.0.1:55432/anes")

MODEL_CHOICES = [
    {"id": "claude-opus-5", "label": "Claude Opus 5（預設・判斷最完整）"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5（較快・費用較低）"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5（最快・費用最低）"},
]

DEFAULT_SETTINGS: dict = {
    "llm": {
        "api_key": "",
        "model": "claude-opus-5",
        "effort": "medium",
    },
    "rounds": {
        "enabled": True,
        # interval：每隔固定分鐘；schedule：每天固定時間點
        "mode": "interval",
        "interval_minutes": 2.0,
        "times": ["08:00", "12:00", "16:00", "20:00"],
        "window_enabled": False,
        "window_start": "07:00",
        "window_end": "22:00",
        # all / OR / PACU
        "scope": "all",
        # off / when_findings / always
        "ai_summary": "when_findings",
        # 有危急病人時，額外每 N 分鐘複查這些病人；0 = 關閉
        "critical_recheck_minutes": 1.0,
    },
    "simulation": {
        "speed": 5,
        "event_rate": 1.0,
        "running": True,
    },
}

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class SettingsError(ValueError):
    pass


def _clamp_number(value, lo, hi, name):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"「{name}」必須是數字") from None
    if not lo <= v <= hi:
        raise SettingsError(f"「{name}」必須介於 {lo} 到 {hi} 之間")
    return v


def _normalize_time(value: str, name: str) -> str:
    m = _TIME_RE.match(str(value).strip())
    if not m:
        raise SettingsError(f"「{name}」時間格式需為 HH:MM，例如 08:30")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _validate(section: str, values: dict) -> dict:
    if section not in DEFAULT_SETTINGS:
        raise SettingsError(f"未知的設定區塊：{section}")
    out = {k: v for k, v in values.items() if k in DEFAULT_SETTINGS[section]}
    if section == "rounds":
        if "mode" in out and out["mode"] not in ("interval", "schedule"):
            raise SettingsError("查房模式只能是「固定間隔」或「固定時間點」")
        if "interval_minutes" in out:
            out["interval_minutes"] = _clamp_number(out["interval_minutes"], 0.5, 720, "查房間隔（分鐘）")
        if "times" in out:
            out["times"] = sorted({_normalize_time(t, "查房時間點") for t in out["times"]})
        for key in ("window_start", "window_end"):
            if key in out:
                out[key] = _normalize_time(out[key], "查房時段")
        if "scope" in out and out["scope"] not in ("all", "OR", "PACU"):
            raise SettingsError("查房範圍只能是 all / OR / PACU")
        if "ai_summary" in out and out["ai_summary"] not in ("off", "when_findings", "always"):
            raise SettingsError("AI 摘要設定只能是 off / when_findings / always")
        if "critical_recheck_minutes" in out:
            out["critical_recheck_minutes"] = _clamp_number(out["critical_recheck_minutes"], 0, 60, "危急病人複查間隔")
        for key in ("enabled", "window_enabled"):
            if key in out:
                out[key] = bool(out[key])
    elif section == "simulation":
        if "speed" in out:
            out["speed"] = _clamp_number(out["speed"], 1, 60, "模擬速度")
        if "event_rate" in out:
            out["event_rate"] = _clamp_number(out["event_rate"], 0, 5, "事件發生頻率")
        if "running" in out:
            out["running"] = bool(out["running"])
    elif section == "llm":
        if "model" in out and out["model"] not in {m["id"] for m in MODEL_CHOICES}:
            raise SettingsError("不支援的 AI 模型")
        if "effort" in out and out["effort"] not in ("low", "medium", "high"):
            raise SettingsError("思考深度只能是 low / medium / high")
        if "api_key" in out:
            out["api_key"] = str(out["api_key"]).strip()
    return out


class Settings:
    """設定快取在記憶體（查房、模擬每秒都會讀取），修改時同步寫入資料庫。

    sessionmaker 為 None 時只存在記憶體（離線訓練等不需要資料庫的情境）。
    """

    def __init__(self, sessionmaker=None):
        self.sm = sessionmaker
        self.data = copy.deepcopy(DEFAULT_SETTINGS)
        self.tools: dict[str, dict] = {}

    async def load(self) -> None:
        if self.sm is None:
            return
        from .repositories.knowledge import load_settings

        sections, tools = await load_settings(self.sm)
        for section, values in sections.items():
            if section in self.data:
                self.data[section].update({k: v for k, v in values.items() if k in DEFAULT_SETTINGS[section]})
        self.tools = tools

    def section(self, name: str) -> dict:
        return copy.deepcopy(self.data[name])

    async def update(self, section: str, values: dict) -> dict:
        clean = _validate(section, values)
        merged = {**self.data[section], **clean}
        if self.sm is not None:
            from .repositories.knowledge import save_setting_section

            await save_setting_section(self.sm, section, merged)
        self.data[section] = merged
        return copy.deepcopy(merged)

    # ---- tools ----
    def tool_enabled(self, tool_id: str) -> bool:
        return self.tools.get(tool_id, {}).get("enabled", True)

    def tool_params(self, tool_id: str) -> dict:
        return dict(self.tools.get(tool_id, {}).get("params", {}))

    async def set_tool(self, tool_id: str, enabled: bool | None = None, params: dict | None = None) -> None:
        current = self.tools.get(tool_id, {"enabled": True, "params": {}})
        new = {
            "enabled": current["enabled"] if enabled is None else bool(enabled),
            "params": current["params"] if params is None else dict(params),
        }
        if self.sm is not None:
            from .repositories.knowledge import save_tool_config

            await save_tool_config(self.sm, tool_id, new["enabled"], new["params"])
        self.tools[tool_id] = new

    async def forget_tool(self, tool_id: str) -> None:
        if self.sm is not None:
            from .repositories.knowledge import delete_tool_config

            await delete_tool_config(self.sm, tool_id)
        self.tools.pop(tool_id, None)

    # ---- llm ----
    def api_key(self) -> tuple[str, str | None]:
        key = self.data["llm"].get("api_key") or ""
        if key:
            return key, "settings"
        env = os.environ.get("ANTHROPIC_API_KEY", "")
        if env:
            return env, "env"
        return "", None

    def public(self) -> dict:
        data = copy.deepcopy(self.data)
        key, source = self.api_key()
        data["llm"].pop("api_key", None)
        data["llm"]["api_key_set"] = bool(key)
        data["llm"]["api_key_source"] = source
        data["llm"]["api_key_hint"] = f"{key[:7]}…{key[-4:]}" if len(key) > 12 else ""
        data["llm"]["model_choices"] = MODEL_CHOICES
        return data
