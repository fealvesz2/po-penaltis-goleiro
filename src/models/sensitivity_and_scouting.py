import datetime
import json
import os
from pathlib import Path
from typing import Any

from google.cloud import bigquery
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

try:
    from src.models import lp_nash_solver as lns
except ImportError:  # pragma: no cover - direct script execution fallback
    import lp_nash_solver as lns

PROJECT_ID = lns.PROJECT_ID
SILVER_TABLE = lns.SILVER_TABLE
GOLD_MATRIX_TABLE = lns.GOLD_MATRIX_TABLE
GOLD_SENSITIVITY_TABLE = f"{PROJECT_ID}.po_gold.mart_sensitivity_theta"
GOLD_SCOUTING_TABLE = f"{PROJECT_ID}.po_gold.mart_shooter_scouting"
LOCATION = lns.LOCATION
GOLD_LABELS = lns.GOLD_LABELS
ZONES = lns.ZONES

THETA_GRID = [round(i * 0.1, 1) for i in range(11)]
SCOUTING_EB_ALPHA = 5.0
MIN_SPATIAL_KICKS_SCOUTING = 10
TOP_SCOUTING_COUNT = 10
FEATURED_GLOVE_STARS = [
    "Harry Kane",
    "Kylian Mbappé",
    "Mohamed Salah",
    "Bruno Fernandes",
    "Erling Haaland",
    "Cole Palmer",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
JSON_EXPORT_PATH = REPO_ROOT / "data" / "processed" / "po_penalties_mart.json"
EXCEL_VALIDATION_PATH = REPO_ROOT / "docs" / "validacao_excel_solver.xlsx"


def compute_expected_payoff(
    p: list[float], A: list[list[float]], q: list[float]
) -> float:
    """Compute bilinear expected payoff p^T A q for 3x3 mixed strategies."""
    return float(
        sum(p[i] * A[i][j] * q[j] for i in range(3) for j in range(3))
    )


def compute_empirical_column_returns(
    A: list[list[float]], q_emp: list[float]
) -> list[float]:
    """Compute vector (A * q_emp) representing expected non-goal payoff per GK zone."""
    return [
        float(sum(A[i][j] * q_emp[j] for j in range(3)))
        for i in range(3)
    ]


def build_theta_payoff_matrix(
    A: list[list[float]], q_emp: list[float], theta: float
) -> list[list[float]]:
    """Build theta-adjusted 3x3 payoff matrix A(theta) = theta*(A*q_emp) + (1-theta)*A."""
    if not (0.0 <= theta <= 1.0):
        raise ValueError(f"theta deve estar em [0, 1], recebido: {theta}")
    emp_returns = compute_empirical_column_returns(A, q_emp)
    return [
        [
            float(theta * emp_returns[i] + (1.0 - theta) * A[i][j])
            for j in range(3)
        ]
        for i in range(3)
    ]


def _pick_best_response_zone(values: list[float]) -> str:
    """Return goalkeeper zone maximizing expected payoff against empirical habits."""
    best_idx = max(range(3), key=lambda idx: values[idx])
    return ZONES[best_idx]


def _format_corner_pt(zone: str) -> str:
    """Map technical zone code to concise Portuguese locker-room cue."""
    mapping = {
        "L": "Esquerda (batedor)",
        "C": "Centro (ficar no meio)",
        "R": "Direita (batedor)",
    }
    return mapping[zone]


def solve_sensitivity_for_scenario(
    scenario_code: str,
    scenario_order: int,
    scenario_label: str,
    A: list[list[float]],
    q_emp: list[float],
    theta_grid: list[float] | None = None,
    loaded_at_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Evaluate Primal/Dual optimal solutions across theta in [0, 1] for one scenario."""
    grid = theta_grid if theta_grid is not None else THETA_GRID
    now_iso = loaded_at_iso or datetime.datetime.now(datetime.timezone.utc).isoformat()
    v_nash = lns.solve_primal_gk(A)[1]
    emp_col_returns = compute_empirical_column_returns(A, q_emp)
    best_response_ev = max(emp_col_returns)

    points: list[dict[str, Any]] = []
    for theta in grid:
        A_theta = build_theta_payoff_matrix(A, q_emp, theta)
        p_theta, v_theta = lns.solve_primal_gk(A_theta)
        q_tilde, w_theta = lns.solve_dual_shooter(A_theta)
        gap = abs(v_theta - w_theta)
        if gap >= 1e-9:
            raise ValueError(
                f"Duality gap acima do limite em {scenario_code} theta={theta}: {gap}"
            )

        q_composite = [
            float(theta * q_emp[j] + (1.0 - theta) * q_tilde[j])
            for j in range(3)
        ]
        ev_vs_emp = compute_expected_payoff(p_theta, A, q_emp)
        worst_case_floor = min(
            sum(p_theta[i] * A[i][j] for i in range(3)) for j in range(3)
        )

        points.append(
            {
                "scenario_order": scenario_order,
                "scenario_code": scenario_code,
                "scenario_label": scenario_label,
                "theta": float(round(theta, 4)),
                "gk_opt_L": float(round(p_theta[0], 6)),
                "gk_opt_C": float(round(p_theta[1], 6)),
                "gk_opt_R": float(round(p_theta[2], 6)),
                "shooter_tilde_L": float(round(q_tilde[0], 6)),
                "shooter_tilde_C": float(round(q_tilde[1], 6)),
                "shooter_tilde_R": float(round(q_tilde[2], 6)),
                "shooter_eff_L": float(round(q_composite[0], 6)),
                "shooter_eff_C": float(round(q_composite[1], 6)),
                "shooter_eff_R": float(round(q_composite[2], 6)),
                "game_value_v_primal": float(round(v_theta, 6)),
                "game_value_w_dual": float(round(w_theta, 6)),
                "duality_gap": float(gap),
                "expected_vs_empirical_rate": float(round(ev_vs_emp, 6)),
                "worst_case_floor_rate": float(round(worst_case_floor, 6)),
                "uplift_vs_nash": float(round(v_theta - v_nash, 6)),
                "max_empirical_best_response": float(round(best_response_ev, 6)),
                "_gold_loaded_at": now_iso,
            }
        )
    return points


def _extract_matrix_and_q_emp(scenario_record: dict[str, Any]) -> tuple[list[list[float]], list[float]]:
    """Reconstruct 3x3 smoothed matrix A and empirical q vector from a scenario record."""
    A = [
        [float(scenario_record[f"a_{gz}_{sz}"]) for sz in ZONES]
        for gz in ZONES
    ]
    q_emp = [float(scenario_record[f"shooter_emp_{sz}"]) for sz in ZONES]
    return A, q_emp


def solve_sensitivity_all_scenarios(
    scenario_records: list[dict[str, Any]],
    theta_grid: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Compute parametric sensitivity curves for all 6 scenarios."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    all_points: list[dict[str, Any]] = []
    for rec in sorted(scenario_records, key=lambda r: r["scenario_order"]):
        A, q_emp = _extract_matrix_and_q_emp(rec)
        all_points.extend(
            solve_sensitivity_for_scenario(
                scenario_code=rec["scenario_code"],
                scenario_order=int(rec["scenario_order"]),
                scenario_label=rec["scenario_label"],
                A=A,
                q_emp=q_emp,
                theta_grid=theta_grid,
                loaded_at_iso=now_iso,
            )
        )
    return all_points


def _select_top_scouting_players(
    all_silver_rows: list[dict[str, Any]],
) -> list[str]:
    """Select the 6 featured stars plus top 4 volume shooters with >= 10 spatial kicks."""
    stats_by_player: dict[str, dict[str, int]] = {}
    for row in all_silver_rows:
        player = row.get("player")
        if not player:
            continue
        bucket = stats_by_player.setdefault(player, {"total": 0, "spatial": 0})
        bucket["total"] += 1
        if row.get("has_spatial_coords"):
            bucket["spatial"] += 1

    featured = [
        p
        for p in FEATURED_GLOVE_STARS
        if stats_by_player.get(p, {}).get("spatial", 0) >= MIN_SPATIAL_KICKS_SCOUTING
    ]
    remaining = [
        p
        for p, st in stats_by_player.items()
        if p not in featured and st["spatial"] >= MIN_SPATIAL_KICKS_SCOUTING
    ]
    remaining.sort(
        key=lambda p: (
            -stats_by_player[p]["total"],
            -stats_by_player[p]["spatial"],
            p,
        )
    )
    selected = featured + remaining[: max(0, TOP_SCOUTING_COUNT - len(featured))]
    if len(selected) != TOP_SCOUTING_COUNT:
        raise ValueError(
            f"Esperado {TOP_SCOUTING_COUNT} batedores no scouting, obtido {len(selected)}"
        )
    return selected


def build_shooter_scouting_records(
    all_silver_rows: list[dict[str, Any]],
    scenario_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build 10 shooter scouting dossiers combining career stats and EB-Nash solutions."""
    matrix_by_code = {
        rec["scenario_code"]: _extract_matrix_and_q_emp(rec)[0]
        for rec in scenario_records
    }
    selected_players = _select_top_scouting_players(all_silver_rows)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dossiers: list[dict[str, Any]] = []

    for rank_idx, player in enumerate(selected_players, start=1):
        career_rows = [r for r in all_silver_rows if r.get("player") == player]
        spatial_rows = [r for r in career_rows if r.get("has_spatial_coords")]
        n_career = len(career_rows)
        n_career_missed = sum(1 for r in career_rows if r.get("outcome") == "missed")
        n_spatial = len(spatial_rows)
        n_spatial_missed = sum(1 for r in spatial_rows if r.get("outcome") == "missed")
        n_spatial_saved = sum(
            1 for r in spatial_rows if r.get("detailed_outcome") == "saved"
        )
        n_spatial_off_target = sum(
            1
            for r in spatial_rows
            if r.get("detailed_outcome") == "off_target_or_woodwork"
        )

        foot_counts: dict[str, int] = {}
        pos_counts: dict[str, int] = {}
        teams_set: set[str] = set()
        for r in spatial_rows:
            foot = r.get("body_part_clean") or "right-foot"
            foot_counts[foot] = foot_counts.get(foot, 0) + 1
            pos = r.get("position") or "F"
            pos_counts[pos] = pos_counts.get(pos, 0) + 1
        for r in career_rows:
            if r.get("team_shooting"):
                teams_set.add(str(r["team_shooting"]))

        dominant_foot = max(foot_counts, key=foot_counts.get)
        primary_position = max(pos_counts, key=pos_counts.get)
        prior_code = (
            "C3_LEFT_FOOT"
            if dominant_foot == "left-foot"
            else "C2_RIGHT_FOOT"
        )
        prior_A = matrix_by_code.get(prior_code, matrix_by_code["C1_GLOBAL"])

        shot_counts = {
            z: sum(1 for r in spatial_rows if r.get("shot_zone") == z) for z in ZONES
        }
        q_player = [shot_counts[z] / n_spatial for z in ZONES]

        corner_counts = {
            c: sum(1 for r in spatial_rows if r.get("tactical_corner") == c)
            for c in ("Natural", "Center", "Opposite")
        }

        A_player, _ = lns.compute_smoothed_payoff_matrix(
            spatial_rows, alpha=SCOUTING_EB_ALPHA, prior_matrix=prior_A
        )
        p_nash, v_nash = lns.solve_primal_gk(A_player)
        q_nash, w_nash = lns.solve_dual_shooter(A_player)
        duality_gap = abs(v_nash - w_nash)
        if duality_gap >= 1e-9:
            raise ValueError(f"Duality gap elevado para {player}: {duality_gap}")

        A_half = build_theta_payoff_matrix(A_player, q_player, 0.5)
        p_half, v_half = lns.solve_primal_gk(A_half)
        emp_returns = compute_empirical_column_returns(A_player, q_player)
        best_zone = _pick_best_response_zone(emp_returns)
        best_ev = max(emp_returns)

        teams_sorted = sorted(teams_set)
        favorite_zone = max(ZONES, key=lambda z: shot_counts[z])
        favorite_corner = max(corner_counts, key=corner_counts.get)

        rec: dict[str, Any] = {
            "scouting_rank": rank_idx,
            "player": player,
            "is_featured_glove_star": player in FEATURED_GLOVE_STARS,
            "dominant_foot": dominant_foot,
            "position": primary_position,
            "prior_scenario_code": prior_code,
            "eb_alpha": float(SCOUTING_EB_ALPHA),
            "teams_list": " | ".join(teams_sorted[:4]),
            "career_total_kicks": n_career,
            "career_missed": n_career_missed,
            "career_conversion_rate": float(
                round((n_career - n_career_missed) / n_career, 6)
            ),
            "spatial_kicks": n_spatial,
            "spatial_missed": n_spatial_missed,
            "spatial_saved": n_spatial_saved,
            "spatial_off_target": n_spatial_off_target,
            "spatial_non_goal_rate": float(round(n_spatial_missed / n_spatial, 6)),
            "shot_count_L": shot_counts["L"],
            "shot_count_C": shot_counts["C"],
            "shot_count_R": shot_counts["R"],
            "shot_pct_L": float(round(q_player[0], 6)),
            "shot_pct_C": float(round(q_player[1], 6)),
            "shot_pct_R": float(round(q_player[2], 6)),
            "corner_natural_count": corner_counts["Natural"],
            "corner_center_count": corner_counts["Center"],
            "corner_opposite_count": corner_counts["Opposite"],
            "corner_natural_pct": float(round(corner_counts["Natural"] / n_spatial, 6)),
            "corner_opposite_pct": float(round(corner_counts["Opposite"] / n_spatial, 6)),
            "favorite_shot_zone": favorite_zone,
            "favorite_tactical_corner": favorite_corner,
            "gk_nash_L": float(round(p_nash[0], 6)),
            "gk_nash_C": float(round(p_nash[1], 6)),
            "gk_nash_R": float(round(p_nash[2], 6)),
            "shooter_nash_L": float(round(q_nash[0], 6)),
            "shooter_nash_C": float(round(q_nash[1], 6)),
            "shooter_nash_R": float(round(q_nash[2], 6)),
            "game_value_v_nash": float(round(v_nash, 6)),
            "duality_gap": float(duality_gap),
            "gk_theta50_L": float(round(p_half[0], 6)),
            "gk_theta50_C": float(round(p_half[1], 6)),
            "gk_theta50_R": float(round(p_half[2], 6)),
            "game_value_v_theta50": float(round(v_half, 6)),
            "best_response_zone_theta1": best_zone,
            "best_response_zone_pt": _format_corner_pt(best_zone),
            "best_response_ev_theta1": float(round(best_ev, 6)),
            "_gold_loaded_at": now_iso,
        }
        for i, gz in enumerate(ZONES):
            for j, sz in enumerate(ZONES):
                rec[f"a_{gz}_{sz}"] = float(round(A_player[i][j], 6))
        dossiers.append(rec)

    return dossiers


def export_dashboard_json(
    scenario_records: list[dict[str, Any]],
    sensitivity_records: list[dict[str, Any]],
    scouting_records: list[dict[str, Any]],
    output_path: Path = JSON_EXPORT_PATH,
) -> Path:
    """Export unified Gold mart payload JSON for web dashboard and GitHub Pages."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "project_id": PROJECT_ID,
            "location": LOCATION,
            "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "zones": ZONES,
            "theta_grid": THETA_GRID,
            "scouting_eb_alpha": SCOUTING_EB_ALPHA,
            "tables": {
                "silver": SILVER_TABLE,
                "gold_matrices": GOLD_MATRIX_TABLE,
                "gold_sensitivity": GOLD_SENSITIVITY_TABLE,
                "gold_scouting": GOLD_SCOUTING_TABLE,
            },
        },
        "scenarios": scenario_records,
        "sensitivity_curves": sensitivity_records,
        "shooter_scouting": scouting_records,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return output_path


def _style_header_cell(cell: Any, text: str) -> None:
    """Apply consistent UFABC dark-green header styling to a worksheet cell."""
    cell.value = text
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="0E5A3C")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def generate_excel_validation_workbook(
    scenario_records: list[dict[str, Any]],
    sensitivity_records: list[dict[str, Any]],
    scouting_records: list[dict[str, Any]],
    output_path: Path = EXCEL_VALIDATION_PATH,
) -> Path:
    """Create multi-tab Excel workbook with live LP/SUMPRODUCT formulas ready for Solver."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # Sheet 1: Resumo Executivo & Instrucoes Solver
    ws_sum = wb.active
    ws_sum.title = "Resumo_Executivo"
    ws_sum["A1"] = "UFABC - Pesquisa Operacional Aplicada (Grupo 11)"
    ws_sum["A1"].font = Font(bold=True, size=14, color="0E5A3C")
    ws_sum["A2"] = (
        "Validacao LP Simplex + Sensibilidade Parametrica V*(theta) e Scouting Gold (E3-T02)"
    )
    ws_sum["A4"] = "Formula de Sensibilidade Linear (Solver-compatível):"
    ws_sum["A5"] = "A_ij(theta) = theta * (A * q_emp)_i + (1 - theta) * A_ij"
    ws_sum["A6"] = (
        "Como reproduzir no Excel Solver (C1_GLOBAL): aba 'Modelo_Solver_LP' -> Dados -> Solver -> "
        "Objetivo: Max J11 | Variaveis: J6:J8,J11 | Restricoes: J9=1 e G10:I10>=J11 (Simplex LP, nao-negativas)."
    )

    sum_headers = [
        "Ordem",
        "Codigo Cenario",
        "Descricao",
        "Amostra (n)",
        "Taxa Emp. Nao-Gol",
        "V*(0) Nash Puro",
        "V*(0.5) Hibrido",
        "V*(1.0) Best Resp.",
        "Gap Primal-Dual Max",
    ]
    for col_idx, header in enumerate(sum_headers, start=1):
        _style_header_cell(ws_sum.cell(row=8, column=col_idx), header)

    sens_by_code_theta = {
        (r["scenario_code"], round(float(r["theta"]), 1)): r for r in sensitivity_records
    }
    for row_offset, sc in enumerate(
        sorted(scenario_records, key=lambda r: r["scenario_order"]), start=9
    ):
        code = sc["scenario_code"]
        s0 = sens_by_code_theta[(code, 0.0)]
        s05 = sens_by_code_theta[(code, 0.5)]
        s10 = sens_by_code_theta[(code, 1.0)]
        max_gap = max(
            r["duality_gap"]
            for r in sensitivity_records
            if r["scenario_code"] == code
        )
        ws_sum.cell(row=row_offset, column=1, value=sc["scenario_order"])
        ws_sum.cell(row=row_offset, column=2, value=code)
        ws_sum.cell(row=row_offset, column=3, value=sc["scenario_label"])
        ws_sum.cell(row=row_offset, column=4, value=sc["sample_size"])
        c_emp = ws_sum.cell(row=row_offset, column=5, value=sc["empirical_non_goal_rate"])
        c_v0 = ws_sum.cell(row=row_offset, column=6, value=s0["game_value_v_primal"])
        c_v05 = ws_sum.cell(row=row_offset, column=7, value=s05["game_value_v_primal"])
        c_v1 = ws_sum.cell(row=row_offset, column=8, value=s10["game_value_v_primal"])
        c_gap = ws_sum.cell(row=row_offset, column=9, value=max_gap)
        for c in (c_emp, c_v0, c_v05, c_v1):
            c.number_format = "0.00%"
        c_gap.number_format = "0.00E+00"

    # Sheet 2: Modelo_Solver_LP (blocks for all 6 scenarios at theta=0.0 plus interactive theta cell)
    ws_lp = wb.create_sheet("Modelo_Solver_LP")
    ws_lp["A1"] = "Modelo de Programacao Linear Primal-Dual (Pronto para Excel Solver Simplex)"
    ws_lp["A1"].font = Font(bold=True, size=13, color="0E5A3C")
    ws_lp["A3"] = "Parametro theta (C1 interativo):"
    ws_lp["B3"] = 0.0
    ws_lp["B3"].number_format = "0.00"
    ws_lp["C3"] = "Ajuste B3 entre 0.00 e 1.00 e rode o Solver na tabela do C1_GLOBAL abaixo."

    row_cursor = 5
    for sc_idx, sc in enumerate(
        sorted(scenario_records, key=lambda r: r["scenario_order"])
    ):
        code = sc["scenario_code"]
        theta_ref = "$B$3" if sc_idx == 0 else "0"
        _style_header_cell(
            ws_lp.cell(row=row_cursor, column=1),
            f"Cenario {sc['scenario_order']}: {code}",
        )
        ws_lp.cell(row=row_cursor, column=2, value="Chute L")
        ws_lp.cell(row=row_cursor, column=3, value="Chute C")
        ws_lp.cell(row=row_cursor, column=4, value="Chute R")
        ws_lp.cell(row=row_cursor, column=5, value="q_emp (Batedor)")
        ws_lp.cell(row=row_cursor, column=6, value="Retorno A*q_emp")
        ws_lp.cell(row=row_cursor, column=7, value="A_eff(theta) L")
        ws_lp.cell(row=row_cursor, column=8, value="A_eff(theta) C")
        ws_lp.cell(row=row_cursor, column=9, value="A_eff(theta) R")
        ws_lp.cell(row=row_cursor, column=10, value="p* (Goleiro Primal)")
        ws_lp.cell(row=row_cursor, column=11, value="q~ (Dual Batedor)")

        mat_start = row_cursor + 1
        for i, gz in enumerate(ZONES):
            r = mat_start + i
            ws_lp.cell(row=r, column=1, value=f"Goleiro {gz}")
            for j, sz in enumerate(ZONES):
                c_a = ws_lp.cell(row=r, column=2 + j, value=sc[f"a_{gz}_{sz}"])
                c_a.number_format = "0.000000"
            c_qe = ws_lp.cell(row=r, column=5, value=sc[f"shooter_emp_{ZONES[i]}"])
            c_qe.number_format = "0.000000"

            # E{mat_start}:E{mat_start+2} holds q_emp
            c_aq = ws_lp.cell(
                row=r,
                column=6,
                value=f"=B{r}*$E${mat_start}+C{r}*$E${mat_start+1}+D{r}*$E${mat_start+2}",
            )
            c_aq.number_format = "0.000000"

            for j, base_col in enumerate(["B", "C", "D"]):
                c_at = ws_lp.cell(
                    row=r,
                    column=7 + j,
                    value=f"={theta_ref}*$F${r}+(1-{theta_ref})*{base_col}{r}",
                )
                c_at.number_format = "0.000000"

            c_p = ws_lp.cell(row=r, column=10, value=sc[f"gk_nash_{gz}"])
            c_p.number_format = "0.000000"
            c_q = ws_lp.cell(row=r, column=11, value=sc[f"shooter_nash_{gz}"])
            c_q.number_format = "0.000000"

        sum_row = mat_start + 3
        ws_lp.cell(row=sum_row, column=1, value="Soma Probabilidades (=1)")
        c_sum_qe = ws_lp.cell(row=sum_row, column=5, value=f"=SUM(E{mat_start}:E{mat_start+2})")
        c_sum_p = ws_lp.cell(row=sum_row, column=10, value=f"=SUM(J{mat_start}:J{mat_start+2})")
        c_sum_q = ws_lp.cell(row=sum_row, column=11, value=f"=SUM(K{mat_start}:K{mat_start+2})")
        for c in (c_sum_qe, c_sum_p, c_sum_q):
            c.number_format = "0.000000"

        ev_row = mat_start + 4
        ws_lp.cell(row=ev_row, column=1, value="Retorno Esperado p^T A_eff(:,j) >= V*")
        for j, col_let in enumerate(["G", "H", "I"]):
            c_ev = ws_lp.cell(
                row=ev_row,
                column=7 + j,
                value=f"=SUMPRODUCT($J${mat_start}:$J${mat_start+2},{col_let}{mat_start}:{col_let}{mat_start+2})",
            )
            c_ev.number_format = "0.000000"

        val_row = mat_start + 5
        ws_lp.cell(row=val_row, column=1, value="Check MIN(G:I) / MAX / Gap / Variavel V* (J) & W* (K)")
        c_vp = ws_lp.cell(row=val_row, column=7, value=f"=MIN(G{ev_row}:I{ev_row})")
        c_wd = ws_lp.cell(
            row=val_row,
            column=8,
            value=(
                f"=MAX("
                f"G{mat_start}*$K${mat_start}+H{mat_start}*$K${mat_start+1}+I{mat_start}*$K${mat_start+2},"
                f"G{mat_start+1}*$K${mat_start}+H{mat_start+1}*$K${mat_start+1}+I{mat_start+1}*$K${mat_start+2},"
                f"G{mat_start+2}*$K${mat_start}+H{mat_start+2}*$K${mat_start+1}+I{mat_start+2}*$K${mat_start+2}"
                f")"
            ),
        )
        c_gap = ws_lp.cell(row=val_row, column=9, value=f"=ABS(G{val_row}-H{val_row})")
        c_v_var = ws_lp.cell(row=val_row, column=10, value=sc["game_value_v_primal"])
        c_w_var = ws_lp.cell(row=val_row, column=11, value=sc["game_value_w_dual"])
        c_vp.number_format = "0.000000"
        c_wd.number_format = "0.000000"
        c_gap.number_format = "0.00E+00"
        c_v_var.number_format = "0.000000"
        c_w_var.number_format = "0.000000"

        row_cursor = val_row + 2

    # Sheet 3: Curva_Sensibilidade (66 rows + chart)
    ws_sens = wb.create_sheet("Curva_Sensibilidade")
    sens_headers = [
        "Ordem",
        "Cenario",
        "theta",
        "p*_L",
        "p*_C",
        "p*_R",
        "V*(theta) Primal",
        "W*(theta) Dual",
        "Gap Primal-Dual",
        "EV vs Habito Emp.",
        "Piso Minimax Pior Caso",
        "Ganho vs Nash (theta=0)",
    ]
    for col_idx, h in enumerate(sens_headers, start=1):
        _style_header_cell(ws_sens.cell(row=1, column=col_idx), h)

    nash_anchor_row_by_order: dict[int, int] = {}
    for idx, pt in enumerate(sensitivity_records, start=2):
        order = int(pt["scenario_order"])
        if round(float(pt["theta"]), 1) == 0.0:
            nash_anchor_row_by_order[order] = idx
        anchor_row = nash_anchor_row_by_order[order]

        ws_sens.cell(row=idx, column=1, value=order)
        ws_sens.cell(row=idx, column=2, value=pt["scenario_code"])
        c_th = ws_sens.cell(row=idx, column=3, value=pt["theta"])
        c_pl = ws_sens.cell(row=idx, column=4, value=pt["gk_opt_L"])
        c_pc = ws_sens.cell(row=idx, column=5, value=pt["gk_opt_C"])
        c_pr = ws_sens.cell(row=idx, column=6, value=pt["gk_opt_R"])
        c_v = ws_sens.cell(row=idx, column=7, value=pt["game_value_v_primal"])
        c_w = ws_sens.cell(row=idx, column=8, value=pt["game_value_w_dual"])
        c_g = ws_sens.cell(row=idx, column=9, value=f"=ABS(G{idx}-H{idx})")
        c_ev = ws_sens.cell(row=idx, column=10, value=pt["expected_vs_empirical_rate"])
        c_fl = ws_sens.cell(row=idx, column=11, value=pt["worst_case_floor_rate"])
        c_up = ws_sens.cell(row=idx, column=12, value=f"=G{idx}-G{anchor_row}")
        c_th.number_format = "0.0"
        for c in (c_pl, c_pc, c_pr, c_v, c_w, c_ev, c_fl, c_up):
            c.number_format = "0.00%"
        c_g.number_format = "0.00E+00"

    # Pivot helper block for native Excel line chart (theta vs C1..C6 V*)
    chart_start_col = 14  # Column N
    ws_sens.cell(row=1, column=chart_start_col, value="theta")
    ordered_codes = [
        sc["scenario_code"]
        for sc in sorted(scenario_records, key=lambda r: r["scenario_order"])
    ]
    for s_idx, code in enumerate(ordered_codes, start=1):
        ws_sens.cell(row=1, column=chart_start_col + s_idx, value=code)
    for t_idx, th in enumerate(THETA_GRID, start=2):
        ws_sens.cell(row=t_idx, column=chart_start_col, value=th).number_format = "0.0"
        for s_idx, code in enumerate(ordered_codes, start=1):
            val = sens_by_code_theta[(code, th)]["game_value_v_primal"]
            c = ws_sens.cell(row=t_idx, column=chart_start_col + s_idx, value=val)
            c.number_format = "0.00%"

    chart = LineChart()
    chart.title = "Curva de Sensibilidade Parametrica V*(theta)"
    chart.style = 10
    chart.y_axis.title = "Taxa Garantida de Nao-Gol V*"
    chart.x_axis.title = "Confianca no Scouting (theta)"
    data_ref = Reference(
        ws_sens,
        min_col=chart_start_col + 1,
        max_col=chart_start_col + len(ordered_codes),
        min_row=1,
        max_row=1 + len(THETA_GRID),
    )
    cats_ref = Reference(
        ws_sens, min_col=chart_start_col, min_row=2, max_row=1 + len(THETA_GRID)
    )
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.width = 18
    chart.height = 10
    ws_sens.add_chart(chart, "N14")

    # Sheet 4: Scouting_10_Batedores
    ws_sc = wb.create_sheet("Scouting_10_Batedores")
    sc_headers = [
        "Rank",
        "Jogador",
        "Estrela Luva",
        "Pe",
        "Pos",
        "Times",
        "Carreira n",
        "Conv. Carreira",
        "Espacial n",
        "Chute L%",
        "Chute C%",
        "Chute R%",
        "Natural%",
        "Oposto%",
        "Nash p*_L",
        "Nash p*_C",
        "Nash p*_R",
        "V* Nash",
        "Theta50 p*_L",
        "Theta50 p*_C",
        "Theta50 p*_R",
        "V*(0.5)",
        "Best Resp (theta=1)",
        "EV Best Resp",
    ]
    for col_idx, h in enumerate(sc_headers, start=1):
        _style_header_cell(ws_sc.cell(row=1, column=col_idx), h)

    for row_idx, d in enumerate(scouting_records, start=2):
        vals = [
            d["scouting_rank"],
            d["player"],
            "Sim" if d["is_featured_glove_star"] else "Nao",
            d["dominant_foot"],
            d["position"],
            d["teams_list"],
            d["career_total_kicks"],
            d["career_conversion_rate"],
            d["spatial_kicks"],
            d["shot_pct_L"],
            d["shot_pct_C"],
            d["shot_pct_R"],
            d["corner_natural_pct"],
            d["corner_opposite_pct"],
            d["gk_nash_L"],
            d["gk_nash_C"],
            d["gk_nash_R"],
            d["game_value_v_nash"],
            d["gk_theta50_L"],
            d["gk_theta50_C"],
            d["gk_theta50_R"],
            d["game_value_v_theta50"],
            d["best_response_zone_pt"],
            d["best_response_ev_theta1"],
        ]
        pct_cols = {8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 24}
        for col_idx, val in enumerate(vals, start=1):
            c = ws_sc.cell(row=row_idx, column=col_idx, value=val)
            if col_idx in pct_cols:
                c.number_format = "0.0%"

    # Auto-fit column widths gently across all sheets
    for ws in wb.worksheets:
        for col_cells in ws.columns:
            col_letter = get_column_letter(col_cells[0].column)
            max_len = max(
                len(str(cell.value or "")) if not str(cell.value or "").startswith("=") else 14
                for cell in col_cells
            )
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 42)

    wb.save(output_path)
    return output_path


def _publish_gold_table(
    client: bigquery.Client,
    records: list[dict[str, Any]],
    table_id: str,
    description: str,
) -> None:
    """Truncate-load JSON records into BigQuery Gold and enforce table labels."""
    load_cfg = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
        labels=GOLD_LABELS,
    )
    load_job = client.load_table_from_json(
        records, table_id, location=LOCATION, job_config=load_cfg
    )
    load_job.result()
    table = client.get_table(table_id)
    table.labels = GOLD_LABELS
    table.description = description
    client.update_table(table, ["labels", "description"])


