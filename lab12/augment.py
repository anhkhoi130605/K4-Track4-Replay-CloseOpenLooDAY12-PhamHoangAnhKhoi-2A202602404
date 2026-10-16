"""Step 7 (fix and re-gate): learn from the scenario family, not only from the logs.

The gate said the learned planner fails in cut-in situations the logs never contain. We generate such situations in
simulation, let the IDM rule act in them, and add those (history, observation, next 3 s) windows to the training set.
"""
import numpy as np

from . import config as C, sim
from .models import features
from .planners import IDM, clip_cmd, idm_forecast


def cutin_windows(n_scen, rng, expert=None, v_range=(4.0, 16.0), gap_range=(2.5, 60.0), steps_after=20, stride=2):
    """Simulate `n_scen` random cut-ins (cruise speed, gap, closing speed up to a standing cutter) with the expert
    driving the ego, and return (X_perc, Y) windows taken during the first `steps_after` steps after the cut-in.
    Windows after a collision are dropped (the expert could not avoid it)."""
    expert = expert or IDM()
    H, F, L = C.H, C.F, C.VEH_LEN
    v0 = rng.uniform(*v_range, n_scen)
    gap0 = rng.uniform(*gap_range, n_scen)
    dv = rng.uniform(0.0, 1.0, n_scen) * v0
    n_steps = steps_after + F + 1
    v = np.zeros((n_scen, n_steps + 1))
    g = np.zeros((n_scen, n_steps + 1))
    v[:, 0], g[:, 0] = v0, gap0
    lead_v = v0 - dv
    alive = np.ones((n_scen, n_steps + 1), bool)
    for k in range(n_steps):
        a = clip_cmd(expert.act(None, v[:, k], g[:, k], lead_v))
        v[:, k + 1] = np.maximum(0.0, v[:, k] + a * C.DT)
        g[:, k + 1] = g[:, k] + (lead_v - 0.5 * (v[:, k] + v[:, k + 1])) * C.DT
        alive[:, k + 1] = alive[:, k] & (g[:, k + 1] > 0)
    Xs, Ys = [], []
    for k in range(0, steps_after, stride):
        ok = alive[:, k + F]
        cols = np.clip(np.arange(k - H, k + 1), 0, None)       # before the cut-in the ego cruised at v0 (= v[:, 0])
        hist = v[:, cols]
        cur = v[:, k]
        Xs.append(features("perc", (hist - cur[:, None])[ok], cur[ok], g[ok, k], lead_v[ok]))
        Ys.append((v[ok, k + 1:k + F + 1] - cur[ok, None]).astype(np.float32))
    return np.concatenate(Xs), np.concatenate(Ys)


def dagger_windows(planner, logs, idx, expert=None):
    """Let `planner` drive the training logs in closed loop, record the states it visits, and label each one with what
    the expert rule would do there (its 3 s speed forecast). Returns (X_perc, Y). Training on these teaches the
    planner to recover from its own small errors instead of only imitating states the human visited."""
    # TODO (Bước 7): hãy tự cài hàm này. Gợi ý:
    #   (1) rec = []; sim.rollout_logs(planner, logs, idx, record=rec). (2) Mỗi phần tử của rec là
    #   (hist_rel, v, gap, lead_v) của các hàng còn đang lái: np.concatenate theo từng thành phần. (3) X =
    #   features('perc', hist_rel, v, gap, lead_v). (4) Y = idm_forecast(expert, v, gap, lead_v): nhãn là
    #   việc luật IDM sẽ làm Ở CHÍNH các trạng thái đó. Trả (X, Y).
    rec = []
    sim.rollout_logs(planner, logs, idx, record=rec)
    if not rec:
        return np.zeros((0, C.H + 4), dtype=np.float32), np.zeros((0, C.F), dtype=np.float32)
    hist_rel = np.concatenate([r[0] for r in rec], axis=0)
    v = np.concatenate([r[1] for r in rec], axis=0)
    gap = np.concatenate([r[2] for r in rec], axis=0)
    lead_v = np.concatenate([r[3] for r in rec], axis=0)
    X = features("perc", hist_rel, v, gap, lead_v)
    expert = expert or IDM()
    Y = idm_forecast(expert, v, gap, lead_v)
    return X, Y
