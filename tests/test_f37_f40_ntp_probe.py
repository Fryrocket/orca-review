"""R11-F37–F40 ("ntp probe").

Audited mao/scheduler_ntp.py::ntp_synchronized() and require_ntp_or_refuse()
directly (not through the scheduler) rather than guessing at a fix from the
one-word hint. Manually verified four real scenarios against the actual
subprocess-calling implementation (fake `timedatectl` on PATH, since this
dev machine has no real one): synced ("yes"), unsynced ("no"), a hung
process (confirms the 5s timeout fires and returns False, not a hang), and
`timedatectl` absent entirely. All four behaved correctly — fail-closed
(False) whenever sync status can't be positively confirmed.

The actual finding: every existing test that touches NTP (test_round6.py's
test_ntp_unsynced_refuses_with_stage / test_ntp_synced_permits_arming, and
test_product.py's scheduler tests) monkeypatches ntp_synchronized() or
require_ntp_or_refuse() itself — the real subprocess/parsing logic in
ntp_synchronized() was never exercised by any test. A regression in the
timedatectl invocation, the stdout parsing, or the timeout handling would
have gone completely undetected. These tests close that gap by mocking
subprocess.run/shutil.which instead of the function under test."""

import subprocess
from unittest.mock import patch

from mao.errors import NTPNotSyncedError
from mao.scheduler_ntp import ntp_synchronized, require_ntp_or_refuse


def _run_result(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["timedatectl"], returncode=returncode, stdout=stdout, stderr=""
    )


def test_probe_true_when_timedatectl_reports_yes():
    with patch("mao.scheduler_ntp.shutil.which", return_value="/usr/bin/timedatectl"), \
         patch("mao.scheduler_ntp.subprocess.run", return_value=_run_result("yes\n")):
        assert ntp_synchronized() is True


def test_probe_false_when_timedatectl_reports_no():
    with patch("mao.scheduler_ntp.shutil.which", return_value="/usr/bin/timedatectl"), \
         patch("mao.scheduler_ntp.subprocess.run", return_value=_run_result("no\n")):
        assert ntp_synchronized() is False


def test_probe_false_on_empty_or_garbage_stdout():
    """Nonzero returncode / unexpected output must fail closed, not crash
    or misinterpret garbage as synced."""
    with patch("mao.scheduler_ntp.shutil.which", return_value="/usr/bin/timedatectl"), \
         patch("mao.scheduler_ntp.subprocess.run", return_value=_run_result("", returncode=1)):
        assert ntp_synchronized() is False


def test_probe_false_when_timedatectl_hangs_past_timeout():
    """The 5s timeout must actually be caught and treated as unsynced, not
    propagate as an unhandled TimeoutExpired."""
    with patch("mao.scheduler_ntp.shutil.which", return_value="/usr/bin/timedatectl"), \
         patch(
             "mao.scheduler_ntp.subprocess.run",
             side_effect=subprocess.TimeoutExpired(cmd="timedatectl", timeout=5),
         ):
        assert ntp_synchronized() is False


def test_probe_false_when_timedatectl_not_on_path():
    """Dev machines / containers without timedatectl at all must fail
    closed rather than erroring or (worse) assuming synced."""
    with patch("mao.scheduler_ntp.shutil.which", return_value=None):
        assert ntp_synchronized() is False


def test_probe_case_and_whitespace_insensitive():
    """timedatectl's real output can include a trailing newline and the
    match should not be case-sensitive in either direction."""
    with patch("mao.scheduler_ntp.shutil.which", return_value="/usr/bin/timedatectl"), \
         patch("mao.scheduler_ntp.subprocess.run", return_value=_run_result("YES\n")):
        assert ntp_synchronized() is True


def test_require_ntp_or_refuse_includes_stage_and_timestamp_in_message():
    with patch("mao.scheduler_ntp.ntp_synchronized", return_value=False):
        try:
            require_ntp_or_refuse(stage="fire")
            assert False, "should have raised"
        except NTPNotSyncedError as e:
            assert "stage='fire'" in str(e)
            assert "utc_now=" in str(e)
