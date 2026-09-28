from __future__ import annotations

import re

from .security import redact_text


_REF = re.compile(r"[A-Z]{1,4}[1-9][0-9]{0,2}\Z")
_NET = re.compile(r"[A-Z0-9_+.-]{1,32}\Z")
_FOOTPRINTS = frozenset({"header_1x02", "header_1x04", "header_1x08", "to220_3", "do41"})


def _inventory_line(item: dict) -> dict | None:
    sku = item.get("sku")
    name = item.get("name") or item.get("title") or sku
    quantity = item.get("quantity", item.get("qty", 0))
    if (not isinstance(sku, str) or not sku or len(sku) > 80
            or not isinstance(name, str) or not name or len(name) > 160
            or not isinstance(quantity, (int, float)) or isinstance(quantity, bool)
            or quantity < 0):
        return None
    return {"sku": sku, "name": name, "quantity": quantity}


def dog_feeder_plan(prompt: str, inventory: dict) -> dict:
    """Return a bounded, conservative editable prototype—not a production design."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2_000:
        raise ValueError("project prompt must contain 1-2000 characters")
    if redact_text(prompt) != prompt:
        raise ValueError("project prompt contains secret-shaped data")
    normalized = prompt.casefold()
    if "dog" not in normalized or not any(word in normalized for word in ("feeder", "feed", "dispens")):
        raise ValueError("The guided PCB workflow currently supports the AI dog-feeder prototype.")
    available = [line for item in inventory.get("items", [])
                 if isinstance(item, dict) and (line := _inventory_line(item))]
    jst = next((item for item in available if "JST-XH-2" in item["sku"].upper()), None)
    inventory_use = []
    if jst:
        inventory_use.append({"sku": jst["sku"], "name": jst["name"],
                              "available": jst["quantity"], "quantity": 4})
    missing = [
        {"part": "12 V regulated DC supply, 5 A minimum", "quantity": 1, "reason": "motor and logic power"},
        {"part": "5 V buck converter module, 3 A", "quantity": 1, "reason": "logic rail"},
        {"part": "ESP32-S3 development module", "quantity": 1, "reason": "controller and local AI interface"},
        {"part": "HX711 module plus load cell", "quantity": 1, "reason": "portion feedback"},
        {"part": "12 V geared DC motor", "quantity": 1, "reason": "auger drive"},
        {"part": "logic-level N-channel MOSFET, TO-220", "quantity": 1, "reason": "motor switching"},
        {"part": "1N5819 or suitable flyback diode", "quantity": 1, "reason": "motor transient clamp"},
        {"part": "3.3 V presence sensor module", "quantity": 1, "reason": "dog/pan detection"},
        {"part": "fuse and reverse-polarity protection", "quantity": 1, "reason": "input protection"},
        {"part": "bulk and local decoupling capacitors", "quantity": 1, "reason": "rail stability"},
    ]
    if not jst:
        missing.append({"part": "2-pin locking connectors", "quantity": 4, "reason": "power, motor, and load interfaces"})
    components = [
        {"ref": "J1", "value": "12V_IN", "footprint": "header_1x02", "x": 18, "y": 20,
         "pins": {"1": "VIN", "2": "GND"}},
        {"ref": "J2", "value": "MOTOR", "footprint": "header_1x02", "x": 82, "y": 20,
         "pins": {"1": "MOTOR+", "2": "VIN"}},
        {"ref": "Q1", "value": "NMOS_LOGIC", "footprint": "to220_3", "x": 67, "y": 24,
         "pins": {"1": "MOTOR_GATE", "2": "MOTOR+", "3": "GND"}},
        {"ref": "D1", "value": "FLYBACK", "footprint": "do41", "x": 76, "y": 30,
         "pins": {"1": "VIN", "2": "MOTOR+"}},
        {"ref": "J3", "value": "BUCK_5V", "footprint": "header_1x04", "x": 30, "y": 30,
         "pins": {"1": "VIN", "2": "GND", "3": "+5V", "4": "GND"}},
        {"ref": "J4", "value": "ESP32_S3_MODULE", "footprint": "header_1x08", "x": 47, "y": 48,
         "pins": {"1": "+5V", "2": "GND", "3": "I2C_SDA", "4": "I2C_SCL", "5": "MOTOR_GATE", "6": "PRESENCE", "7": "FEED_BUTTON", "8": "STATUS_LED"}},
        {"ref": "J5", "value": "HX711_LOAD_CELL", "footprint": "header_1x04", "x": 25, "y": 62,
         "pins": {"1": "+5V", "2": "GND", "3": "I2C_SDA", "4": "I2C_SCL"}},
        {"ref": "J6", "value": "PRESENCE_SENSOR", "footprint": "header_1x04", "x": 68, "y": 62,
         "pins": {"1": "+5V", "2": "GND", "3": "PRESENCE", "4": "NC"}},
        {"ref": "J7", "value": "UI_BUTTON_LED", "footprint": "header_1x04", "x": 86, "y": 48,
         "pins": {"1": "FEED_BUTTON", "2": "STATUS_LED", "3": "+5V", "4": "GND"}},
    ]
    plan = {
        "schema": 1,
        "project_name": "AI Dog Feeder",
        "summary": "Editable low-voltage controller draft for measured, sensor-gated dog-food dispensing.",
        "board": {"width_mm": 100, "height_mm": 75, "route_nets": ["VIN", "GND", "MOTOR+"]},
        "inventory_use": inventory_use,
        "missing_parts": missing,
        "components": components,
        "assumptions": [
            "Low-voltage 12 VDC prototype only; no mains voltage is present on this PCB.",
            "Module headers are placeholders until exact purchased modules and verified pinouts are selected.",
            "The 100 x 75 mm board outline and mounting arrangement must be checked against the enclosure.",
            "Motor current, MOSFET thermal margin, fuse value, trace width, and flyback diode rating require measured load data.",
            "The draft is intentionally paused for human schematic and layout review before fabrication.",
        ],
    }
    validate_project_plan(plan, {item["sku"] for item in available})
    return plan


def validate_project_plan(plan: dict, inventory_skus: set[str] | None = None) -> dict:
    if not isinstance(plan, dict) or set(plan) != {"schema", "project_name", "summary", "board", "inventory_use", "missing_parts", "components", "assumptions"}:
        raise ValueError("project plan has an invalid schema")
    if plan["schema"] != 1 or not isinstance(plan["project_name"], str) or not 1 <= len(plan["project_name"]) <= 80:
        raise ValueError("project identity is invalid")
    if not isinstance(plan["summary"], str) or not 1 <= len(plan["summary"]) <= 500:
        raise ValueError("project summary is invalid")
    board = plan["board"]
    if (not isinstance(board, dict) or set(board) != {"width_mm", "height_mm", "route_nets"}
            or not all(isinstance(board[key], (int, float)) and not isinstance(board[key], bool) and 30 <= board[key] <= 300 for key in ("width_mm", "height_mm"))
            or not isinstance(board["route_nets"], list) or len(board["route_nets"]) > 8
            or not all(isinstance(net, str) and _NET.fullmatch(net) for net in board["route_nets"])):
        raise ValueError("board definition is invalid")
    if not isinstance(plan["components"], list) or not 1 <= len(plan["components"]) <= 64:
        raise ValueError("component list is invalid")
    refs = set()
    for component in plan["components"]:
        if not isinstance(component, dict) or set(component) != {"ref", "value", "footprint", "x", "y", "pins"}:
            raise ValueError("component definition is invalid")
        ref = component["ref"]
        if not isinstance(ref, str) or not _REF.fullmatch(ref) or ref in refs:
            raise ValueError("component reference is invalid or duplicated")
        refs.add(ref)
        if (component["footprint"] not in _FOOTPRINTS or not isinstance(component["value"], str)
                or not 1 <= len(component["value"]) <= 80
                or not all(isinstance(component[k], (int, float)) and not isinstance(component[k], bool) for k in ("x", "y"))
                or not 5 <= component["x"] <= board["width_mm"] - 5
                or not 5 <= component["y"] <= board["height_mm"] - 5):
            raise ValueError("component placement is invalid")
        pins = component["pins"]
        if (not isinstance(pins, dict) or not 1 <= len(pins) <= 16
                or not all(isinstance(pin, str) and pin.isdigit() and 1 <= len(pin) <= 2
                           and isinstance(net, str) and _NET.fullmatch(net) for pin, net in pins.items())):
            raise ValueError("component pin map is invalid")
    skus = inventory_skus or set()
    if not isinstance(plan["inventory_use"], list) or len(plan["inventory_use"]) > 64:
        raise ValueError("inventory use is invalid")
    for item in plan["inventory_use"]:
        if (not isinstance(item, dict) or set(item) != {"sku", "name", "available", "quantity"}
                or item["sku"] not in skus or not isinstance(item["name"], str)
                or not isinstance(item["quantity"], (int, float)) or isinstance(item["quantity"], bool)
                or not isinstance(item["available"], (int, float)) or isinstance(item["available"], bool)
                or item["quantity"] <= 0 or item["available"] < item["quantity"]):
            raise ValueError("project inventory reference is invalid")
    for key, limit in (("missing_parts", 64), ("assumptions", 32)):
        if not isinstance(plan[key], list) or len(plan[key]) > limit:
            raise ValueError(f"{key} is invalid")
    if not all(isinstance(item, dict) and set(item) == {"part", "quantity", "reason"}
               and isinstance(item["part"], str) and 1 <= len(item["part"]) <= 160
               and isinstance(item["quantity"], (int, float)) and not isinstance(item["quantity"], bool) and item["quantity"] > 0
               and isinstance(item["reason"], str) and 1 <= len(item["reason"]) <= 240
               for item in plan["missing_parts"]):
        raise ValueError("missing-parts list is invalid")
    if not all(isinstance(item, str) and 1 <= len(item) <= 300 for item in plan["assumptions"]):
        raise ValueError("assumptions are invalid")
    if redact_text(str(plan)) != str(plan):
        raise ValueError("project plan contains secret-shaped data")
    return plan
