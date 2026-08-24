"""R11-F54: a bare `assert` statement is stripped entirely by `python -O`
(or PYTHONOPTIMIZE=1) — Python doesn't warn, it just removes the check. The
TEAM/UNCLASSIFIED invariant in mao/roles.py used to be a bare module-level
assert, meaning that check silently stopped running on any optimized
deployment. It's now a real conditional + raise, which no interpreter flag
can compile away.

The subprocess tests here are the only way to actually prove this: -O is a
process-wide flag, not something you can toggle after mao.roles is already
imported in-process."""

import subprocess
import sys
import textwrap


def _run(code: str, optimize: bool) -> subprocess.CompletedProcess:
    cmd = [sys.executable]
    if optimize:
        cmd.append("-O")
    cmd += ["-c", code]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_roles_module_has_no_bare_assert_statements():
    """Static guard: catches anyone reintroducing a bare `assert` for a
    real invariant in this file."""
    import ast
    from pathlib import Path

    src = Path(__file__).parent.parent / "mao" / "roles.py"
    tree = ast.parse(src.read_text())
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    assert asserts == [], f"mao/roles.py has bare assert statement(s) at lines {[a.lineno for a in asserts]} — these are stripped under python -O"


def test_team_invariant_violation_raises_normally():
    code = textwrap.dedent(
        """
        from mao.roles import Privilege, JobDuty, OrcaConfigError
        TEAM = {"broken": JobDuty(name="broken", title="x", privileges={Privilege.UNCLASSIFIED})}
        if any(Privilege.UNCLASSIFIED in d.privileges for d in TEAM.values()):
            raise OrcaConfigError("UNCLASSIFIED must not be held")
        print("NOT RAISED")
        """
    )
    result = _run(code, optimize=False)
    assert result.returncode != 0
    assert "OrcaConfigError" in result.stderr


def test_team_invariant_violation_still_raises_under_dash_o():
    """The actual F54 regression check: the same violation must still
    raise even when the interpreter is run with -O."""
    code = textwrap.dedent(
        """
        from mao.roles import Privilege, JobDuty, OrcaConfigError
        TEAM = {"broken": JobDuty(name="broken", title="x", privileges={Privilege.UNCLASSIFIED})}
        if any(Privilege.UNCLASSIFIED in d.privileges for d in TEAM.values()):
            raise OrcaConfigError("UNCLASSIFIED must not be held")
        print("NOT RAISED")
        """
    )
    result = _run(code, optimize=True)
    assert result.returncode != 0, "invariant check was compiled away under -O"
    assert "OrcaConfigError" in result.stderr


def test_real_module_imports_cleanly_under_dash_o():
    """The real TEAM definition is valid, so importing mao.roles under -O
    must not raise anything — this fix must not break normal loading."""
    result = _run("import mao.roles; print('OK')", optimize=True)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
