"""Step 1: log replay. Write a timestamped log, replay it message by message, compare two replays with a tolerance,
and see what 'as fast as possible' replay hides compared with real-time replay.

Log format (JSON Lines, one message per line, sorted by time inside a segment):
    {"seg": 12, "t_ns": 500000000, "topic": "/can",        "v_ego": 7.31}
    {"seg": 12, "t_ns": 520000000, "topic": "/perception", "gap": 11.9, "v_lead": 6.8}
The perception message arrives 20 ms after the CAN message of the same tick, like two sensors with their own clock.
"""
import json

import numpy as np

from . import config as C

TICK_NS = int(C.DT * 1e9)
PERCEPTION_DELAY_NS = 20_000_000
DEADLINE_NS = TICK_NS                    # a command must be ready before the next frame arrives


# ---------------------------------------------------------------- write / read
def write_log(path, logs, idx):
    """Write the trajectories `idx` as one log file (segment id = position inside idx)."""
    with open(path, "w") as f:
        for s, i in enumerate(idx):
            for k in range(logs.n[i]):
                t = k * TICK_NS
                f.write(json.dumps({"seg": s, "t_ns": t, "topic": "/can", "v_ego": round(float(logs.v_ego[i, k]), 4)}) + "\n")
                f.write(json.dumps({"seg": s, "t_ns": t + PERCEPTION_DELAY_NS, "topic": "/perception",
                                    "gap": round(float(logs.gap[i, k]), 4), "v_lead": round(float(logs.v_lead[i, k]), 4)}) + "\n")


def read_log(path):
    """-> {seg: [messages sorted by t_ns]}"""
    segs = {}
    with open(path) as f:
        for line in f:
            m = json.loads(line)
            segs.setdefault(m["seg"], []).append(m)
    for msgs in segs.values():
        msgs.sort(key=lambda m: m["t_ns"])
    return segs


# ---------------------------------------------------------------- planners as message streams
class IDMStream:
    """IDM as a stream consumer: remembers the latest ego speed, answers every /perception message with a command."""

    def __init__(self, T=1.2, v0=15.0, s0=2.0, a=1.5, b=2.0, dtype=np.float64, variant="plain", aeb_ttc=None):
        self.p = dict(T=T, v0=v0, s0=s0, a=a, b=b)
        self.dtype, self.variant, self.aeb_ttc = dtype, variant, aeb_ttc     # aeb_ttc: emergency-brake rule (a real behaviour change)
        self.v = 0.0

    def on_msg(self, m):
        if m["topic"] == "/can":
            self.v = m["v_ego"]
            return None
        cmd = self._cmd(self.v, m["gap"], m["v_lead"])
        closing = self.v - m["v_lead"]
        if self.aeb_ttc and closing > 1e-3 and m["gap"] / closing < self.aeb_ttc:
            cmd = min(cmd, -6.0)                                  # emergency braking
        return cmd

    def _cmd(self, v, gap, v_lead):
        d, p = self.dtype, self.p
        v, gap, vl = d(v), d(max(gap, 0.1)), d(v_lead)
        if self.variant == "plain":
            s_star = p["s0"] + max(0.0, v * p["T"] + v * (v - vl) / (2 * np.sqrt(p["a"] * p["b"])))
            return float(p["a"] * (1 - (v / p["v0"]) ** 4 - (s_star / gap) ** 2))
        # 'refactored': same maths, different order of operations (what a harmless-looking code cleanup does)
        inv_gap = d(1.0) / gap
        s_star = d(p["s0"]) + max(d(0.0), v * d(p["T"]) + (v * (v - vl)) * d(0.5 / np.sqrt(p["a"] * p["b"])))
        return float(d(p["a"]) - d(p["a"]) * (v / d(p["v0"])) ** 4 - d(p["a"]) * (s_star * inv_gap) ** 2)


# ---------------------------------------------------------------- replay
def replay(segs, make_stream, mode="fastest", cost_seed=0, spike_prob=0.02, base_ms=6.0, spike_ms=140.0):
    """Feed every segment to a fresh stream planner, in timestamp order. Returns (commands (n_seg, T), stats).

    mode='fastest' : the next message is sent as soon as the previous one is processed; deadlines do not exist,
                     so a slow frame is invisible.
    mode='realtime': messages are delivered at their logged times. A /perception message that arrives while the planner
                     is still busy is dropped, one that is answered after the next frame arrived is late; in both cases
                     the previous command is held. Processing cost is simulated: base_ms, with spike_prob of spike_ms.
    """
    n_seg = len(segs)
    T = max(sum(1 for m in v if m["topic"] == "/perception") for v in segs.values())
    out = np.full((n_seg, T), np.nan)
    rng = np.random.default_rng(cost_seed)
    dropped = late = frames = 0
    for s in sorted(segs):
        stream = make_stream()
        busy_until, held, k = -1, 0.0, 0
        for m in segs[s]:
            if m["topic"] == "/can":
                stream.on_msg(m)
                continue
            frames += 1
            cmd = stream.on_msg(m)
            if mode == "realtime":
                cost = (spike_ms if rng.random() < spike_prob else base_ms) * 1e6
                if m["t_ns"] < busy_until:
                    dropped += 1
                    cmd = held
                elif cost > DEADLINE_NS:
                    late += 1
                    busy_until = m["t_ns"] + cost
                    cmd = held
                else:
                    busy_until = m["t_ns"] + cost
            held = cmd
            out[s, k] = cmd
            k += 1
    return out, {"frames": frames, "dropped": dropped, "late": late, "mode": mode}


