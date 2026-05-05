"""
Command schema (DSL) definitions and helpers for TestFlowAI.

Provides strict validation using Pydantic and a small compatibility layer to
map the previous selector-based schema to the new intent-based DSL.

New DSL shape:
{
  "action": "navigate" | "click" | "type" | "press_key" | "verify",
  "target": string (required for all non-navigate actions),
  "value": optional string,
  "url": optional string,
  "key": optional string,
  "assertion": optional object
}

For verify:
{
  "assertion": {
    "type": "contains_text" | "equals_text" | "element_visible" | "element_count",
    "expected": string | number,
    "scope": optional string
  }
}

Note: We purposely do NOT implement selector resolution here. The executor will
still interpret `target` as a CSS selector when a selector-like value is given.
"""
from __future__ import annotations

from typing import Optional, Union, Literal
from pydantic import BaseModel, root_validator, validator


AssertionType = Literal[
    "contains_text",
    "equals_text",
    "element_visible",
    "element_count",
]


class Assertion(BaseModel):
    type: AssertionType
    expected: Optional[Union[str, int, float]] = None
    scope: Optional[str] = None

    @validator("expected", always=False)
    def _validate_expected_type(cls, v, values):  # type: ignore[override]
        t = values.get("type")
        if t in {"contains_text", "equals_text"}:
            if v is None or not isinstance(v, str):
                raise ValueError("expected must be a string for contains_text/equals_text assertions")
        elif t == "element_count":
            if v is None or not isinstance(v, (int,)):
                raise ValueError("expected must be an integer for element_count assertions")
            if v < 0:
                raise ValueError("expected must be >= 0 for element_count")
        else:  # element_visible
            # No specific expected required; ignore if present
            pass
        return v


ActionType = Literal["navigate", "click", "type", "press_key", "verify"]


class Command(BaseModel):
    action: ActionType
    target: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    key: Optional[str] = None
    assertion: Optional[Assertion] = None

    @root_validator
    def _check_constraints(cls, values):  # type: ignore[override]
        action: ActionType = values.get("action")
        target = values.get("target")
        url = values.get("url")
        value = values.get("value")
        key = values.get("key")
        assertion = values.get("assertion")

        if action == "navigate":
            if not url or not isinstance(url, str):
                raise ValueError("'url' is required for navigate action")
            return values

        # For non-navigate, target is generally required by the new DSL
        if action in {"click", "type", "verify"} and not target:
            raise ValueError("'target' is required for click/type/verify actions")

        if action == "type" and (not value or not isinstance(value, str)):
            raise ValueError("'value' is required for type action")

        if action == "press_key":
            if not target:
                raise ValueError("'target' is required for press_key action")
            if not key or not isinstance(key, str):
                raise ValueError("'key' is required for press_key action")

        if action == "verify":
            if assertion is None:
                raise ValueError("'assertion' is required for verify action")

        return values


def normalize_legacy(d: dict) -> dict:
    """
    Backward-compatibility adapter:
    - selector -> target
    - verify text -> assertion { type: contains_text, expected: text }
    - Provide default 'target' for press_key if absent ("active_element")
    """
    if not isinstance(d, dict):
        return d

    out = dict(d)

    # Map old fields
    if "selector" in out and "target" not in out:
        out["target"] = out.get("selector")

    if out.get("action") == "verify":
        if "assertion" not in out or not out.get("assertion"):
            text = out.get("text")
            if isinstance(text, str):
                out["assertion"] = {
                    "type": "contains_text",
                    "expected": text,
                }
        # Clean legacy key if present
        out.pop("text", None)
        # Provide a default target for page-wide verification to satisfy new DSL
        if not out.get("target"):
            out["target"] = "page"

    # For press_key, ensure some target exists for DSL conformance
    if out.get("action") == "press_key" and not out.get("target"):
        out["target"] = "active_element"

    return out
