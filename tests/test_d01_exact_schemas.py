"""Deterministic, dependency-free contract checks for the D01 schemas."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCHEMAS = ROOT / "schemas"


def load(name: str) -> dict:
    with (SCHEMAS / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def assert_object_boundary(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def validate_common(instance: dict, schema: dict) -> bool:
    """Small validator for the keywords used by these two persisted contracts."""
    if not isinstance(instance, dict) or set(instance) - set(schema["properties"]):
        return False
    if any(field not in instance for field in schema["required"]):
        return False
    for field, rule in schema["properties"].items():
        if field not in instance:
            continue
        value = instance[field]
        if "enum" in rule and value not in rule["enum"]:
            return False
        if "pattern" in rule and (not isinstance(value, str) or not re.fullmatch(rule["pattern"], value)):
            return False
        if rule.get("type") == "string" and (not isinstance(value, str) or len(value) < rule.get("minLength", 0)):
            return False
        if rule.get("type") == "array" and (not isinstance(value, list) or len(value) < rule.get("minItems", 0)):
            return False
        if "anyOf" in rule:
            valid_any = False
            for sub in rule["anyOf"]:
                if sub.get("type") == "null" and value is None:
                    valid_any = True
                elif sub.get("type") == "string" and isinstance(value, str) and len(value) >= sub.get("minLength", 0):
                    valid_any = True
                elif sub.get("type") == "object" and isinstance(value, dict):
                    props = sub.get("properties", {})
                    valid_any = sub.get("additionalProperties", True) is False and set(value) == set(sub.get("required", [])) and all(isinstance(value[key], str) and len(value[key]) >= props[key].get("minLength", 0) for key in value)
            if not valid_any:
                return False
    return True


def test_schema_files_are_valid_json_and_draft_2020_12() -> None:
    for name in ("p08_structure_draft.schema.json", "p08_gate_result.schema.json"):
        assert_object_boundary(load(name))


def test_p08_contract_shape_and_negative_controls() -> None:
    schema = load("p08_structure_draft.schema.json")
    assert schema["properties"]["decision"]["enum"] == ["KEEP", "SPLIT"]
    assert schema["required"] == [
        "parent_id", "decision", "draft_markdown", "source_coverage_summary",
        "unit_boundaries", "history_boundary_blocker",
    ]
    valid = {
        "parent_id": "V01_CH003", "decision": "SPLIT", "draft_markdown": "draft",
        "source_coverage_summary": "complete", "unit_boundaries": [{
            "unit_id": "V01_CH003_S01", "source_start_anchor": "start", "source_end_anchor": "end",
        }], "history_boundary_blocker": None,
    }
    assert validate_common(valid, schema)
    assert not validate_common({**valid, "decision": "MERGE"}, schema)
    assert not validate_common({**valid, "unknown": 1}, schema)


def test_p08b_verdicts_sha_and_conditional_contract() -> None:
    schema = load("p08_gate_result.schema.json")
    assert schema["properties"]["verdict"]["enum"] == ["PASS", "REVISE", "HISTORY_BOUNDARY_BLOCKER"]
    sha = "a" * 64
    assert re.fullmatch(r"[0-9a-f]{64}", sha)
    assert not re.fullmatch(r"[0-9a-f]{64}", "A" * 64)
    assert not re.fullmatch(r"[0-9a-f]{64}", "a" * 63)
    assert not re.fullmatch(r"[0-9a-f]{64}", "g" * 64)
    branches = schema["oneOf"]
    assert branches[0]["properties"]["revision_targets"]["maxItems"] == 0
    assert branches[1]["properties"]["revision_targets"]["minItems"] == 1
    assert branches[1]["properties"]["return_action"]["const"].startswith("P08")
    assert branches[2]["properties"]["blocker_details"]["required"] == ["missing_input", "reason", "required_return_interface"]
    base = {
        "reviewed_sha256": sha,
        "summary": "reviewed",
        "revision_targets": [],
        "blocker_details": None,
        "return_action": "P08B_GATE_RESULT",
    }
    assert validate_gate_payload({**base, "verdict": "PASS"})
    assert not validate_gate_payload({**base, "verdict": "PASS", "revision_targets": ["boundary"]})
    assert not validate_gate_payload({**base, "verdict": "PASS", "blocker_details": {"missing_input": "x", "reason": "y", "required_return_interface": "z"}})
    assert validate_gate_payload({
        **base,
        "verdict": "REVISE",
        "revision_targets": ["unit boundary"],
        "return_action": "P08 / ACTION_ID = P08_MAP_CURRENT_PARENT",
    })
    assert not validate_gate_payload({
        **base,
        "verdict": "REVISE",
        "return_action": "P08 / ACTION_ID = P08_MAP_CURRENT_PARENT",
    })
    assert not validate_gate_payload({
        **base,
        "verdict": "REVISE",
        "revision_targets": ["unit boundary"],
        "return_action": "P08A",
    })
    assert validate_gate_payload({
        **base,
        "verdict": "HISTORY_BOUNDARY_BLOCKER",
        "blocker_details": {"missing_input": "ledger boundary", "reason": "historical boundary is unresolved", "required_return_interface": "controller.review"},
        "return_action": "STOP / REQUIRED_RETURN_INTERFACE",
    })
    assert not validate_gate_payload({**base, "verdict": "HISTORY_BOUNDARY_BLOCKER"})
    blocker = {"missing_input": "ledger boundary", "reason": "unresolved", "required_return_interface": "controller.review"}
    for key in blocker:
        assert not validate_gate_payload({**base, "verdict": "HISTORY_BOUNDARY_BLOCKER", "blocker_details": {k: v for k, v in blocker.items() if k != key}, "return_action": "STOP / REQUIRED_RETURN_INTERFACE"})
    assert not validate_gate_payload({**base, "verdict": "HISTORY_BOUNDARY_BLOCKER", "blocker_details": {**blocker, "extra": "nope"}, "return_action": "STOP / REQUIRED_RETURN_INTERFACE"})
    assert not validate_gate_payload({**base, "verdict": "HISTORY_BOUNDARY_BLOCKER", "blocker_details": blocker, "return_action": "PUBLISH"})
    for forbidden in ("maf", "openai", "deepseek", "provider"):
        assert forbidden not in json.dumps(schema).lower()


def validate_gate_payload(payload: dict) -> bool:
    """Validate D01's verdict-specific constraints without adding a validator dependency."""
    schema = load("p08_gate_result.schema.json")
    if not validate_common(payload, schema):
        return False
    verdict = payload["verdict"]
    if verdict == "PASS":
        return not payload["revision_targets"] and payload["blocker_details"] in (None, "")
    if verdict == "REVISE":
        return (
            bool(payload["revision_targets"])
            and payload["blocker_details"] in (None, "")
            and payload["return_action"] == "P08 / ACTION_ID = P08_MAP_CURRENT_PARENT"
        )
    if verdict == "HISTORY_BOUNDARY_BLOCKER":
        details = payload["blocker_details"]
        return isinstance(details, dict) and set(details) == {"missing_input", "reason", "required_return_interface"} and all(isinstance(value, str) and value for value in details.values()) and payload["return_action"] == "STOP / REQUIRED_RETURN_INTERFACE"
    return False
