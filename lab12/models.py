"""Learned planners: features, training windows, and a plain-numpy MLP (manual backprop + Adam, no torch).

Both learned planners predict the follower's next F speed deltas (relative to the current speed):
  EgoMLP  : sees only ego's own last 2 s of speed         (history-only baseline)
  PercMLP : the same + (gap, lead speed - ego speed)       (as if from perception)
"""
import numpy as np

from . import config as C


# ---------------------------------------------------------------- features
def features(kind, hist_rel, v, gap=None, lead_v=None):
    """hist_rel: (M, H+1) ego speeds minus the current speed; v: (M,) current speed. Same code for training and driving."""
    cols = [hist_rel, v[:, None]]
    if kind == "perc":
        cols += [gap[:, None], (lead_v - v)[:, None]]
    return np.concatenate(cols, 1).astype(np.float32)


def build_windows(logs, idx, stride=2):
    """Slide a (history 2 s -> future 3 s) window over each trajectory of `idx`.

    Returns X_ego, X_perc, Y (future speed deltas), `brake_ahead` (the lead decelerates below C.BRAKE_THRESHOLD
    within the future horizon: the slice that open-loop averages hide) and the trajectory index of each window.
    """
    H, F = C.H, C.F
    Xe, Xp, Y, B, W = [], [], [], [], []
    for t in range(H, logs.T - F, stride):
        sel = idx[logs.n[idx] > t + F]
        if len(sel) == 0:
            continue
        v = logs.v_ego[sel, t]
        hist_rel = logs.v_ego[sel, t - H:t + 1] - v[:, None]
        gap, vl = logs.gap[sel, t], logs.v_lead[sel, t]
        Xe.append(features("ego", hist_rel, v))
        Xp.append(features("perc", hist_rel, v, gap, vl))
        Y.append((logs.v_ego[sel, t + 1:t + F + 1] - v[:, None]).astype(np.float32))
        B.append(np.nanmin(logs.a_lead[sel, t:t + F + 1], axis=1) < C.BRAKE_THRESHOLD)
        W.append(sel)
    return np.concatenate(Xe), np.concatenate(Xp), np.concatenate(Y), np.concatenate(B), np.concatenate(W)


# ---------------------------------------------------------------- MLP
class MLP:
    def __init__(self, d_in, d_hid=128, d_out=C.F, seed=0):
        r = np.random.default_rng(seed)
        sizes = [d_in, d_hid, d_hid, d_out]
        self.W = [(r.standard_normal((a, b)) * np.sqrt(2.0 / a)).astype(np.float32) for a, b in zip(sizes[:-1], sizes[1:])]
        self.b = [np.zeros(b, np.float32) for b in sizes[1:]]
        self.m = [np.zeros_like(p) for p in self.W + self.b]
        self.v = [np.zeros_like(p) for p in self.W + self.b]
        self.t = 0

    def forward(self, x, keep=False):
        acts = [x]
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            x = x @ W + b
            if i < 2:
                x = np.maximum(x, 0.0)                       # ReLU on the two hidden layers
            acts.append(x)
        return (x, acts) if keep else x

    def step(self, x, y, lr=2e-3, b1=0.9, b2=0.999, eps=1e-8):
        out, acts = self.forward(x, keep=True)
        d = 2.0 * (out - y) / out.size                       # d(MSE)/d(out)
        gW, gb = [None] * 3, [None] * 3
        for i in (2, 1, 0):
            gW[i], gb[i] = acts[i].T @ d, d.sum(0)
            if i > 0:
                d = (d @ self.W[i].T) * (acts[i] > 0)
        self.t += 1
        for k, (p, g) in enumerate(zip(self.W + self.b, gW + gb)):   # Adam, in place
            self.m[k] = b1 * self.m[k] + (1 - b1) * g
            self.v[k] = b2 * self.v[k] + (1 - b2) * g * g
            p -= lr * (self.m[k] / (1 - b1 ** self.t)) / (np.sqrt(self.v[k] / (1 - b2 ** self.t)) + eps)
        return float(((out - y) ** 2).mean())


class Learned:
    """A trained MLP + the input normalisation; call .predict(features) -> (M, F) speed deltas."""

    def __init__(self, kind, net, mu, sd):
        self.kind, self.net, self.mu, self.sd = kind, net, mu, sd

    def predict(self, X):
        return self.net.forward(((X - self.mu) / self.sd).astype(np.float32))

    def save(self, path):
        np.savez(path, kind=self.kind, mu=self.mu, sd=self.sd, **{f"W{i}": w for i, w in enumerate(self.net.W)},
                 **{f"b{i}": b for i, b in enumerate(self.net.b)})

    @staticmethod
    def load(path):
        z = np.load(path)
        net = MLP(z["W0"].shape[0])
        net.W = [z[f"W{i}"] for i in range(3)]
        net.b = [z[f"b{i}"] for i in range(3)]
        return Learned(str(z["kind"]), net, z["mu"], z["sd"])


def fit(kind, X, Y, seed=0, epochs=15, batch=512, verbose=False):
    mu, sd = X.mean(0), X.std(0) + 1e-6
    net = MLP(X.shape[1], seed=seed)
    rng = np.random.default_rng(seed)
    Xn = ((X - mu) / sd).astype(np.float32)
    for ep in range(epochs):
        perm = rng.permutation(len(X))
        loss = [net.step(Xn[perm[i:i + batch]], Y[perm[i:i + batch]]) for i in range(0, len(X), batch)]
        if verbose:
            print(f"    epoch {ep + 1:2d}  train mse {np.mean(loss):.4f}")
    return Learned(kind, net, mu, sd)


# ---------------------------------------------------------------- open-loop metric
def l2_at(pred, Y, secs):
    """Position error [m] after `secs` seconds. Positions are cumulative sums of speed deltas times dt
    (the current-speed term is common to prediction and truth and cancels)."""
    k = int(round(secs / C.DT))
    return np.abs(np.cumsum(pred, 1)[:, k - 1] - np.cumsum(Y, 1)[:, k - 1]) * C.DT


def l2_summary(pred, Y, brake):
    """Average of L2@1s, @2s, @3s: over all windows and over the 'lead is about to brake' slice."""
    # TODO (Bước 3): hãy tự cài hàm này. Gợi ý:
    #   Gọi l2_at(pred, Y, s) cho s = 1, 2, 3 và lấy trung bình ba giá trị cho mỗi cửa sổ. Trả dict: all
    #   (trung bình mọi cửa sổ), brake_slice (trung bình trên cửa sổ có brake = True, nan nếu rỗng),
    #   slice_share (tỷ lệ cửa sổ có brake = True).
    l2 = (l2_at(pred, Y, 1) + l2_at(pred, Y, 2) + l2_at(pred, Y, 3)) / 3.0
    brake = np.asarray(brake, bool)
    all_mean = float(np.mean(l2))
    brake_slice_mean = float(np.mean(l2[brake])) if np.any(brake) else float("nan")
    slice_share = float(np.mean(brake)) if len(brake) > 0 else 0.0
    return {"all": all_mean, "brake_slice": brake_slice_mean, "slice_share": slice_share}
