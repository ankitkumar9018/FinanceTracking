"""Pydantic schemas for alert endpoints."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# One source of truth for valid values: a typo'd channel previously passed
# create/update untouched and the alert then silently never notified.
Channel = Literal["in_app", "email", "telegram", "whatsapp", "sms"]
AlertType = Literal["PRICE_RANGE", "RSI", "CUSTOM"]

# The zones ``alert_service.determine_action_needed`` can return. A CUSTOM
# alert waiting on any other string can never fire.
ActionZone = Literal[
    "N", "Y_LOWER_MID", "Y_UPPER_MID", "Y_DARK_RED", "Y_DARK_GREEN"
]
_ACTION_ZONES: tuple[str, ...] = (
    "N",
    "Y_LOWER_MID",
    "Y_UPPER_MID",
    "Y_DARK_RED",
    "Y_DARK_GREEN",
)

# Condition keys carrying a numeric threshold, grouped by the alert type that
# reads them. ``alert_service`` no longer *crashes* on a non-numeric threshold
# (it warns and ignores the key), but an ignored key leaves an alert that can
# never fire and gives the user no clue why — so the bad value is rejected at
# the API boundary instead of being stored.
PRICE_KEYS: tuple[str, ...] = ("above", "below")
RSI_KEYS: tuple[str, ...] = ("rsi_above", "rsi_below")
NUMERIC_CONDITION_KEYS: tuple[str, ...] = PRICE_KEYS + RSI_KEYS


def _default_channels() -> list[Channel]:
    return ["in_app"]


def _coerce_threshold(key: str, value: Any) -> float | int:
    """Validate one threshold, returning the value to store.

    Ints and floats are kept as-is so a condition round-trips unchanged;
    numeric strings (``{"above": "1400"}``) are normalised to float so the
    stored JSON is always comparable. Everything else raises.
    """
    # bool is a subclass of int, and ``float(True)`` is a perfectly valid 1.0 —
    # which would be stored as a threshold nobody meant.
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(
            f"condition['{key}'] must be a number, got {type(value).__name__}"
        )

    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            raise ValueError(
                f"condition['{key}'] must be a number, got {value!r}"
            ) from None
        stored: float | int = number
    else:
        number = float(value)
        stored = value

    # NaN compares false against everything, so a NaN threshold is an alert
    # that silently never fires; inf is the same in one direction.
    if not math.isfinite(number):
        raise ValueError(f"condition['{key}'] must be a finite number")

    if key in RSI_KEYS:
        if not 0 <= number <= 100:
            raise ValueError(
                f"condition['{key}'] must be between 0 and 100 (RSI range)"
            )
    elif number <= 0:
        raise ValueError(f"condition['{key}'] must be a positive price")

    return stored


def _require_actionable(condition: dict, alert_type: str | None) -> None:
    """Reject a condition that no evaluation path can ever satisfy.

    ``alert_type`` is None on a partial update that leaves the type alone; the
    check then only insists on *some* recognised key, since which ones apply
    isn't knowable from the request body.
    """
    if alert_type == "CUSTOM":
        zone = condition.get("action_needed")
        if zone not in _ACTION_ZONES:
            raise ValueError(
                "a CUSTOM alert needs condition['action_needed'] set to one of "
                + ", ".join(_ACTION_ZONES)
            )
        return

    if alert_type == "PRICE_RANGE":
        wanted, label = PRICE_KEYS, "condition['above'] or condition['below']"
    elif alert_type == "RSI":
        wanted, label = (
            RSI_KEYS,
            "condition['rsi_above'] or condition['rsi_below']",
        )
    else:
        wanted = (*NUMERIC_CONDITION_KEYS, "action_needed")
        label = "a recognised condition key (" + ", ".join(wanted) + ")"

    if not any(condition.get(key) is not None for key in wanted):
        raise ValueError(f"this alert needs {label} — it could never fire")


def validate_condition(condition: dict, alert_type: str | None) -> dict:
    """Return the condition to store, or raise if it can never fire correctly."""
    cleaned = dict(condition)
    for key in NUMERIC_CONDITION_KEYS:
        if key in cleaned and cleaned[key] is not None:
            cleaned[key] = _coerce_threshold(key, cleaned[key])
    _require_actionable(cleaned, alert_type)
    return cleaned


def apply_once(condition: dict, once: bool | None) -> dict:
    """Fold the typed ``once`` flag into the stored condition dict.

    ``alert_service`` reads one-shot from the condition JSON (``once`` or the
    older ``one_shot``). When the typed field is supplied it is authoritative,
    so the legacy key is dropped rather than left to contradict it.
    """
    if once is None:
        return condition
    condition = dict(condition)
    condition.pop("one_shot", None)
    condition["once"] = once
    return condition


# One-shot is worth a typed field rather than a documented JSON key: it is the
# only way the flag shows up in the OpenAPI schema (so a UI can offer it), and
# a client that hand-writes a near-miss key such as ``"one-shot"`` gets a
# repeating alert with no error.
_ONCE_DESCRIPTION = (
    "Fire at most once, then deactivate the alert. Stored as "
    "condition['once']; omit to leave an existing setting alone."
)


class AlertCreate(BaseModel):
    holding_id: int | None = None
    watchlist_item_id: int | None = None
    alert_type: AlertType = "PRICE_RANGE"
    condition: dict = Field(
        ...,
        description="Alert condition, e.g. {'above': 150.0} or {'rsi_above': 70}",
    )
    is_active: bool = True
    channels: list[Channel] = Field(default_factory=_default_channels)
    once: bool | None = Field(default=None, description=_ONCE_DESCRIPTION)

    @model_validator(mode="after")
    def _check_condition(self) -> AlertCreate:
        self.condition = validate_condition(
            apply_once(self.condition, self.once), self.alert_type
        )
        return self


class AlertUpdate(BaseModel):
    alert_type: AlertType | None = None
    condition: dict | None = None
    is_active: bool | None = None
    once: bool | None = Field(default=None, description=_ONCE_DESCRIPTION)

    @model_validator(mode="after")
    def _check_condition(self) -> AlertUpdate:
        # ``once`` alone is merged into the *stored* condition by the endpoint,
        # which is the only place the existing dict is available.
        if self.condition is not None:
            self.condition = validate_condition(self.condition, self.alert_type)
        return self


class AlertChannelUpdate(BaseModel):
    channels: list[Channel] = Field(
        ...,
        description="List of notification channels: in_app, email, telegram, whatsapp, sms",
    )


class AlertResponse(BaseModel):
    id: int
    user_id: int
    holding_id: int | None
    watchlist_item_id: int | None
    alert_type: str
    condition: dict
    is_active: bool
    last_triggered: datetime | None
    channels: list
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertHistoryEntry(BaseModel):
    alert_id: int
    alert_type: str
    condition: dict
    triggered_at: datetime
    stock_symbol: str | None
    message: str
