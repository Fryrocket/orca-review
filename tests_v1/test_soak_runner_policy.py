from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_soak_media_uses_short_video_samples_not_disallowed_lengths():
    source = (ROOT / "scripts/orca_soak_test.py").read_text()
    assert "SHORT_VIDEO_FRAMES = 33" in source
    assert '"length": SHORT_VIDEO_FRAMES' in source
    assert '"length": 49' not in source
    assert '"length": 73' not in source
