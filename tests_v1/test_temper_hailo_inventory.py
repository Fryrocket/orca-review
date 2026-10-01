import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "deploy/temper/temper_hailo_inventory.py"
SPEC = importlib.util.spec_from_file_location("temper_hailo_inventory", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_camera_discovery_excludes_internal_video_nodes(tmp_path):
    # Use real directory targets so strict symlink resolution behaves as it
    # does under /sys/class/video4linux.
    internal = tmp_path / "devices/platform/rp1-cfe/video0"
    external = tmp_path / "devices/pci/usb1/1-1/video4linux/video2"
    for target, name in ((internal, "rp1-cfe"), (external, "USB Camera")):
        target.mkdir(parents=True)
        (target / "name").write_text(name)
    classes = tmp_path / "class/video4linux"
    classes.mkdir(parents=True)
    (classes / "video0").symlink_to(internal, target_is_directory=True)
    (classes / "video2").symlink_to(external, target_is_directory=True)
    assert MODULE.discover_uvc_cameras(classes) == [
        {"device": "/dev/video2", "name": "USB Camera", "driver": "usb"}
    ]


def test_camera_discovery_excludes_uvc_metadata_companion(tmp_path):
    capture = tmp_path / "devices/pci/usb1/1-1/video4linux/video0"
    metadata = tmp_path / "devices/pci/usb1/1-1/video4linux/video1"
    for target, index in ((capture, "0"), (metadata, "1")):
        target.mkdir(parents=True)
        (target / "name").write_text("HDMI USB Camera")
        (target / "index").write_text(index)
    classes = tmp_path / "class/video4linux"
    classes.mkdir(parents=True)
    (classes / "video0").symlink_to(capture, target_is_directory=True)
    (classes / "video1").symlink_to(metadata, target_is_directory=True)
    assert MODULE.discover_uvc_cameras(classes) == [
        {"device": "/dev/video0", "name": "HDMI USB Camera", "driver": "usb"}
    ]


def test_model_inventory_accepts_h8_but_not_h8l(tmp_path):
    (tmp_path / "detector_h8.hef").write_bytes(b"h8")
    (tmp_path / "detector_h8l.hef").write_bytes(b"h8l")
    models = MODULE.discover_h8_models(tmp_path)
    assert [model["id"] for model in models] == ["detector_h8"]


def test_atomic_inventory_write_has_restrictive_mode(tmp_path):
    output = tmp_path / "state/inventory.json"
    MODULE.write_atomic(output, {"camera_connected": False})
    assert output.read_text().endswith("\n")
    assert output.stat().st_mode & 0o777 == 0o640
