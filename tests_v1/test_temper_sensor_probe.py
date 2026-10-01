import importlib.util
import json
import stat
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "deploy/temper/temper_sensor_probe.py"
spec = importlib.util.spec_from_file_location("temper_sensor_probe", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_probe_retains_no_image_and_reports_success(tmp_path):
    device = tmp_path / "video0"
    device.touch()
    fake_stat = device.stat()
    with patch.object(Path, "stat", return_value=type("S", (), {"st_mode": stat.S_IFCHR})()), \
            patch.object(module.subprocess, "run") as run:
        run.return_value.returncode = 0
        result = module.probe(device)
    assert result["available"] is True
    assert result["image_retained"] is False
    assert result["external_actions"] == 0
    assert "--stream-to=/dev/null" in run.call_args.args[0]


def test_atomic_output_is_private_and_valid(tmp_path):
    target = tmp_path / "camera-health.json"
    module.atomic_write(target, {"available": True})
    assert json.loads(target.read_text()) == {"available": True}
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_service_is_unprivileged_bounded_and_timer_driven():
    unit = (ROOT / "deploy/temper/orca-temper-sensor-probe.service").read_text()
    timer = (ROOT / "deploy/temper/orca-temper-sensor-probe.timer").read_text()
    assert "User=fryrocket" in unit
    assert "SupplementaryGroups=video" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "ProtectSystem=strict" in unit
    assert "MemoryMax=96M" in unit and "CPUQuota=20%" in unit
    assert "OnUnitActiveSec=120s" in timer
