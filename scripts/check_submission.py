"""Self-check before you submit.   python3 scripts/check_submission.py [--save-verify]

Checks that your evidence is complete and consistent, that the tests pass, that REPORT.md is filled and that the repo is clean.
It does NOT grade the content of your answers. Any [FAIL] costs points (see RUBRIC.md); [WARN] is advice.
Run it from the repo root (the folder that contains run_all.py).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
EVID = ROOT / "evidence"
FILES = ["data_audit", "replay", "scenarios", "openloop", "closedloop", "agents", "gate", "fix"]
LEARNED = ["EgoMLP", "PercMLP"]
OUT = []


def say(kind, msg):
    OUT.append(f"[{kind}] {msg}")
    print(OUT[-1])


def ok(cond, msg, warn=False):
    say("PASS" if cond else ("WARN" if warn else "FAIL"), msg)
    return cond


def load(name):
    p = EVID / f"{name}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def report_fields():
    p = ROOT / "REPORT.md"
    if not p.exists():
        return None, None
    text = p.read_text(encoding="utf-8")
    m = re.search(r"\|\s*MSSV[^|]*\|\s*`?([^`|\n]+?)`?\s*\|", text)
    return (m.group(1).strip() if m else None), text


def check_evidence():
    ev = {n: load(n) for n in FILES}
    for n in FILES:
        ok(ev[n] is not None, f"evidence/{n}.json exists and is valid JSON")
    if any(v is None for v in ev.values()):
        return ev, False
    ids = {n: ev[n].get("student", {}).get("student_id") for n in FILES if n != "data_audit"}
    splits = {n: ev[n].get("student", {}).get("split_seed") for n in FILES if n != "data_audit"}
    ok(len(set(ids.values())) == 1, f"one student id in every evidence file ({sorted(set(map(str, ids.values())))})")
    ok(len(set(splits.values())) == 1, "one split seed in every evidence file (all steps were run with the same --student-id)")
    sid = next(iter(ids.values()))
    ok(sid not in (None, "demo"), "evidence was produced with a real student id, not the default 'demo'")

    a = ev["data_audit"]
    ok(a["exact_duplicates_removed"] > 0 and a["trajectories_clean"] < a["trajectories_raw"], "data audit removed the exact duplicates")

    r = ev["replay"]
    ok(r["rerun_identical"], "replay: same code twice gives identical commands")
    ok(r["refactor_float32"]["not_bit_identical"] > 0 and r["refactor_float32"]["differ_beyond_tol"] == 0,
       "replay: refactor is not bit-identical but within tolerance in every segment (your compare_with_tol)")
    n = r["n_segments"]
    ok(0 < r["behaviour_change_aeb"]["differ_beyond_tol"] < n, "replay: the AEB change flags SOME segments, not none and not all")
    ok(r["fastest"]["late"] + r["fastest"]["dropped"] == 0 and r["realtime"]["late"] + r["realtime"]["dropped"] > 0,
       "replay: real-time mode exposes late/dropped frames that 'fastest' mode hides")

    s = ev["scenarios"]
    v = s["validation_full_brake_vs_physics"]
    ok(all(x["mismatch_cells_away_from_frontier"] == 0 for x in v.values()),
       "scenarios: simulator agrees with your `unavoidable` frontier (0 mismatching cells at both delays)")
    ok(s["coverage"]["mined_events"] >= 100, f"scenarios: {s['coverage']['mined_events']} braking events mined (>= 100 expected)")

    o = ev["openloop"]
    ok(all(k in o["summary"] for k in ("const-vel", "IDM", "EgoMLP", "PercMLP", "PercMLP+")), "openloop: all five planners scored")
    ok(len(o["per_seed"]["EgoMLP"]) >= 3, f"openloop: {len(o['per_seed']['EgoMLP'])} training seeds (>= 3 needed)")
    ok(0 < o["slice_share"] < 0.5, "openloop: the braking slice is a small share of the windows")

    c = ev["closedloop"]
    ok(all(len(c["logs"][k]["per_seed_collision_rate"]) >= 3 for k in LEARNED), "closedloop: learned planners have >= 3 seeds")
    ok(set(c["grid"]) == {"t_react_0.0", "t_react_0.6"}, "closedloop: scenario grid evaluated at both reaction delays")
    ok(len(c["ranking"]["order_flips"]) >= 1, "closedloop: at least one pair of planners changes order between open and closed loop")
    ok("PercMLP+" in c["logs"], "closedloop: PercMLP+ was evaluated (step 7 was run)")

    g = ev["agents"]
    ok("best_T" in g["calibration"] and "rear_comparison_t_react_0.6" in g, "agents: calibrated IDM driver and both rear-vehicle worlds present")

    gt, fx = ev["gate"], ev["fix"]
    ok(all(k in gt["decisions"] for k in ("const-vel", "EgoMLP", "PercMLP", "PercMLP+")), "gate: a decision for every candidate")
    ok(gt["decisions"]["PercMLP+"]["release"] == fx["decision_PercMLP+"], "fix.json agrees with gate.json on PercMLP+")
    return ev, True


def check_tests():
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, capture_output=True, text=True)
    tail = [ln for ln in p.stderr.strip().splitlines() if ln.startswith(("Ran", "OK", "FAILED"))]
    ok(p.returncode == 0, "unit tests: " + " / ".join(tail))
    if p.returncode != 0:
        bad = sorted({m for m in re.findall(r"^(?:ERROR|FAIL): (\w+)", p.stderr, re.M)})
        say("INFO", "failing tests: " + ", ".join(bad[:12]))


def check_report(sid):
    mssv, text = report_fields()
    if text is None:
        ok(False, "REPORT.md exists")
        return
    ok(mssv not in (None, "<điền>", ""), f"REPORT.md has an MSSV ({mssv})")
    if sid:
        ok(mssv == sid, "MSSV in REPORT.md equals the student id used for the run")
    for key in ("Họ và tên", "GitHub"):
        m = re.search(rf"\|\s*{key}[^|]*\|\s*`?([^`|\n]*)`?\s*\|", text)
        ok(bool(m) and m.group(1).strip() not in ("", "<điền>", "<điền: tên tài khoản>"), f"REPORT.md: '{key}' is filled")
    parts = re.split(r"^## Câu (\d)", text, flags=re.M)
    answers = {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    ok(sorted(answers) == list(range(1, 9)), "REPORT.md has the 8 question sections")
    for q in range(1, 9):
        body = answers.get(q, "")
        body = body.split("\n", 2)[-1] if body else ""
        placeholder = "(trả lời ở đây)" in body
        digits = len(re.findall(r"\d+[.,]?\d*", body))
        ok(not placeholder and len(body.strip()) >= 250, f"Câu {q}: answered ({len(body.strip())} characters)")
        ok(digits >= 3, f"Câu {q}: quotes numbers from your evidence ({digits} numbers found)", warn=True)
    table = text.split("## Câu 1")[0]
    rows = [ln for ln in table.splitlines() if ln.startswith("|") and any(k in ln.lower() for k in ("constant", "const-vel", "idm", "egomlp", "percmlp"))]
    ok(all(len([c for c in ln.split("|")[2:-1] if c.strip()]) >= 2 for ln in rows) and len(rows) >= 5,
       "REPORT.md: the results table is filled")


def check_git():
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    r = git("rev-parse", "--is-inside-work-tree")
    if r.returncode != 0:
        say("WARN", "not inside a git repository: cannot check commits (you must submit through your own public GitHub repo)")
        return
    # a fork or clone carries the starter's commits (written by the instructor): count only yours.
    emails = git("log", "--format=%ae").stdout.split()
    roots = git("rev-list", "--max-parents=0", "HEAD").stdout.split()
    root_email = git("log", "--format=%ae", "-1", roots[-1]).stdout.strip() if roots else ""
    own = [e for e in emails if e != root_email]
    n = len(own) if own else len(emails)           # a repo you started from scratch has no starter commits
    ok(n >= 5, f"git: {n} commits of yours (>= 5 expected, spread over the steps)")
    files = git("ls-files").stdout.splitlines()
    bad = [f for f in files if "/work/" in "/" + f or f.startswith("work/") or re.search(r"(^|/)data/.+\.(csv|zip)$", f)]
    ok(not bad, "git: no raw data or work/ files are tracked" + (f" (found {bad[:3]})" if bad else ""))
    ok(any(f.startswith("evidence/") and f.endswith(".json") for f in files), "git: evidence/*.json is committed")
    ok("REPORT.md" in files or any(f.endswith("/REPORT.md") for f in files), "git: REPORT.md is committed")
    dirty = git("status", "--porcelain").stdout.strip()
    ok(not dirty, "git: no uncommitted changes (commit and push before submitting)", warn=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-verify", action="store_true", help="write evidence/verify.txt")
    a = ap.parse_args()
    print("== evidence ==")
    ev, _ = check_evidence()
    sid = None
    if ev.get("replay"):
        sid = ev["replay"].get("student", {}).get("student_id")
    print("\n== tests ==")
    check_tests()
    print("\n== report ==")
    check_report(sid)
    print("\n== git ==")
    check_git()
    fails = sum(1 for x in OUT if x.startswith("[FAIL]"))
    warns = sum(1 for x in OUT if x.startswith("[WARN]"))
    summary = f"\n{len(OUT) - fails - warns} passed, {warns} warnings, {fails} FAILED"
    print(summary)
    if a.save_verify:
        EVID.mkdir(exist_ok=True)
        (EVID / "verify.txt").write_text("\n".join(OUT) + summary + "\n", encoding="utf-8")
        print("saved evidence/verify.txt")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
