#!/usr/bin/env python3
import argparse, json, os, time
from pathlib import Path

INPUTS = {
    "backup": Path("/var/lib/orca-backup/status.json"),
    "offsite": Path("/var/lib/orca-offsite/status.json"),
    "restore": Path("/var/lib/orca-backup/restore-drill-latest.json"),
}

def evaluate(paths=INPUTS, now=None, max_age=172800):
    now = int(time.time() if now is None else now)
    checks, state = {}, "healthy"
    for name, path in paths.items():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            stamp = data.get("updated_epoch", data.get("verified_epoch"))
            if not isinstance(stamp, int) or stamp > now + 300:
                raise ValueError("invalid evidence timestamp")
            age = now - stamp
            source_state = data.get("state")
            ok = source_state in {"healthy", "passed"} and age <= max_age
            checks[name] = {"state": source_state, "age_seconds": age, "fresh": age <= max_age, "ok": ok}
            if not ok: state = "degraded"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks[name] = {"state": "unavailable", "ok": False, "error": type(exc).__name__}
            state = "degraded"
    return {"schema_version": 1, "bot_id": "recovery_marshal", "state": state,
            "observed_epoch": now, "checks": checks,
            "alert_required": state != "healthy",
            "alert_class": "backup_evidence_exception" if state != "healthy" else None,
            "authority": "read_only_evidence_observer"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/var/lib/orca-recovery-marshal/status.json")
    parser.add_argument("--max-age", type=int, default=172800)
    args = parser.parse_args()
    report = evaluate(max_age=args.max_age)
    target = Path(args.output); target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640); os.replace(temporary, target)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1

if __name__ == "__main__": raise SystemExit(main())
