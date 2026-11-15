import datetime
import os
from itertools import combinations
from typing import Callable

from google.cloud import bigquery

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "dev-plataforma-geral")
SILVER_TABLE = f"{PROJECT_ID}.po_silver.stg_football_penalties_clean"
GOLD_MATRIX_TABLE = f"{PROJECT_ID}.po_gold.mart_payoff_matrices_3x3"
LOCATION = "southamerica-east1"

GOLD_LABELS = {
    "datacloud": "antigravity",
    "domain": "po",
    "layer": "gold",
}

ZONES = ["L", "C", "R"]


def solve_linear_system_4x4(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Solve a 4x4 dense linear system via Gauss-Jordan elimination with partial pivoting."""
    M = [row[:] + [b[idx]] for idx, row in enumerate(A)]
    for col in range(4):
        piv = max(range(col, 4), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        div = M[col][col]
        for j in range(col, 5):
            M[col][j] /= div
        for r in range(4):
            if r != col and abs(M[r][col]) > 1e-15:
                fac = M[r][col]
                for j in range(col, 5):
                    M[r][j] -= fac * M[col][j]
    return [M[i][4] for i in range(4)]


def _solve_zero_sum_lp(
    payoff_rows: list[list[float]],
    maximize: bool,
) -> tuple[list[float], float]:
    """Solve a 3x3 zero-sum game LP by enumerating simplex vertices."""
    ineqs = [row[:] + [-1.0] for row in payoff_rows]
    for idx in range(3):
        vec = [0.0, 0.0, 0.0, 0.0]
        vec[idx] = 1.0
        ineqs.append(vec)
    eq = [1.0, 1.0, 1.0, 0.0]
    best_val = -1e9 if maximize else 1e9
    best_probs = [1.0 / 3.0] * 3

    for comb in combinations(range(6), 3):
        sol = solve_linear_system_4x4([eq] + [ineqs[k] for k in comb], [1.0, 0.0, 0.0, 0.0])
        if sol is None:
            continue
        probs, val = sol[:3], sol[3]
        if any(x < -1e-9 for x in probs):
            continue
        expected = [sum(probs[k] * row[k] for k in range(3)) for row in payoff_rows]
        feasible = (
            all(e >= val - 1e-9 for e in expected)
            if maximize
            else all(e <= val + 1e-9 for e in expected)
        )
        if feasible and ((maximize and val > best_val) or (not maximize and val < best_val)):
            best_val = val
            clipped = [max(0.0, x) for x in probs]
            total = sum(clipped)
            best_probs = [x / total for x in clipped]
    return best_probs, float(best_val)


def solve_primal_gk(A: list[list[float]]) -> tuple[list[float], float]:
    """Solve the goalkeeper's maximin primal LP over a 3x3 payoff matrix."""
    payoff_t = [[A[i][j] for i in range(3)] for j in range(3)]
    return _solve_zero_sum_lp(payoff_t, maximize=True)


def solve_dual_shooter(A: list[list[float]]) -> tuple[list[float], float]:
    """Solve the shooter's minimax dual LP over a 3x3 payoff matrix."""
    return _solve_zero_sum_lp(A, maximize=False)


def compute_smoothed_payoff_matrix(
    sub_rows: list[dict],
    alpha: float = 0.0,
    prior_matrix: list[list[float]] | None = None,
) -> tuple[list[list[float]], dict[str, tuple[int, int, float, float]]]:
    """Build the 3x3 GK non-goal payoff matrix with optional Empirical Bayes shrinkage."""
    matrix = [[0.0] * 3 for _ in range(3)]
    cell_stats: dict[str, tuple[int, int, float, float]] = {}
    for i, gz in enumerate(ZONES):
        for j, sz in enumerate(ZONES):
            cell = [r for r in sub_rows if r["gk_zone"] == gz and r["shot_zone"] == sz]
            tot = len(cell)
            ms = sum(1 for r in cell if r["outcome"] == "missed")
            raw_rate = ms / tot if tot else 0.0
            prior = prior_matrix[i][j] if prior_matrix is not None else raw_rate
            denom = tot + alpha
            smoothed = (ms + alpha * prior) / denom if denom > 0 else 0.0
            matrix[i][j] = smoothed
            cell_stats[f"{gz}_{sz}"] = (tot, ms, raw_rate, smoothed)
    return matrix, cell_stats


def get_scenario_definitions() -> list[tuple[int, str, str, Callable[[dict], bool], float]]:
    """Return the six canonical penalty-kick scenarios ordered for modeling."""
    return [
        (1, "C1_GLOBAL", "1. Global (Todas as Cobrancas Espaciais)", lambda r: True, 0.0),
        (
            2,
            "C2_RIGHT_FOOT",
            "2. Batedor Destro (Pe Direito)",
            lambda r: r["body_part_clean"] == "right-foot",
            0.0,
        ),
        (
            3,
            "C3_LEFT_FOOT",
            "3. Batedor Canhoto (Pe Esquerdo - EB alpha=2)",
            lambda r: r["body_part_clean"] == "left-foot",
            2.0,
        ),
        (
            4,
            "C4_CLUTCH",
            "4. Pressao / Clutch (2T min>=75 ou diff<=1)",
            lambda r: bool(r["is_clutch_situational"]),
            0.0,
        ),
        (5, "C5_FORWARDS", "5. Atacantes (Posicao F)", lambda r: r["position"] == "F", 0.0),
        (
            6,
            "C6_MID_DEF",
            "6. Meio-Campistas e Defensores (M/D)",
            lambda r: r["position"] != "F",
            0.0,
        ),
    ]


def solve_all_scenarios(rows: list[dict]) -> list[dict]:
    """Compute payoff matrices, empirical distributions, and Nash equilibria for all 6 scenarios."""
    global_A: list[list[float]] | None = None
    records: list[dict] = []
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for order_idx, code, label, pred, alpha in get_scenario_definitions():
        sub = [r for r in rows if pred(r)]
        n_total = len(sub)
        n_missed = sum(1 for r in sub if r["outcome"] == "missed")
        emp_non_goal_rate = n_missed / n_total if n_total else 0.0

        emp_p = [sum(1 for r in sub if r["gk_zone"] == z) / n_total for z in ZONES]
        emp_q = [sum(1 for r in sub if r["shot_zone"] == z) / n_total for z in ZONES]

        A, cell_stats = compute_smoothed_payoff_matrix(sub, alpha=alpha, prior_matrix=global_A)
        if code == "C1_GLOBAL":
            global_A = [row[:] for row in A]

        p_star, v_star = solve_primal_gk(A)
        q_star, w_star = solve_dual_shooter(A)
        duality_gap = abs(v_star - w_star)
        if duality_gap >= 1e-9:
            raise ValueError(f"Duality gap acima do limite em {code}: {duality_gap}")

        rec: dict = {
            "scenario_order": order_idx,
            "scenario_code": code,
            "scenario_label": label,
            "sample_size": n_total,
            "total_missed": n_missed,
            "empirical_non_goal_rate": float(round(emp_non_goal_rate, 6)),
            "eb_alpha": float(alpha),
            "gk_emp_L": float(round(emp_p[0], 6)),
            "gk_emp_C": float(round(emp_p[1], 6)),
            "gk_emp_R": float(round(emp_p[2], 6)),
            "shooter_emp_L": float(round(emp_q[0], 6)),
            "shooter_emp_C": float(round(emp_q[1], 6)),
            "shooter_emp_R": float(round(emp_q[2], 6)),
            "gk_nash_L": float(round(p_star[0], 6)),
            "gk_nash_C": float(round(p_star[1], 6)),
            "gk_nash_R": float(round(p_star[2], 6)),
            "shooter_nash_L": float(round(q_star[0], 6)),
            "shooter_nash_C": float(round(q_star[1], 6)),
            "shooter_nash_R": float(round(q_star[2], 6)),
            "game_value_v_primal": float(round(v_star, 6)),
            "game_value_w_dual": float(round(w_star, 6)),
            "duality_gap": float(duality_gap),
            "_gold_loaded_at": now_iso,
        }
        for key, (tot, ms, raw_r, sm_r) in cell_stats.items():
            rec[f"n_{key}"] = tot
            rec[f"miss_{key}"] = ms
            rec[f"raw_a_{key}"] = float(round(raw_r, 6))
            rec[f"a_{key}"] = float(round(sm_r, 6))

        records.append(rec)
    return records


def main() -> None:
    """Load spatial penalties from Silver, solve 6 scenarios, and publish to Gold."""
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    job_config = bigquery.QueryJobConfig(labels=GOLD_LABELS)

    sql = f"""
    SELECT
      gk_zone,
      shot_zone,
      outcome,
      detailed_outcome,
      body_part_clean,
      is_clutch_situational,
      position
    FROM `{SILVER_TABLE}`
    WHERE has_spatial_coords = TRUE
    """
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    records = solve_all_scenarios(rows)

    for rec in records:
        p_pct = [round(rec[f"gk_nash_{z}"] * 100, 1) for z in ZONES]
        q_pct = [round(rec[f"shooter_nash_{z}"] * 100, 1) for z in ZONES]
        print(
            f"[{rec['scenario_code']}] n={rec['sample_size']:4d} | "
            f"p*={p_pct}% | q*={q_pct}% | "
            f"v*={rec['game_value_v_primal']*100:.2f}% | "
            f"emp={rec['empirical_non_goal_rate']*100:.2f}% | "
            f"gap={rec['duality_gap']:.2e}"
        )

    load_cfg = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
        labels=GOLD_LABELS,
    )
    load_job = client.load_table_from_json(
        records, GOLD_MATRIX_TABLE, location=LOCATION, job_config=load_cfg
    )
    load_job.result()

    table = client.get_table(GOLD_MATRIX_TABLE)
    table.labels = GOLD_LABELS
    table.description = (
        "Camada Gold (E3-T01): 6 matrizes de payoff 3x3 e equilibrios de Nash "
        "Primal-Dual de Von Neumann resolvidos por Programacao Linear"
    )
    client.update_table(table, ["labels", "description"])
    print(f"[Gold E3-T01] Tabela gravada e rotulada: {GOLD_MATRIX_TABLE} ({len(records)} cenarios)")


if __name__ == "__main__":
    main()
