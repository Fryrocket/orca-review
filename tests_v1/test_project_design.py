import importlib.util
from pathlib import Path

import pytest

from orca.project_design import dog_feeder_plan, validate_project_plan


def inventory():
    return {"items": [{"sku": "JST-XH-2-PIN-HOUSINGS", "name": "JST XH housings", "quantity": 25}]}


def test_dog_feeder_plan_uses_only_real_inventory_and_marks_draft():
    plan = dog_feeder_plan("Let's create an efficient AI-powered dog feeder", inventory())
    assert plan["inventory_use"] == [{"sku": "JST-XH-2-PIN-HOUSINGS", "name": "JST XH housings", "available": 25, "quantity": 4}]
    assert {component["ref"] for component in plan["components"]} == {"J1", "J2", "J3", "J4", "J5", "J6", "J7", "Q1", "D1"}
    assert {"VIN", "GND", "MOTOR+"} == set(plan["board"]["route_nets"])
    assert any("human" in note for note in plan["assumptions"])


def test_plan_rejects_unrecorded_inventory_and_path_like_reference():
    plan = dog_feeder_plan("build a dog feeder", inventory())
    plan["inventory_use"][0]["sku"] = "INVENTED"
    with pytest.raises(ValueError, match="inventory"):
        validate_project_plan(plan, {"JST-XH-2-PIN-HOUSINGS"})
    plan = dog_feeder_plan("build a dog feeder", inventory())
    plan["components"][0]["ref"] = "../../J1"
    with pytest.raises(ValueError, match="reference"):
        validate_project_plan(plan, {"JST-XH-2-PIN-HOUSINGS"})


def test_project_builder_creates_unique_bounded_folder_and_schematic(tmp_path, monkeypatch):
    source = Path("desktop/KILNStudio/project_builder.py")
    spec = importlib.util.spec_from_file_location("project_builder_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_build_board", lambda plan, path: path.write_text("pcb", encoding="utf-8"))
    monkeypatch.setattr(module, "_pdf_report", lambda path, *args: path.write_bytes(b"%PDF-test"))
    def fake_tool(command, timeout=45):
        if command[0].endswith("pdftoppm"):
            Path(command[-1] + ".png").write_bytes(b"png")
        elif command[0].endswith("libreoffice"):
            Path(command[command.index("--outdir") + 1], "BOM-DRAFT.ods").write_bytes(b"ods")
        return "ok"
    monkeypatch.setattr(module, "_run_fixed", fake_tool)
    plan = dog_feeder_plan("build a dog feeder", inventory())
    first = module.create_project(plan, tmp_path)
    second = module.create_project(plan, tmp_path)
    assert first["folder"] != second["folder"]
    assert Path(first["folder"]).parent == tmp_path
    text = Path(first["schematic"]).read_text()
    assert "EDITABLE PROTOTYPE" in text
    assert "DRAFT ONLY" in text
    assert Path(first["board"]).read_text() == "pcb"
    assert "NOT RELEASED FOR FABRICATION" in Path(first["readiness"]).read_text()
    assert "Manufacturer part number" in (Path(first["folder"]) / "BOM-DRAFT.csv").read_text()
    assert Path(first["bom"]).suffix == ".ods"
    assert len(first["checks"]) >= 8
    assert any(item["name"] == "KiCad PCB Editor" for item in first["resources"])
    assert any(item["name"] == "FILE-MAP.json" or item["name"] == "DESIGN-REVIEW.json"
               for item in first["file_map"]["files"])


def test_native_builder_rejects_schematic_injection(tmp_path, monkeypatch):
    source = Path("desktop/KILNStudio/project_builder.py")
    spec = importlib.util.spec_from_file_location("project_builder_reject", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_build_board", lambda plan, path: None)
    plan = dog_feeder_plan("build a dog feeder", inventory())
    plan["components"][0]["value"] = 'POWER"\n$EndSCHEMATC'
    with pytest.raises(ValueError, match="component"):
        module.create_project(plan, tmp_path)


def test_project_intent_is_explicit_only():
    source = Path("orca/static/launcher.js").read_text()
    assert "parseProject" in source
    assert "don't|do not|explain|describe" in source


def test_product_builder_is_a_first_class_workspace_below_operations():
    html_source = Path("orca/static/index.html").read_text()
    nav = html_source.split('<nav class="primary-nav"', 1)[1].split("</nav>", 1)[0]
    assert nav.index('data-view="operations"') < nav.index('data-view="product-builder"')
    assert '<section id="product-builder" class="view">' in html_source
    assert 'id="builder-files"' in html_source
    assert 'id="builder-resources"' in html_source
    assert 'id="builder-checks"' in html_source
    script = Path("orca/static/product-builder.js").read_text()
    assert "postMutation('/api/product-development/plans'" in script
    assert "postProjectPlan(currentPlan.brief)" in script
    assert "StudioLauncher.createProject(plan)" in script
    assert "StudioLauncher.openArtifact" in script
