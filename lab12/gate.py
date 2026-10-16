"""Step 6: the release gate. A candidate planner is released only if it passes EVERY rule; one failed rule blocks it.

The rules encode the lecture: do not trust the open-loop score, beat the simple rule in closed loop, test the boundary
and not the average, report spread over seeds, and test with a reacting world.
"""
import numpy as np

RULES = {
    "R1_replay_reproducible": "the replay tool itself is reproducible: re-run identical, refactor within tolerance",
    "R2_closed_loop_logs": "non-inferior to the IDM baseline on held-out logs: upper 95 % bound of the collision rate <= baseline rate + 1 point (worst seed)",
    "R3_braking_slice": "same on the slice where the lead brakes (fewer trajectories, so margin 5 points)",
    "R4_scenario_grid": "collision area on the cut-in grid that is physically avoidable <= baseline + 2 points (t_react = 0.6 s)",
    "R5_seed_stability": "collision rate varies by <= 1 point across training seeds",
    "R6_reactive_world": "collision area with a REACTIVE rear vehicle <= baseline + 2 points",
    "R7_coverage": "enough scenarios were actually run: >= 100 mined braking events, >= 2000 grid cells",
}


def rule_closed_loop_logs(c, b, margin=0.01):
    """R2. Non-inferiority on the held-out logs. c, b: the candidate's and the baseline's entry of closedloop.json["logs"]
    (each has ["collision"] = {"rate", "ci95": [low, high], ...}; for a learned planner the entry is its WORST seed).
    Pass when the candidate's UPPER 95 % bound is <= baseline rate + margin. Returns (passed: bool, detail: str)."""
    # TODO (Bước 6): hãy tự cài hàm này. Gợi ý:
    #   Quy tắc không-kém-hơn: pass khi CẬN TRÊN 95% của ứng viên <= tỷ lệ va chạm của baseline + margin.
    #   Trả (ok, chuỗi mô tả) với chuỗi nêu số của cả hai bên.
    candidate_upper = c["collision"]["ci95"][1]
    baseline_rate = b["collision"]["rate"]
    passed = candidate_upper <= baseline_rate + margin
    detail = f"candidate upper 95%: {candidate_upper:.4f}, baseline rate: {baseline_rate:.4f}, margin: {margin:.4f}"
    return passed, detail


def rule_scenario_grid(area_candidate, area_baseline, margin=0.02):
    """R4. Both areas are the share of the cut-in grid where contact was avoidable but happened (0..1), worst seed.
    Pass when candidate <= baseline + margin. Returns (passed: bool, detail: str)."""
    # TODO (Bước 6): hãy tự cài hàm này. Gợi ý:
    #   pass khi diện tích của ứng viên <= diện tích của baseline + margin. Trả (ok, chuỗi mô tả).
    passed = area_candidate <= area_baseline + margin
    detail = f"candidate area: {area_candidate:.4f}, baseline area: {area_baseline:.4f}, margin: {margin:.4f}"
    return passed, detail


def evaluate(candidate, baseline, ev):
    """candidate/baseline: planner names. ev: dict of evidence collected by the earlier steps. Returns (release, rules)."""
    r = {}
    r["R1_replay_reproducible"] = (bool(ev["replay"]["rerun_identical"]) and ev["replay"]["refactor_float32"]["differ_beyond_tol"] == 0,
                                   "rerun identical and refactor differs beyond tol in 0 segments")

    cl = ev["closed_loop"]["logs"]
    c, b = cl[candidate], cl[baseline]
    r["R2_closed_loop_logs"] = rule_closed_loop_logs(c, b)
    r["R3_braking_slice"] = (c["collision_brake_slice"]["ci95"][1] <= b["collision_brake_slice"]["rate"] + 0.05,
                             f"{c['collision_brake_slice']['rate']*100:.1f} % (n={c['collision_brake_slice']['n']}, upper "
                             f"{c['collision_brake_slice']['ci95'][1]*100:.1f} %) vs baseline {b['collision_brake_slice']['rate']*100:.1f} % + 5 points")

    grid = ev["closed_loop"]["grid"]["t_react_0.6"]
    gc, gb = grid[candidate]["attributable_area"], grid[baseline]["attributable_area"]
    r["R4_scenario_grid"] = rule_scenario_grid(gc, gb)
    seeds = c["per_seed_collision_rate"]
    r["R5_seed_stability"] = (max(seeds) - min(seeds) <= 0.01, f"{min(seeds)*100:.1f} .. {max(seeds)*100:.1f} % over {len(seeds)} run(s)")

    rc, rb = ev["agents"]["rear_comparison_t_react_0.6"][candidate]["reactive"]["any"], ev["agents"]["rear_comparison_t_react_0.6"][baseline]["reactive"]["any"]
    r["R6_reactive_world"] = (rc <= rb + 0.02, f"{rc*100:.1f} % of the grid vs baseline {rb*100:.1f} %")

    cov = ev["scenarios"]["coverage"]
    r["R7_coverage"] = (cov["mined_events"] >= 100 and cov["grid_cells"] >= 2000,
                        f"{cov['mined_events']} mined events, {cov['grid_cells']} grid cells")

    release = all(ok for ok, _ in r.values())
    return release, {k: {"pass": bool(ok), "detail": d, "rule": RULES[k]} for k, (ok, d) in r.items()}
