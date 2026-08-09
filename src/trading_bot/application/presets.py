from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping

from trading_bot.application.constants import DEFAULT_REPORTS_DIR, PRESETS_FILENAME, RUN_MODE_OPTIONS, STRATEGY_OPTIONS
from trading_bot.application.requests import BacktestRequest, sweep_parameter_names
from trading_bot.errors import FormValidationError
from trading_bot.strategies import STRATEGY_SPECS

PRESET_NAME_PATTERN = re.compile(r"[^a-z0-9]+")


def preset_storage_path(output_dir: str | Path = DEFAULT_REPORTS_DIR) -> Path:
    return Path(output_dir) / PRESETS_FILENAME


def list_strategy_presets(output_dir: str | Path = DEFAULT_REPORTS_DIR) -> list[dict[str, object]]:
    path = preset_storage_path(output_dir)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        presets = json.load(handle)
    return sorted(presets, key=lambda item: str(item.get("saved_at", "")), reverse=True)


def save_strategy_preset(raw: Mapping[str, object], output_dir: str | Path = DEFAULT_REPORTS_DIR) -> dict[str, object]:
    preset_name = str(raw.get("preset_name", "")).strip()
    if not preset_name:
        raise FormValidationError(
            "Dammi un nome per salvare il preset strategia.",
            fields=("preset_name",),
        )

    request = BacktestRequest.from_mapping(raw)
    run_mode = str(raw.get("run_mode", "single")).strip().lower()
    if run_mode not in RUN_MODE_OPTIONS:
        run_mode = "single"
    if run_mode == "sweep" and (request.is_composite or not STRATEGY_OPTIONS[request.strategy]["supports_sweep"]):
        run_mode = "single"

    preset = {
        "id": _preset_slug(preset_name),
        "name": preset_name,
        "strategy": request.strategy,
        "strategy_label": request.strategy_label,
        "active_strategy_ids": list(request.active_strategy_ids),
        "rule_logic": request.rule_logic,
        "is_composite": request.is_composite,
        "active_rules": [rule.metadata() for rule in request.active_rules()],
        "interval": request.interval,
        "initial_capital": request.initial_capital,
        "fee_bps": request.fee_bps,
        "run_mode": run_mode,
        "parameters": request.strategy_parameters(),
        "parameters_by_strategy": {
            rule.strategy_id: dict(rule.parameters)
            for rule in request.active_rules()
        },
        "sweep_settings": _sweep_settings_from_form(raw=raw, strategy_id=request.strategy),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }

    existing = list_strategy_presets(output_dir)
    updated = [item for item in existing if str(item.get("id")) != preset["id"]]
    updated.insert(0, preset)

    path = preset_storage_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(updated, handle, indent=2)
    return preset


def _sweep_settings_from_form(*, raw: Mapping[str, object], strategy_id: str) -> dict[str, object]:
    """Estrae dal form i campi range sweep della strategia selezionata.

    I campi seguono la convenzione ``<strategia>__<parametro>_start/_end/_step``
    (stessa dei template e di ``_parse_parameter_ranges``), con fallback sulla
    forma globale ``<parametro>_start`` per i form pre-namespacing. Vengono
    salvati solo i campi presenti e non vuoti: al ripristino quelli mancanti
    restano sui default del form.
    """
    settings: dict[str, object] = {"sort_by": str(raw.get("sort_by", "total_return_pct"))}
    spec = STRATEGY_SPECS[strategy_id]
    if not spec.supports_sweep:
        return settings

    parameter_map = spec.parameter_map()
    for name in sweep_parameter_names(strategy_id):
        value_type = parameter_map[name].value_type
        for suffisso in ("start", "end", "step"):
            key = f"{strategy_id}__{name}_{suffisso}"
            text = str(raw.get(key, "") or "").strip()
            if not text:
                text = str(raw.get(f"{name}_{suffisso}", "") or "").strip()
            if not text:
                continue
            try:
                value = float(text)
            except ValueError:
                continue
            settings[key] = int(value) if value_type == "int" else value
    return settings


def _preset_slug(name: str) -> str:
    normalized = PRESET_NAME_PATTERN.sub("-", name.lower()).strip("-")
    return normalized or "strategy-preset"
