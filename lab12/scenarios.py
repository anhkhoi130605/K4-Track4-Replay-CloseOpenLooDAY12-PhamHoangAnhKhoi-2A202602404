"""Step 2: scenarios. Metrics (TTC, required deceleration), mining braking events from the logs, and the physics
frontier that separates 'no planner could have avoided this' from 'this planner failed'."""
import numpy as np

from . import config as C


def ttc(gap, closing):
    """Time to collision [s] = gap / closing speed (inf when the gap is not closing)."""
    # TODO (Bước 2): hãy tự cài hàm này. Gợi ý:
    #   TTC = gap / closing khi closing > 0, ngược lại inf. Phải chạy được trên mảng numpy (dùng np.where,
    #   tránh chia cho 0).
    closing = np.asarray(closing)
    gap = np.asarray(gap)
    TTC = np.where(closing > 0, gap / closing, np.inf)
    return TTC


def required_decel(gap, closing):
    """Deceleration [m/s^2] needed to remove the closing speed exactly at contact: closing^2 / (2 gap)."""
    # TODO (Bước 2): hãy tự cài hàm này. Gợi ý:
    #   closing^2 / (2 * gap) khi closing > 0, ngược lại 0. Ví dụ của slide: gap 12 m, closing 5 m/s -> 1,04
    #   m/s^2.
    closing = np.asarray(closing)
    gap = np.asarray(gap)
    required = np.where(closing > 0, closing**2 / (2 * gap), 0)
    return required


def unavoidable(gaps, dvs, t_react=0.0, b_max=C.B_MAX):
    """Boolean grid (len(dvs), len(gaps)): True where NO planner can avoid contact, even braking at b_max after the
    reaction delay: gap < dv * t_react + dv^2 / (2 b_max)  (lead keeps its speed)."""
    # TODO (Bước 2): hãy tự cài hàm này. Gợi ý:
    #   Hãy tự suy ra biên. Trong t_react xe vẫn giữ tốc độ nên khoảng cách co lại dv * t_react. Sau đó
    #   phanh b_max cần dv^2 / (2 * b_max) để triệt tiêu tốc độ tiến gần. Bất khả thi khi gap nhỏ hơn tổng
    #   hai đoạn đó. Dùng np.meshgrid(gaps, dvs) để kết quả có shape (len(dvs), len(gaps)). Với dv = 0 phải
    #   luôn tránh được.
    # Tạo lưới 2D với shape (len(dvs), len(gaps))
    G, DV = np.meshgrid(gaps, dvs)

    # Khoảng cách tối thiểu cần có để dừng trước khi va chạm:
    # d_stop = dv * t_react + dv^2 / (2 * b_max)
    d_stop = DV * t_react + (DV ** 2) / (2.0 * b_max)

    # Bất khả thi khi gap < d_stop VÀ dv > 0 (với dv = 0 luôn tránh được)
    return (G < d_stop) & (DV > 0)


def mine_braking(logs, threshold=C.BRAKE_THRESHOLD, min_steps=5):
    """Find trajectories where the lead brakes: smoothed deceleration below `threshold` for at least `min_steps`
    consecutive steps (0.5 s). Returns a list of event dicts (one per trajectory, first event only)."""
    # TODO (Bước 2): hãy tự cài hàm này. Gợi ý:
    #   Với mỗi quỹ đạo i: a = logs.a_lead[i, :logs.n[i]] (đã làm mượt; KHÔNG dùng acc_lead_raw). Tìm lần
    #   ĐẦU TIÊN có đủ min_steps bước liên tiếp a < threshold. onset_step = bước bắt đầu chuỗi đó. Mỗi quỹ
    #   đạo tối đa 1 sự kiện. Trả list dict có đúng các khoá: traj, onset_step, peak_decel (a nhỏ nhất trong
    #   chuỗi), gap_m (logs.gap[i, onset]), closing_m_s (logs.v_ego[i, onset] - logs.v_lead_s[i, onset]),
    #   ego_speed (logs.v_ego[i, onset]).
    events = []
    n_trajs = len(logs.n)

    for i in range(n_trajs):
        T = int(logs.n[i])
        if T < min_steps:
            continue

        a = logs.a_lead[i, :T]
        is_braking = a < threshold

        # Tìm chuỗi True liên tiếp có độ dài tối thiểu min_steps
        count = 0
        found = False
        onset_idx = -1

        for t in range(T):
            if is_braking[t]:
                count += 1
                if count == min_steps:
                    onset_idx = t - min_steps + 1
                    found = True
                    break
            else:
                count = 0

        if not found:
            continue

        # Sau khi tìm được onset, xác định toàn bộ khoảng phanh liên tiếp đó để lấy peak_decel
        end_idx = onset_idx + min_steps
        while end_idx < T and is_braking[end_idx]:
            end_idx += 1

        # Gia tốc nhỏ nhất trong chuỗi phanh liên tiếp đó (âm sâu nhất)
        peak_decel = float(np.min(a[onset_idx:end_idx]))

        onset = onset_idx
        v_ego_val = float(logs.v_ego[i, onset])
        v_lead_val = float(logs.v_lead_s[i, onset])

        event = {
            "traj": int(i),
            "onset_step": int(onset),
            "peak_decel": peak_decel,
            "gap_m": float(logs.gap[i, onset]),
            "closing_m_s": float(v_ego_val - v_lead_val),
            "ego_speed": v_ego_val,
        }
        events.append(event)

    return events


def human_brake_limit(logs, q=0.1):
    """Hardest braking [m/s^2, positive number] that the logged human followers ever applied (the q-th percentile of
    their acceleration, from the speed differences). Learned planners cannot have seen anything harder."""
    a = np.diff(logs.v_ego, axis=1) / C.DT
    return float(-np.nanpercentile(a, q))


def grid_from_logs(logs, v_ego, n_gap=60, n_dv=45):
    """Scenario grid. Gap limits come from what the logs contain (p2 .. p98 of the logged gaps). Closing speed runs
    from 0 to v_ego: dv = v_ego means the cutter is standing still, the most extreme case (never faster than that,
    otherwise the cutter would drive backwards)."""
    g_lo, g_hi = np.nanpercentile(logs.gap, [2, 98])
    return np.linspace(g_lo, g_hi, n_gap), np.linspace(0.0, v_ego, n_dv)