def main() -> None:
    """Run parametric sensitivity, 10-shooter scouting, BigQuery Gold loads, JSON & Excel."""
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    job_cfg = bigquery.QueryJobConfig(labels=GOLD_LABELS)

    silver_sql = f"""
    SELECT
      player,
      team_shooting,
      position,
      outcome,
      detailed_outcome,
      gk_zone,
      shot_zone,
      body_part_clean,
      tactical_corner,
      has_spatial_coords,
      is_clutch_situational
    FROM `{SILVER_TABLE}`
    """
    all_silver_rows = [dict(r) for r in client.query(silver_sql, job_config=job_cfg).result()]
    spatial_rows = [r for r in all_silver_rows if r.get("has_spatial_coords")]

    scenario_records = lns.solve_all_scenarios(spatial_rows)
    sensitivity_records = solve_sensitivity_all_scenarios(scenario_records)
    scouting_records = build_shooter_scouting_records(
        all_silver_rows=all_silver_rows,
        scenario_records=scenario_records,
    )

    _publish_gold_table(
        client,
        sensitivity_records,
        GOLD_SENSITIVITY_TABLE,
        "Camada Gold (E3-T02): Curva parametrica V*(theta) em [0, 1] para os 6 cenarios",
    )
    _publish_gold_table(
        client,
        scouting_records,
        GOLD_SCOUTING_TABLE,
        "Camada Gold (E3-T02): Dossie Nash + Empirical Bayes dos 10 principais batedores",
    )

    json_path = export_dashboard_json(
        scenario_records=scenario_records,
        sensitivity_records=sensitivity_records,
        scouting_records=scouting_records,
    )
    xlsx_path = generate_excel_validation_workbook(
        scenario_records=scenario_records,
        sensitivity_records=sensitivity_records,
        scouting_records=scouting_records,
    )

    print(f"[Gold E3-T02] Sensibilidade publicada: {GOLD_SENSITIVITY_TABLE} ({len(sensitivity_records)} pontos)")
    for code in [r["scenario_code"] for r in sorted(scenario_records, key=lambda x: x["scenario_order"])]:
        pts = [p for p in sensitivity_records if p["scenario_code"] == code]
        v0, v05, v1 = pts[0]["game_value_v_primal"], pts[5]["game_value_v_primal"], pts[-1]["game_value_v_primal"]
        print(f"  {code:15s} | V*(0)={v0*100:.2f}% -> V*(0.5)={v05*100:.2f}% -> V*(1.0)={v1*100:.2f}%")

    print(f"[Gold E3-T02] Scouting publicado: {GOLD_SCOUTING_TABLE} ({len(scouting_records)} jogadores)")
    for d in scouting_records:
        print(
            f"  #{d['scouting_rank']:2d} {d['player']:20s} | sp={d['spatial_kicks']:2d}/{d['career_total_kicks']:2d} | "
            f"L/C/R={d['shot_count_L']}/{d['shot_count_C']}/{d['shot_count_R']} | "
            f"V*(0)={d['game_value_v_nash']*100:.2f}% | BR={d['best_response_zone_theta1']} ({d['best_response_ev_theta1']*100:.2f}%)"
        )
    print(f"[Export] JSON: {json_path}")
    print(f"[Export] Excel Solver: {xlsx_path}")


if __name__ == "__main__":
    main()
