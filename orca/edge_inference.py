from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EdgeModel:
    id: str
    task: str
    artifact: str
    state: str
    input_types: tuple[str, ...]
    benchmark_fps: float


@dataclass(frozen=True)
class EdgeWorkflow:
    id: str
    area: str
    purpose: str
    model_tasks: tuple[str, ...]
    readiness: str
    output: str


# These artifacts are supplied by the Raspberry Pi/Hailo packages installed on
# TEMPER.  They are Hailo-8 artifacts, not the incompatible H8L/H10 variants.
H8_MODELS = (
    EdgeModel(
        "yolov6n_h8", "object_detection",
        "/usr/share/hailo-models/yolov6n_h8.hef", "runtime_benchmarked",
        ("usb_camera", "image", "video"), 140.9,
    ),
    EdgeModel(
        "yolov8s_h8", "object_detection",
        "/usr/share/hailo-models/yolov8s_h8.hef", "runtime_benchmarked",
        ("usb_camera", "image", "video"), 148.22,
    ),
    EdgeModel(
        "yolov5n_seg_h8", "instance_segmentation",
        "/usr/share/hailo-models/yolov5n_seg_h8.hef", "runtime_benchmarked",
        ("usb_camera", "image", "video"), 61.32,
    ),
    EdgeModel(
        "yolov8s_pose_h8", "pose_estimation",
        "/usr/share/hailo-models/yolov8s_pose_h8.hef", "runtime_benchmarked",
        ("usb_camera", "image", "video"), 228.5,
    ),
)


EDGE_WORKFLOWS = (
    EdgeWorkflow(
        "inventory_visual_count", "inventory",
        "Count and locate visible stock while keeping the canonical ledger authoritative.",
        ("object_detection", "instance_segmentation"), "camera_and_acceptance_required",
        "count proposal with frame, model and confidence evidence",
    ),
    EdgeWorkflow(
        "receiving_and_packaging_check", "inventory",
        "Flag damaged, missing, duplicated or incorrectly packed incoming items.",
        ("object_detection", "instance_segmentation"), "custom_model_required",
        "inspection proposal; never an automatic acceptance or rejection",
    ),
    EdgeWorkflow(
        "pcb_assembly_inspection", "engineering",
        "Assist inspection of component presence, orientation, soldering and visible defects.",
        ("object_detection", "instance_segmentation"), "custom_model_required",
        "annotated defect candidates for human or QUENCH review",
    ),
    EdgeWorkflow(
        "product_media_preflight", "canvas",
        "Preflight product photos and clips for framing, occlusion and visible subject placement.",
        ("object_detection", "instance_segmentation"), "camera_or_file_input_required",
        "quality findings and crop/mask suggestions",
    ),
    EdgeWorkflow(
        "prototype_observation", "product-builder",
        "Observe bounded prototype tests and associate visible events with the test timeline.",
        ("object_detection", "pose_estimation"), "camera_and_acceptance_required",
        "timestamped observations, never autonomous physical control",
    ),
    EdgeWorkflow(
        "lab_safety_observation", "operations",
        "Detect configured visible hazards or missing protective equipment in a declared test area.",
        ("object_detection", "pose_estimation"), "custom_model_and_owner_policy_required",
        "advisory alert with retained evidence limits",
    ),
    EdgeWorkflow(
        "listing_asset_verification", "business",
        "Compare draft listing assets with the selected product and required image checklist.",
        ("object_detection", "instance_segmentation"), "custom_model_required",
        "mismatch report; publishing remains approval-controlled",
    ),
    EdgeWorkflow(
        "sensor_quality_and_anomaly", "bgm",
        "Run low-latency artifact and anomaly screening near the sensor source.",
        ("signal_quality", "anomaly_detection"), "validated_custom_hef_required",
        "quality/anomaly evidence only; no diagnosis, dosing or medical claim",
    ),
    EdgeWorkflow(
        "local_speech_recognition", "studio",
        "Transcribe bounded local voice input without consuming general reasoning capacity.",
        ("automatic_speech_recognition",), "validated_audio_model_required",
        "draft transcript for review before sending",
    ),
)


