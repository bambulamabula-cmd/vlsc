from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings, apply_runtime_settings_overrides, settings, settings_defaults
from app.models import AppSetting


class SettingsStoreError(ValueError):
    pass


def _serialize_value(value: object) -> str:
    return json.dumps(value)


def _deserialize_value(raw: str) -> object:
    return json.loads(raw)


def apply_persisted_settings(db: Session) -> None:
    rows = db.query(AppSetting).all()
    overrides: dict[str, object] = {}
    for row in rows:
        if row.key in Settings.model_fields:
            overrides[row.key] = _deserialize_value(row.value)
    if overrides:
        try:
            validated = Settings(**{**settings_defaults(), **overrides})
        except ValidationError as exc:  # pragma: no cover
            raise SettingsStoreError(str(exc)) from exc
        apply_runtime_settings_overrides(validated.model_dump())


def upsert_settings(db: Session, updates: Mapping[str, object]) -> dict[str, object]:
    current_data = {
        name: getattr(settings, name)
        for name in Settings.model_fields
    }
    merged = {**current_data, **updates}

    try:
        validated = Settings(**merged)
    except ValidationError as exc:
        raise SettingsStoreError(str(exc)) from exc

    validated_data = validated.model_dump()
    apply_runtime_settings_overrides(validated_data)

    for key, value in validated_data.items():
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        serialized = _serialize_value(value)
        if row is None:
            db.add(AppSetting(key=key, value=serialized))
        else:
            row.value = serialized
    db.commit()

    return validated_data


def settings_view_model() -> list[dict[str, Any]]:
    defaults = settings_defaults()
    fields = []
    for name in Settings.model_fields:
        value = getattr(settings, name)
        default_value = defaults.get(name)
        fields.append(
            {
                "name": name,
                "value": value,
                "default": default_value,
                "type": type(default_value).__name__,
                "requires_restart": name == "sqlite_path",
            }
        )
    return fields