# ---------------------------------------------------------------- compare
def compare_with_tol(golden, new, atol=1e-3, rtol=1e-3):
    """Segment-by-segment comparison. A segment 'differs' if any command is outside atol + rtol * |golden|.
    Also reports how many segments are not bit-identical, to show why exact equality is the wrong test."""
    # TODO (Bước 1): hãy tự cài hàm này. Gợi ý:
    #   golden và new có shape (n_seg, T), NaN ở phần đệm. Một đoạn 'lệch' nếu có lệnh nào vượt atol + rtol
    #   * |golden|. Hai NaN ở cùng vị trí coi là bằng nhau. Trả dict có đúng các khoá: segments,
    #   differ_beyond_tol, not_bit_identical (số đoạn không giống TỪNG BIT), max_abs_diff, atol, rtol,
    #   differing_segments (tối đa 20 chỉ số đầu, dạng list).
    golden = np.asarray(golden)
    new = np.asarray(new)
    n_seg = golden.shape[0]
    # 1. Mặt nạ xác định vị trí NaN
    nan_golden = np.isnan(golden)
    nan_new = np.isnan(new)
    # 2. Hai NaN ở cùng vị trí coi là bằng nhau; lệch nếu một bên NaN một bên không
    nan_mismatch = (nan_golden != nan_new)
    # 3. So sánh chính xác từng bit (Bit-identical)
    # np.array_equal với equal_nan=True kiểm tra NaN == NaN,
    # nhưng ở mức element-wise ta dùng: (golden == new) HOẶC cả hai đều là NaN.
    # Lưu ý: float bit-identical với NaN thông thường thỏa mãn khi cả hai đều là NaN.
    bit_equal_mask = (golden == new) | (nan_golden & nan_new)
    # Một segment không bit-identical nếu có bất kỳ phần tử nào khác nhau
    not_bit_identical_seg = ~np.all(bit_equal_mask, axis=1)
    not_bit_identical = int(np.sum(not_bit_identical_seg))
    # 4. So sánh theo dung sai (tolerance)
    # Chỉ tính độ lệch trên những vị trí mà cả hai đều là số thực (valid)
    valid_mask = ~nan_golden & ~nan_new
    abs_diff = np.zeros_like(golden, dtype=float)
    abs_diff[valid_mask] = np.abs(golden[valid_mask] - new[valid_mask])

    tol = atol + rtol * np.abs(golden)
    # Một vị trí bị coi là vượt ngưỡng nếu:
    # - Một bên là NaN còn bên kia là số (nan_mismatch)
    # - HOẶC chênh lệch vượt quá sai số cho phép: |golden - new| > atol + rtol * |golden|
    exceed_tol = nan_mismatch | (valid_mask & (abs_diff > tol))
    # Segment bị lệch nếu có ít nhất 1 phần tử vượt ngưỡng
    seg_differs = np.any(exceed_tol, axis=1)
    differ_beyond_tol = int(np.sum(seg_differs))
    differing_segments = np.flatnonzero(seg_differs)[:20].tolist()
    # 5. Độ lệch tuyệt đối lớn nhất trên các phần tử hợp lệ
    # Nếu không có phần tử số nào (hoặc toàn NaN lệch nhau), fallback về NaN hoặc giá trị hợp lý
    if np.any(valid_mask):
        max_abs_diff = float(np.max(abs_diff[valid_mask]))
    else:
        max_abs_diff = 0.0

    return {
        "segments": int(n_seg),
        "differ_beyond_tol": differ_beyond_tol,
        "not_bit_identical": not_bit_identical,
        "max_abs_diff": max_abs_diff,
        "atol": float(atol),
        "rtol": float(rtol),
        "differing_segments": differing_segments,
    }
def summation_order_demo(n=1_000_000, seed=0):
    """Why two replays are never bit-identical: float addition is not associative."""
    x = np.random.default_rng(seed).standard_normal(n).astype(np.float32)
    fwd, rev = np.float32(0), np.float32(0)
    for v in x[:50_000]:
        fwd += v
    for v in x[:50_000][::-1]:
        rev += v
    return {"(0.1+0.2)+0.3": (0.1 + 0.2) + 0.3, "0.1+(0.2+0.3)": 0.1 + (0.2 + 0.3),
            "float32_sum_forward_50k": float(fwd), "float32_sum_reversed_50k": float(rev),
            "float32_sum_numpy_pairwise_50k": float(x[:50_000].sum()),
            "relative_difference_forward_vs_reversed": float(abs(fwd - rev) / max(abs(fwd), 1e-12))}