EDGE_GOVERNANCE = {
    "execution": (
        "Signed bounded jobs only. Every result records source, model ID, artifact hash, "
        "timestamps, confidence, latency, temperature and disposition."
    ),
    "privacy": (
        "No facial recognition, identity inference, covert surveillance or unbounded recording. "
        "Frames are retained only when the owning workflow explicitly requires evidence."
    ),
    "authority": (
        "Inference may observe, classify and propose. It may not publish, purchase, change stock, "
        "operate machinery, make a medical decision or approve its own output."
    ),
    "safety": (
        "One bounded accelerator queue with temperature, memory, disk, deadline and restart limits; "
        "fail closed on stale models, missing provenance or evidence-integrity failure."
    ),
    "fallback": "CPU preprocessing remains available; unavailable Hailo work returns a typed blocked result.",
}


GENERIC_VISION_WORKFLOWS = frozenset({
    "inventory_visual_count", "product_media_preflight", "prototype_observation",
})


def plan_edge_workflow(*, workflow_id: str, input_kind: str = "camera",
                       labels: tuple[str, ...] | list[str] = ()) -> dict:
    """Build a read-only, non-executing TEMPER workflow plan."""
    workflows = {workflow.id: workflow for workflow in EDGE_WORKFLOWS}
    if workflow_id not in workflows:
        raise ValueError("edge workflow is not registered")
    if input_kind not in {"camera", "image", "video"}:
        raise ValueError("edge workflow input is not accepted")
    if not isinstance(labels, (tuple, list)) or len(labels) > 50 or any(
            not isinstance(label, str) or not label.strip() or len(label) > 80
            for label in labels):
        raise ValueError("edge workflow labels are invalid")
    normalized_labels = tuple(dict.fromkeys(label.strip() for label in labels))
    workflow = workflows[workflow_id]
    custom_required = "custom_model" in workflow.readiness or any(
        task in {"signal_quality", "anomaly_detection", "automatic_speech_recognition"}
        for task in workflow.model_tasks)
    if custom_required:
        state = "blocked_custom_model_required"
    elif workflow_id == "inventory_visual_count" and not normalized_labels:
        state = "needs_declared_label_scope"
    else:
        state = "ready_for_bounded_dry_run"
    candidates = [model.id for model in H8_MODELS if model.task in workflow.model_tasks]
    return {
        "node_id": "temper",
        "workflow": asdict(workflow),
        "input_kind": input_kind,
        "state": state,
        "model_candidates": candidates,
        "declared_labels": list(normalized_labels),
        "generic_model_scope": workflow_id in GENERIC_VISION_WORKFLOWS,
        "may_execute": False,
        "next_gate": (
            "validated custom Hailo-8 model with provenance and task evaluation"
            if custom_required else
            "declare the exact countable label set"
            if state == "needs_declared_label_scope" else
            "stage a signed bounded dry run and owner-reviewed evidence"
        ),
        "required_evidence": [
            "input hash or camera device", "model id and artifact hash",
            "frame count and timestamps", "confidence and latency",
            "TEMPER temperature", "disposition and reviewer",
        ],
        "prohibited": [
            "stock mutation", "publishing", "purchasing", "physical control",
            "identity inference", "self-approval",
        ],
    }


def edge_inference_blueprint(*, camera_connected: bool = True) -> dict:
    """Describe TEMPER's accepted edge scope without starting remote execution."""
    return {
        "node_id": "temper",
        "accelerator": "Hailo-8",
        "capacity": {"tops_int8": 26, "scheduler": "single governed queue"},
        "benchmark": {
            "date": "2026-10-01",
            "method": "HailoRT hardware-only synthetic streaming input",
            "scope": "accelerator throughput, not end-to-end camera or post-processing latency",
        },
        "camera": {
            "type": "USB UVC HDMI capture camera",
            "connected": camera_connected,
            "discovery": "automatic uvcvideo/V4L2 discovery; internal Pi codec devices excluded",
            "accepted_profile": "MJPEG 1280x720 at 30 FPS; bounded inference at 640x640 and 5 FPS",
            "state": "accepted_available" if camera_connected else "accepted_not_connected",
        },
        "models": [asdict(model) for model in H8_MODELS],
        "workflows": [asdict(workflow) for workflow in EDGE_WORKFLOWS],
        "governance": EDGE_GOVERNANCE,
        "runtime": {
            "hardware": "verified",
            "job_broker": "live_camera_and_file_accepted",
            "model_invocation": "signed_bounded_camera_and_file_jobs",
            "camera_and_file_inputs": "accepted",
            "automatic_execution": False,
            "reason": "signed broker, four pinned models, physical camera and approved-file pipelines are accepted; custom models and autonomous workflows remain gated",
        },
    }
