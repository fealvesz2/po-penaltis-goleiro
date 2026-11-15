import argparse
import contextlib
import csv
import datetime
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import openpyxl
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "etl"))
sys.path.insert(0, str(REPO_ROOT / "src" / "models"))

import extract_load_bronze as elb
import transform_silver_base as tsb
import enrich_silver_features as esf
import lp_nash_solver as lns
import sensitivity_and_scouting as sas
import generate_etapa2_3_deliverables as ged

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "dev-plataforma-geral")
LOCATION = "southamerica-east1"
TEST_MODE = os.environ.get("PO_TEST_MODE", "full")

HANDBALL_TEAMS = [
    "Baerum", "Byaasen IL", "Fana", "Fjellhammer", "Follo HK Damer",
    "Fredrikstad Bkl", "Gjerpen Handball Skien U20", "Larvik HK",
    "Molde HK", "Oppsal", "Raelingen", "Sola", "Storhamar", "Tertnes IL",
]


class BasePOTestCase(unittest.TestCase):
    client: bigquery.Client | None = None

    @classmethod
    def get_bq_client(cls) -> bigquery.Client:
        if cls.client is None:
            cls.client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
        return cls.client

    @classmethod
    def run_bq_row(cls, sql: str) -> dict:
        return cls.run_bq_rows(sql)[0]

    @classmethod
    def run_bq_rows(cls, sql: str) -> list[dict]:
        client = cls.get_bq_client()
        job_config = bigquery.QueryJobConfig(
            labels={"datacloud": "antigravity", "domain": "po", "layer": "qa"}
        )
        return [dict(r) for r in client.query(sql, job_config=job_config).result()]


class TestE1Governance(BasePOTestCase):
    """Casos de Teste TC-E1-01 e TC-E1-02 (Governanca GCP & Arquitetura Medalhao)."""

    def test_tc_e1_01_project_and_location_config(self) -> None:
        self.assertEqual(elb.PROJECT_ID, "dev-plataforma-geral")
        self.assertEqual(elb.LOCATION, "southamerica-east1")
        self.assertEqual(tsb.LOCATION, "southamerica-east1")
        self.assertEqual(esf.LOCATION, "southamerica-east1")
        self.assertEqual(lns.LOCATION, "southamerica-east1")

    def test_tc_e1_02_medallion_datasets_and_labels(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao online no BigQuery.")
        client = self.get_bq_client()
        self.assertEqual(client.project, "dev-plataforma-geral")

        ds_ids = {d.dataset_id for d in client.list_datasets(PROJECT_ID)}
        self.assertTrue({"po_bronze", "po_silver", "po_gold"}.issubset(ds_ids))

        bronze_ds = client.get_dataset(f"{PROJECT_ID}.po_bronze")
        self.assertEqual(bronze_ds.location, "southamerica-east1")
        self.assertEqual(bronze_ds.default_partition_expiration_ms, 7776000000)
        self.assertEqual(bronze_ds.labels.get("datacloud"), "antigravity")
        self.assertEqual(bronze_ds.labels.get("domain"), "po")


class TestE2T01BronzeIngestion(BasePOTestCase):
    """Casos de Teste TC-E2-01A e TC-E2-01B (Extracao Kaggle & Carga Bronze)."""

    def test_tc_e2_01a_local_schema_and_raw_csv_contract(self) -> None:
        self.assertEqual(len(elb.SCHEMA), 27)
        schema_map = {field.name: field.field_type for field in elb.SCHEMA}
        self.assertEqual(schema_map["period"], "STRING")
        self.assertEqual(schema_map["match_date"], "DATE")
        self.assertEqual(schema_map["gkCoordinates"], "STRING")

        self.assertTrue(elb.CSV_PATH.exists(), f"CSV bruto ausente: {elb.CSV_PATH}")
        with elb.CSV_PATH.open("r", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            row_count = sum(1 for _ in reader)
        self.assertEqual(len(header), 27)
        self.assertEqual(row_count, 16629)

    def test_tc_e2_01b_bigquery_bronze_table_invariants(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao online no BigQuery.")
        client = self.get_bq_client()
        table_ref = f"{PROJECT_ID}.po_bronze.raw_kaggle_penalties_sofascore"
        table = client.get_table(table_ref)
        self.assertEqual(len(table.schema), 27)
        self.assertEqual(table.labels.get("datacloud"), "antigravity")

        row = self.run_bq_row(
            f"""
            SELECT
              COUNT(*) AS total_rows,
              COUNT(DISTINCT match_id) AS unique_matches,
              MIN(match_date) AS min_date,
              MAX(match_date) AS max_date
            FROM `{table_ref}`
            """
        )
        self.assertEqual(row["total_rows"], 16629)
        self.assertEqual(row["unique_matches"], 13658)
        self.assertEqual(row["min_date"], datetime.date(1970, 8, 12))
        self.assertEqual(row["max_date"], datetime.date(2026, 6, 28))


class TestE2T02SilverBase(BasePOTestCase):
    """Casos de Teste TC-E2-02A e TC-E2-02B (Expurgo Handebol & Normalizacao Espacial)."""

    def test_tc_e2_02a_silver_base_sql_contract(self) -> None:
        for team in HANDBALL_TEAMS:
            self.assertIn(team, tsb.SILVER_BASE_DDL)
        self.assertIn("CLUSTER BY has_spatial_coords, outcome, position_group", tsb.SILVER_BASE_DDL)
        self.assertIn("WHEN p.shot_y_norm <= -1.2 THEN 'L'", tsb.SILVER_BASE_DDL)
        self.assertIn("WHEN p.shot_y_norm >= 1.2 THEN 'R'", tsb.SILVER_BASE_DDL)

    def test_tc_e2_02b_bigquery_silver_spatial_and_handball_invariants(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao online no BigQuery.")
        teams_sql = ", ".join(f"'{t}'" for t in HANDBALL_TEAMS)
        row = self.run_bq_row(
            f"""
            SELECT
              COUNT(*) AS total_football,
              COUNTIF(home_team IN ({teams_sql}) OR away_team IN ({teams_sql})) AS handball_leaks,
              COUNTIF(has_spatial_coords) AS spatial_rows,
              COUNTIF(has_spatial_coords AND shot_zone = 'L') AS zone_L,
              COUNTIF(has_spatial_coords AND shot_zone = 'C') AS zone_C,
              COUNTIF(has_spatial_coords AND shot_zone = 'R') AS zone_R,
              COUNTIF(has_spatial_coords AND shot_zone IS NULL) AS zone_nulls
            FROM `{tsb.SILVER_TABLE}`
            """
        )
        self.assertEqual(row["total_football"], 15726)
        self.assertEqual(row["handball_leaks"], 0)
        self.assertEqual(row["spatial_rows"], 1377)
        self.assertEqual(row["zone_L"], 592)
        self.assertEqual(row["zone_C"], 150)
        self.assertEqual(row["zone_R"], 635)
        self.assertEqual(row["zone_L"] + row["zone_C"] + row["zone_R"], 1377)
        self.assertEqual(row["zone_nulls"], 0)


class TestE2T03SilverEnrichment(BasePOTestCase):
    """Casos de Teste TC-E2-03A e TC-E2-03B (Decomposicao de Erro, GK Zone e Pe Dominante)."""

    def test_tc_e2_03a_enrich_idempotency_and_cluster_contract(self) -> None:
        self.assertIn("CLUSTER BY has_spatial_coords, outcome, position_group", esf.SILVER_ENRICH_DDL)
        self.assertNotIn("SELECT * EXCEPT", esf.SILVER_ENRICH_DDL)
        if TEST_MODE != "fast":
            client = self.get_bq_client()
            dry_cfg = bigquery.QueryJobConfig(
                dry_run=True,
                labels={"datacloud": "antigravity", "domain": "po", "layer": "qa"},
            )
            dry_job = client.query(esf.SILVER_ENRICH_DDL, job_config=dry_cfg)
            self.assertGreater(dry_job.total_bytes_processed, 0)

    def test_tc_e2_03b_bigquery_silver_enriched_features_invariants(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao online no BigQuery.")
        row = self.run_bq_row(
            f"""
            SELECT
              COUNTIF(has_spatial_coords AND detailed_outcome = 'scored') AS scored,
              COUNTIF(has_spatial_coords AND detailed_outcome = 'saved_by_gk') AS saved,
              COUNTIF(has_spatial_coords AND detailed_outcome = 'off_target_or_post') AS off_post,
              COUNTIF(has_spatial_coords AND detailed_outcome = 'saved_by_gk'
                      AND (end_location_y < 45.2 OR end_location_y > 54.8)) AS saved_outside_posts,
              COUNTIF(has_spatial_coords AND gk_zone = 'L') AS gk_L,
              COUNTIF(has_spatial_coords AND gk_zone = 'C') AS gk_C,
              COUNTIF(has_spatial_coords AND gk_zone = 'R') AS gk_R,
              COUNTIF(has_spatial_coords AND body_part_clean = 'right-foot') AS right_foot,
              COUNTIF(has_spatial_coords AND body_part_clean = 'left-foot') AS left_foot,
              COUNTIF(has_spatial_coords AND tactical_corner = 'Natural') AS corner_natural,
              COUNTIF(has_spatial_coords AND tactical_corner = 'Center') AS corner_center,
              COUNTIF(has_spatial_coords AND tactical_corner = 'Opposite') AS corner_opposite,
              COUNTIF(has_spatial_coords AND (
                detailed_outcome IS NULL OR gk_zone IS NULL OR body_part_clean IS NULL OR tactical_corner IS NULL
              )) AS enriched_nulls
            FROM `{esf.SILVER_TABLE}`
            """
        )
        self.assertEqual(row["scored"], 1176)
        self.assertEqual(row["saved"], 143)
        self.assertEqual(row["off_post"], 58)
        self.assertEqual(row["saved_outside_posts"], 0)
        self.assertEqual(row["gk_L"], 359)
        self.assertEqual(row["gk_C"], 465)
        self.assertEqual(row["gk_R"], 553)
        self.assertEqual(row["right_foot"], 996)
        self.assertEqual(row["left_foot"], 381)
        self.assertEqual(row["corner_natural"], 549)
        self.assertEqual(row["corner_center"], 150)
        self.assertEqual(row["corner_opposite"], 678)
        self.assertEqual(row["enriched_nulls"], 0)


class TestE3T01GoldNashSolver(BasePOTestCase):
    """Casos de Teste TC-E3-01A e TC-E3-01B (Solver PL Primal-Dual 3x3 & Camada Gold)."""

    def _assert_nash_properties(
        self,
        A: list[list[float]],
        expected_p: list[float],
        expected_q: list[float],
        expected_v: float,
    ) -> None:
        p, v = lns.solve_primal_gk(A)
        q, w = lns.solve_dual_shooter(A)

        self.assertAlmostEqual(sum(p), 1.0, places=9)
        self.assertAlmostEqual(sum(q), 1.0, places=9)
        self.assertLess(abs(v - w), 1e-12)
        self.assertAlmostEqual(v, expected_v, places=7)

        for i in range(3):
            self.assertGreaterEqual(p[i], 0.0)
            self.assertGreaterEqual(q[i], 0.0)
            self.assertAlmostEqual(p[i], expected_p[i], places=6)
            self.assertAlmostEqual(q[i], expected_q[i], places=6)

        for j in range(3):
            self.assertGreaterEqual(sum(p[i] * A[i][j] for i in range(3)), v - 1e-9)
        for i in range(3):
            self.assertLessEqual(sum(A[i][j] * q[j] for j in range(3)), w + 1e-9)

    def test_tc_e3_01a_solver_primal_dual_mathematical_contracts(self) -> None:
        self.assertEqual(lns.GOLD_LABELS, {"datacloud": "antigravity", "domain": "po", "layer": "gold"})

        # 1. Matriz Identidade 3x3 simetrica: equilibrio uniforme (1/3, 1/3, 1/3)
        identity_3x3 = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        self._assert_nash_properties(identity_3x3, [1.0 / 3.0] * 3, [1.0 / 3.0] * 3, 1.0 / 3.0)

        # 2. Ponto de Sela puro: goleiro fixa L e batedor fixa R com valor 0.40
        saddle_3x3 = [[0.50, 0.45, 0.40], [0.10, 0.20, 0.30], [0.20, 0.25, 0.15]]
        self._assert_nash_properties(saddle_3x3, [1.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.40)

        # 3. Subjogo 2x2 misto com linha C dominada e coluna C subotima para batedor
        dominated_c_3x3 = [[0.40, 0.80, 0.10], [0.01, 0.80, 0.01], [0.10, 0.80, 0.30]]
        self._assert_nash_properties(dominated_c_3x3, [0.40, 0.0, 0.60], [0.40, 0.0, 0.60], 0.22)

        # 4. Suavizacao Bayesiana Empirica (alpha=2.0 encolhe celula vazia para a matriz prior)
        prior = [[0.30] * 3 for _ in range(3)]
        sample_rows = [
            {"gk_zone": "L", "shot_zone": "L", "outcome": "missed"},
            {"gk_zone": "L", "shot_zone": "L", "outcome": "scored"},
        ]
        smoothed, stats = lns.compute_smoothed_payoff_matrix(sample_rows, alpha=2.0, prior_matrix=prior)
        self.assertAlmostEqual(smoothed[0][0], (1 + 2.0 * 0.30) / 4.0, places=9)
        self.assertAlmostEqual(smoothed[1][1], 0.30, places=9)
        self.assertEqual(stats["L_L"][0], 2)
        self.assertEqual(stats["C_C"][0], 0)

    def test_tc_e3_01b_bigquery_gold_matrices_and_duality_gap(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao online no BigQuery.")
        client = self.get_bq_client()
        table = client.get_table(lns.GOLD_MATRIX_TABLE)
        self.assertEqual(table.num_rows, 6)
        self.assertEqual(table.labels, lns.GOLD_LABELS)

        rows = self.run_bq_rows(
            f"SELECT * FROM `{lns.GOLD_MATRIX_TABLE}` ORDER BY scenario_order ASC"
        )
        self.assertEqual(len(rows), 6)

        expected = {
            "C1_GLOBAL": (1377, 0.0, 0.139382),
            "C2_RIGHT_FOOT": (996, 0.0, 0.143700),
            "C3_LEFT_FOOT": (381, 2.0, 0.121360),
            "C4_CLUTCH": (616, 0.0, 0.141208),
            "C5_FORWARDS": (841, 0.0, 0.131012),
            "C6_MID_DEF": (536, 0.0, 0.151811),
        }
        self.assertEqual([r["scenario_code"] for r in rows], list(expected.keys()))

        zones = ["L", "C", "R"]
        for r in rows:
            code = r["scenario_code"]
            exp_n, exp_alpha, exp_v = expected[code]
            self.assertEqual(r["sample_size"], exp_n)
            self.assertAlmostEqual(r["eb_alpha"], exp_alpha, places=6)
            self.assertLess(r["duality_gap"], 1e-9)
            self.assertAlmostEqual(r["game_value_v_primal"], r["game_value_w_dual"], places=6)
            self.assertAlmostEqual(r["game_value_v_primal"], exp_v, places=5)

            self.assertAlmostEqual(r["gk_emp_L"] + r["gk_emp_C"] + r["gk_emp_R"], 1.0, places=5)
            self.assertAlmostEqual(r["shooter_emp_L"] + r["shooter_emp_C"] + r["shooter_emp_R"], 1.0, places=5)
            self.assertAlmostEqual(r["gk_nash_L"] + r["gk_nash_C"] + r["gk_nash_R"], 1.0, places=5)
            self.assertAlmostEqual(r["shooter_nash_L"] + r["shooter_nash_C"] + r["shooter_nash_R"], 1.0, places=5)

            cell_n_sum = sum(r[f"n_{gz}_{sz}"] for gz in zones for sz in zones)
            cell_miss_sum = sum(r[f"miss_{gz}_{sz}"] for gz in zones for sz in zones)
            self.assertEqual(cell_n_sum, r["sample_size"])
            self.assertEqual(cell_miss_sum, r["total_missed"])


class TestE3T02SensitivityScouting(BasePOTestCase):
    """TC-E3-02A/B: Curva parametrica V*(theta), 10 batedores Gold, JSON e Excel Solver."""

    def test_tc_e3_02a_sensitivity_theta_and_excel_contracts(self) -> None:
        A = [
            [0.36, 0.05, 0.10],
            [0.08, 0.24, 0.06],
            [0.12, 0.07, 0.34],
        ]
        q_emp = [0.45, 0.15, 0.40]

        A0 = sas.build_theta_payoff_matrix(A, q_emp, 0.0)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(A0[i][j], A[i][j], places=12)

        A1 = sas.build_theta_payoff_matrix(A, q_emp, 1.0)
        emp_returns = sas.compute_empirical_column_returns(A, q_emp)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(A1[i][j], emp_returns[i], places=12)

        with self.assertRaises(ValueError):
            sas.build_theta_payoff_matrix(A, q_emp, 1.2)

        curve = sas.solve_sensitivity_for_scenario(
            scenario_code="C1_GLOBAL",
            scenario_order=1,
            scenario_label="Teste Sintetico",
            A=A,
            q_emp=q_emp,
        )
        self.assertEqual(len(curve), 11)
        _, v_nash = lns.solve_primal_gk(A)
        self.assertAlmostEqual(curve[0]["game_value_v_primal"], v_nash, places=6)
        self.assertAlmostEqual(curve[-1]["game_value_v_primal"], max(emp_returns), places=6)

        for idx, pt in enumerate(curve):
            self.assertLess(pt["duality_gap"], 1e-9)
            self.assertLessEqual(
                pt["worst_case_floor_rate"], pt["game_value_v_primal"] + 1e-6
            )
            self.assertLessEqual(
                pt["game_value_v_primal"], pt["expected_vs_empirical_rate"] + 1e-6
            )
            if idx > 0:
                self.assertGreaterEqual(
                    pt["game_value_v_primal"],
                    curve[idx - 1]["game_value_v_primal"] - 1e-6,
                )

        # Valida geracao de planilha Excel Solver com formulas ativas em arquivo temporario
        fake_scenario = {
            "scenario_order": 1,
            "scenario_code": "C1_GLOBAL",
            "scenario_label": "1. Global Sintetico",
            "sample_size": 100,
            "empirical_non_goal_rate": 0.14,
            "shooter_emp_L": q_emp[0],
            "shooter_emp_C": q_emp[1],
            "shooter_emp_R": q_emp[2],
            "gk_nash_L": 0.30,
            "gk_nash_C": 0.35,
            "gk_nash_R": 0.35,
            "shooter_nash_L": 0.30,
            "shooter_nash_C": 0.35,
            "shooter_nash_R": 0.35,
            "game_value_v_primal": curve[0]["game_value_v_primal"],
            "game_value_w_dual": curve[0]["game_value_w_dual"],
        }
        for i, gz in enumerate(sas.ZONES):
            for j, sz in enumerate(sas.ZONES):
                fake_scenario[f"a_{gz}_{sz}"] = A[i][j]

        fake_scout = {
            "scouting_rank": 1,
            "player": "Harry Kane",
            "is_featured_glove_star": True,
            "dominant_foot": "right-foot",
            "position": "F",
            "teams_list": "FC Bayern",
            "career_total_kicks": 72,
            "career_conversion_rate": 0.916667,
            "spatial_kicks": 28,
            "shot_pct_L": 11 / 28,
            "shot_pct_C": 0.0,
            "shot_pct_R": 17 / 28,
            "corner_natural_pct": 11 / 28,
            "corner_opposite_pct": 17 / 28,
            "gk_nash_L": 0.30,
            "gk_nash_C": 0.38,
            "gk_nash_R": 0.32,
            "game_value_v_nash": 0.135,
            "gk_theta50_L": 0.25,
            "gk_theta50_C": 0.35,
            "gk_theta50_R": 0.40,
            "game_value_v_theta50": 0.145,
            "best_response_zone_pt": "Direita (batedor)",
            "best_response_ev_theta1": 0.16,
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_xlsx = Path(tmp_dir) / "solver_check.xlsx"
            sas.generate_excel_validation_workbook(
                scenario_records=[fake_scenario],
                sensitivity_records=curve,
                scouting_records=[fake_scout],
                output_path=out_xlsx,
            )
            wb = openpyxl.load_workbook(out_xlsx, data_only=False)
            self.assertEqual(
                wb.sheetnames,
                ["Resumo_Executivo", "Modelo_Solver_LP", "Curva_Sensibilidade", "Scouting_10_Batedores"],
            )
            ws_lp = wb["Modelo_Solver_LP"]
            self.assertEqual(ws_lp["J9"].value, "=SUM(J6:J8)")
            self.assertEqual(ws_lp["G10"].value, "=SUMPRODUCT($J$6:$J$8,G6:G8)")
            self.assertEqual(ws_lp["G11"].value, "=MIN(G10:I10)")

    def test_tc_e3_02b_bigquery_sensitivity_scouting_and_exports(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao online no BigQuery e artefatos.")
        client = self.get_bq_client()

        # 1. BigQuery Gold: mart_sensitivity_theta
        sens_table = client.get_table(sas.GOLD_SENSITIVITY_TABLE)
        self.assertEqual(sens_table.num_rows, 66)
        self.assertEqual(sens_table.labels, sas.GOLD_LABELS)

        sens_rows = self.run_bq_rows(
            f"SELECT * FROM `{sas.GOLD_SENSITIVITY_TABLE}` ORDER BY scenario_order ASC, theta ASC"
        )
        self.assertEqual(len(sens_rows), 66)

        by_code: dict[str, list[dict]] = {}
        for r in sens_rows:
            by_code.setdefault(r["scenario_code"], []).append(r)
            self.assertLess(r["duality_gap"], 1e-9)
            self.assertAlmostEqual(
                r["gk_opt_L"] + r["gk_opt_C"] + r["gk_opt_R"], 1.0, places=5
            )
            self.assertLessEqual(
                r["worst_case_floor_rate"], r["game_value_v_primal"] + 1e-6
            )
            self.assertLessEqual(
                r["game_value_v_primal"], r["expected_vs_empirical_rate"] + 1e-6
            )

        self.assertEqual(len(by_code), 6)
        for code, pts in by_code.items():
            self.assertEqual(len(pts), 11, f"Cenario {code} sem 11 pontos")
            for idx in range(1, len(pts)):
                self.assertGreaterEqual(
                    pts[idx]["game_value_v_primal"],
                    pts[idx - 1]["game_value_v_primal"] - 1e-6,
                )
        self.assertAlmostEqual(by_code["C1_GLOBAL"][0]["game_value_v_primal"], 0.139382, places=5)

        # 2. BigQuery Gold: mart_shooter_scouting
        scout_table = client.get_table(sas.GOLD_SCOUTING_TABLE)
        self.assertEqual(scout_table.num_rows, 10)
        self.assertEqual(scout_table.labels, sas.GOLD_LABELS)

        scout_rows = self.run_bq_rows(
            f"SELECT * FROM `{sas.GOLD_SCOUTING_TABLE}` ORDER BY scouting_rank ASC"
        )
        self.assertEqual(len(scout_rows), 10)
        players_set = {r["player"] for r in scout_rows}
        for star in sas.FEATURED_GLOVE_STARS:
            self.assertIn(star, players_set)

        for r in scout_rows:
            self.assertGreaterEqual(r["spatial_kicks"], 10)
            self.assertLess(r["duality_gap"], 1e-9)
            self.assertAlmostEqual(
                r["shot_pct_L"] + r["shot_pct_C"] + r["shot_pct_R"], 1.0, places=5
            )
            self.assertAlmostEqual(
                r["gk_nash_L"] + r["gk_nash_C"] + r["gk_nash_R"], 1.0, places=5
            )
            self.assertAlmostEqual(
                r["gk_theta50_L"] + r["gk_theta50_C"] + r["gk_theta50_R"], 1.0, places=5
            )
            self.assertEqual(
                r["corner_natural_count"] + r["corner_center_count"] + r["corner_opposite_count"],
                r["spatial_kicks"],
            )

        # 3. Exportacao JSON unificada para Dashboard Web
        self.assertTrue(sas.JSON_EXPORT_PATH.exists())
        payload = json.loads(sas.JSON_EXPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["scenarios"]), 6)
        self.assertEqual(len(payload["sensitivity_curves"]), 66)
        self.assertEqual(len(payload["shooter_scouting"]), 10)
        kane = next(p for p in payload["shooter_scouting"] if p["player"] == "Harry Kane")
        self.assertEqual(kane["spatial_kicks"], 28)

        # 4. Planilha Excel Solver gerada
        self.assertTrue(sas.EXCEL_VALIDATION_PATH.exists())
        wb = openpyxl.load_workbook(sas.EXCEL_VALIDATION_PATH, data_only=False)
        self.assertEqual(
            wb.sheetnames,
            ["Resumo_Executivo", "Modelo_Solver_LP", "Curva_Sensibilidade", "Scouting_10_Batedores"],
        )
        self.assertEqual(wb["Curva_Sensibilidade"].max_row, 67)
        self.assertEqual(wb["Scouting_10_Batedores"].max_row, 11)


class TestE3T03DocumentationAndXlsm(BasePOTestCase):
    """TC-E3-03A/B: Documentacao Etapas 2-3 (.md) e Planilha Oficial (.xlsm)."""

    @staticmethod
    def _build_minimal_mart_fixture() -> dict:
        codes = [
            "C1_GLOBAL",
            "C2_RIGHT_FOOT",
            "C3_LEFT_FOOT",
            "C4_CLUTCH",
            "C5_FORWARDS",
            "C6_MID_DEF",
        ]
        scenarios = []
        curves = []
        for idx, code in enumerate(codes, start=1):
            rec = {
                "scenario_order": idx,
                "scenario_code": code,
                "scenario_label": code,
                "sample_size": 1377 if idx == 1 else 500,
                "total_missed": 201 if idx == 1 else 70,
                "empirical_non_goal_rate": 0.1460,
                "eb_alpha": 2.0 if idx == 3 else 0.0,
                "gk_emp_L": 0.26,
                "gk_emp_C": 0.34,
                "gk_emp_R": 0.40,
                "gk_nash_L": 0.287,
                "gk_nash_C": 0.381,
                "gk_nash_R": 0.332,
                "shooter_emp_L": 0.43,
                "shooter_emp_C": 0.11,
                "shooter_emp_R": 0.46,
                "shooter_nash_L": 0.296,
                "shooter_nash_C": 0.365,
                "shooter_nash_R": 0.339,
                "game_value_v_primal": 0.1394,
                "game_value_w_dual": 0.1394,
                "duality_gap": 0.0,
            }
            for gz in sas.ZONES:
                for sz in sas.ZONES:
                    rec[f"a_{gz}_{sz}"] = 0.35 if gz == sz else 0.04
                    rec[f"n_{gz}_{sz}"] = 100
                    rec[f"miss_{gz}_{sz}"] = 14
            rec["a_L_C"] = 0.0286
            rec["a_C_L"] = 0.0505
            rec["a_R_L"] = 0.0343
            rec["a_C_C"] = 0.3019
            rec["a_L_L"] = 0.3789
            scenarios.append(rec)
            for th in sas.THETA_GRID:
                curves.append(
                    {
                        "scenario_order": idx,
                        "scenario_code": code,
                        "theta": th,
                        "game_value_v_primal": 0.1394 if th <= 0.6 else 0.1886,
                        "worst_case_floor_rate": 0.1394 if th <= 0.6 else 0.0286,
                    }
                )

        scouting = [
            {
                "scouting_rank": rank,
                "player": star,
                "is_featured_glove_star": rank <= 6,
                "dominant_foot": "right-foot",
                "career_total_kicks": 30,
                "spatial_kicks": 12,
                "shot_count_L": 4,
                "shot_count_C": 1,
                "shot_count_R": 7,
                "corner_natural_count": 4,
                "corner_center_count": 1,
                "corner_opposite_count": 7,
                "gk_nash_L": 0.30,
                "gk_nash_C": 0.35,
                "gk_nash_R": 0.35,
                "game_value_v_nash": 0.125,
                "gk_theta50_L": 0.30,
                "gk_theta50_C": 0.35,
                "gk_theta50_R": 0.35,
                "best_response_zone_theta1": "R",
                "best_response_ev_theta1": 0.18,
            }
            for rank, star in enumerate(
                sas.FEATURED_GLOVE_STARS
                + ["Hakan Çalhanoğlu", "Mikel Oyarzabal", "Robert Lewandowski", "Ante Budimir"],
                start=1,
            )
        ]
        return {
            "scenarios": scenarios,
            "sensitivity_curves": curves,
            "shooter_scouting": scouting,
        }

    def test_tc_e3_03a_deliverable_builders_and_zero_stale_draft(self) -> None:
        mart = self._build_minimal_mart_fixture()
        cells = ged.build_etapa2_cell_texts(mart)
        self.assertEqual(list(cells.keys()), ["B", "C", "D", "E", "F", "G", "H"])

        stale_markers = [
            "136 pênaltis",
            "136 penaltis",
            "StatsBomb",
            "regressão logística",
            "regressao logistica",
            "não informa para que lado o goleiro pulou",
        ]
        joined = "\n".join(cells.values())
        self.assertNotIn("\u2014", joined)
        for marker in stale_markers:
            self.assertNotIn(marker, joined)
        for expected in ("15.726", "1.377", "Primal", "Dual", "13,94%", "Excel Solver", "BigQuery"):
            self.assertIn(expected, joined)

        md_text = ged.render_etapa2_3_markdown(mart)
        self.assertNotIn("\u2014", md_text)
        for sc_code in ("C1_GLOBAL", "C2_RIGHT_FOOT", "C3_LEFT_FOOT", "C4_CLUTCH", "C5_FORWARDS", "C6_MID_DEF"):
            self.assertIn(sc_code, md_text)
        for star in sas.FEATURED_GLOVE_STARS:
            self.assertIn(star, md_text)
        self.assertIn("19/11", md_text)

    def test_tc_e3_03b_repo_docs_and_xlsm_sync(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando auditoria de arquivos consolidados em docs/.")

        mart = ged.load_mart_payload()
        expected_cells = ged.build_etapa2_cell_texts(mart)

        # 1. Verifica relatorio Markdown Etapas 2 e 3
        self.assertTrue(ged.REPORT_MD_PATH.exists())
        md_text = ged.REPORT_MD_PATH.read_text(encoding="utf-8")
        self.assertNotIn("\u2014", md_text)
        self.assertIn("15.726", md_text)
        self.assertIn("13.94%", md_text)
        self.assertIn("66 pontos", md_text)
        self.assertIn("| `C4_CLUTCH` | 14.12% | `theta = 0.5` | `theta = 0.6` |", md_text)
        for star in sas.FEATURED_GLOVE_STARS:
            self.assertIn(star, md_text)

        # 2. Verifica planilha oficial atualizada (.xlsm) preservando abas e Grupo 11
        self.assertTrue(ged.OFFICIAL_XLSM_PATH.exists())
        wb = openpyxl.load_workbook(ged.OFFICIAL_XLSM_PATH, keep_vba=True)
        self.assertEqual(
            wb.sheetnames,
            [
                "Projeto Final - Etapa 1 Em sala",
                "Projeto Final Etapa 2 - Modelag",
                "Semana 10 - 1911 Reunião com ca",
            ],
        )
        ws_et2 = wb[ged.ETAPA2_SHEET_NAME]
        self.assertEqual(ws_et2["A3"].value, "Grupo 11")
        for col_letter, expected_text in expected_cells.items():
            actual_val = str(ws_et2[f"{col_letter}3"].value or "")
            self.assertNotIn("\u2014", actual_val)
            self.assertNotIn("StatsBomb", actual_val)
            self.assertEqual(actual_val, expected_text)

        ws_s10 = wb["Semana 10 - 1911 Reunião com ca"]
        self.assertEqual(ws_s10["A11"].value, "16h30 - 16h45")
        self.assertEqual(ws_s10["B11"].value, 11)


class _QuietRepoHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """Serve REPO_ROOT files silently during automated headless browser checks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return None


def _find_chromium_binary() -> str | None:
    """Locate an installed Chrome or Edge binary for headless browser tests."""
    candidates = [
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return str(cand)
    return None


class TestE4T01PortfolioCore(BasePOTestCase):
    """Casos de Teste TC-E4-01A e TC-E4-01B (Portfolio Web Secoes 1 a 3 + KaTeX)."""

    def test_tc_e4_01a_portfolio_structure_katex_and_static_contracts(self) -> None:
        html_path = REPO_ROOT / "index.html"
        css_path = REPO_ROOT / "web" / "css" / "styles.css"
        js_path = REPO_ROOT / "web" / "js" / "app.js"
        katex_dir = REPO_ROOT / "web" / "vendor" / "katex"

        for asset in (
            html_path,
            css_path,
            js_path,
            katex_dir / "katex.min.css",
            katex_dir / "katex.min.js",
            katex_dir / "contrib" / "auto-render.min.js",
        ):
            self.assertTrue(asset.exists(), f"Asset obrigatorio ausente: {asset}")

        katex_css = (katex_dir / "katex.min.css").read_text(encoding="utf-8")
        font_refs = re.findall(r"url\((fonts/[^)]+\.woff2)\)", katex_css)
        self.assertGreaterEqual(len(font_refs), 20)
        for rel_font in font_refs:
            self.assertTrue((katex_dir / rel_font).exists(), f"Fonte KaTeX ausente: {rel_font}")

        html_text = html_path.read_text(encoding="utf-8")
        css_text = css_path.read_text(encoding="utf-8")
        js_text = js_path.read_text(encoding="utf-8")

        for filename, content in (("index.html", html_text), ("styles.css", css_text), ("app.js", js_text)):
            self.assertNotIn("\u2014", content, f"Travessao longo proibido encontrado em {filename}")

        self.assertIn('lang="pt-BR"', html_text)
        self.assertEqual(html_text.count("<h1"), 1)
        for marker in (
            '<link rel="icon"',
            "<header",
            "<nav",
            "<main",
            "<footer",
            "#conteudo-principal",
            'id="sec-1-contexto"',
            'id="sec-2-personas"',
            'id="sec-3-teoria"',
            'id="sec-4-treinador"',
            'id="sec-5-goleiro"',
            'id="sec-6-ponte"',
            'id="sec-7-arena"',
            "16.629",
            "15.726",
            "1.377",
            "po_bronze",
            "po_silver",
            "po_gold",
            "Palacios-Huerta",
            'role="tablist"',
            'id="tab-treinador"',
            'id="tab-goleiro"',
            'id="tab-ladoalado"',
            'aria-labelledby="tab-treinador"',
            'aria-labelledby="tab-goleiro"',
            'aria-labelledby="tab-ladoalado"',
            'hidden="until-found"',
            r"\max_{p,\, V}",
            r"\min_{q,\, W}",
            r"A_{ij}(\theta)",
        ):
            self.assertIn(marker, html_text, f"Marcador ausente em index.html: {marker}")

        self.assertIn("./data/processed/po_penalties_mart.json", js_text)
        self.assertIn("@layer reset, tokens, base, layout, components, utilities;", css_text)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css_text)
        self.assertIn("@media (forced-colors: active)", css_text)
        self.assertIn("@container (width < 520px)", css_text)
        self.assertIsNone(re.search(r"^\s*\*\s*[,{]", css_text, re.MULTILINE))

        node_bin = shutil.which("node")
        if node_bin:
            syntax = subprocess.run(
                [node_bin, "--check", str(js_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, f"Erro de sintaxe JS: {syntax.stderr}")

    def test_tc_e4_01b_browser_render_katex_and_zero_console_errors(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao em navegador headless.")

        browser_bin = _find_chromium_binary()
        node_bin = shutil.which("node")
        if not browser_bin or not node_bin:
            self.skipTest("Chrome/Edge ou Node indisponivel neste ambiente.")

        class _ReusableServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        httpd = _ReusableServer(("127.0.0.1", 0), _QuietRepoHTTPHandler)
        port = httpd.server_address[1]
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        tmp_profile = tempfile.mkdtemp(prefix="po-e4t01-chrome-")
        proc = subprocess.Popen(
            [
                browser_bin,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                f"--user-data-dir={tmp_profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            port_file = Path(tmp_profile) / "DevToolsActivePort"
            for _ in range(80):
                if port_file.exists() and port_file.read_text(encoding="utf-8").strip():
                    break
                time.sleep(0.1)
            self.assertTrue(port_file.exists(), "DevToolsActivePort nao foi criado pelo browser headless.")
            cdp_lines = port_file.read_text(encoding="utf-8").strip().splitlines()
            cdp_port = int(cdp_lines[0])
            ws_path = cdp_lines[1]

            node_script = r"""
const url = process.argv[1];
const browserWsUrl = process.argv[2];

(async () => {
  const listRes = await fetch(`http://127.0.0.1:${new URL(browserWsUrl).port}/json/list`);
  const targets = await listRes.json();
  const pageTarget = targets.find((t) => t.type === "page") || targets[0];
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  let seq = 0;
  const pending = new Map();
  const events = [];

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    } else if (msg.method) {
      events.push(msg);
    }
  });

  await new Promise((r) => ws.addEventListener("open", r));
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Network.enable");

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url });

  for (let i = 0; i < 40; i++) {
    const check = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(document.getElementById("mart-status-badge")?.textContent || "").includes("6 cenarios")`,
    });
    if (check.result.value) break;
    await new Promise((r) => setTimeout(r, 100));
  }

  const desktopEval = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const badge = document.getElementById("mart-status-badge")?.textContent || "";
      const footerTs = document.getElementById("footer-generated-at")?.textContent || "";
      const katexCount = document.querySelectorAll(".katex").length;
      const katexErrors = document.querySelectorAll(".katex-error").length;
      const isWideDesktop = document.getElementById("site-header").classList.contains("is-wide");
      const overflow1440 = document.documentElement.scrollWidth > document.documentElement.clientWidth;

      document.getElementById("tab-goleiro").click();
      const tabGolSelected = document.getElementById("tab-goleiro").getAttribute("aria-selected");
      const panelGolHidden = document.getElementById("panel-goleiro").hasAttribute("hidden");
      document.getElementById("tab-ladoalado").click();
      const tabLadoSelected = document.getElementById("tab-ladoalado").getAttribute("aria-selected");
      const panelCompHidden = document.getElementById("panel-comparativo").hasAttribute("hidden");
      document.getElementById("tab-treinador").click();

      document.querySelector('.pipeline-step-btn[data-stage="silver-enriched"]').click();
      const etlText = document.getElementById("pipeline-inspector")?.textContent || "";

      const sel = document.getElementById("theory-scenario-select");
      sel.value = "C6_MID_DEF";
      sel.dispatchEvent(new Event("change"));
      const verifierText = document.getElementById("theory-verifier-metrics")?.textContent || "";

      const themeInput = document.getElementById("theme-switch");
      const wasChecked = themeInput.checked;
      themeInput.click();
      const themeAfter = document.documentElement.dataset.theme;
      themeInput.click();

      return {
        badge,
        footerTs,
        katexCount,
        katexErrors,
        isWideDesktop,
        overflow1440,
        tabGolSelected,
        panelGolHidden,
        tabLadoSelected,
        panelCompHidden,
        etlHas1377: etlText.includes("1.377"),
        verifierHas1518: verifierText.includes("15,18%") && verifierText.includes("C6_MID_DEF"),
        themeToggled: themeAfter === (wasChecked ? "light" : "dark"),
      };
    })()`,
  });

  await send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await new Promise((r) => setTimeout(r, 250));
  const m390 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `({
      overflow390: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      isWide390: document.getElementById("site-header").classList.contains("is-wide"),
    })`,
  });

  await send("Emulation.setDeviceMetricsOverride", {
    width: 320,
    height: 640,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await new Promise((r) => setTimeout(r, 250));
  const m320 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `({
      overflow320: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      sw320: document.documentElement.scrollWidth,
    })`,
  });

  const consoleErrors = events.filter(
    (e) => e.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(e.params.type)
  );
  const exceptions = events.filter((e) => e.method === "Runtime.exceptionThrown");
  const logErrors = events.filter(
    (e) => e.method === "Log.entryAdded" && ["error", "warning"].includes(e.params.entry.level)
  );
  const httpErrors = events.filter(
    (e) => e.method === "Network.responseReceived" && e.params.response.status >= 400
  );
  const netFails = events.filter((e) => e.method === "Network.loadingFailed");

  console.log(
    JSON.stringify({
      desktop: desktopEval.result.value,
      m390: m390.result.value,
      m320: m320.result.value,
      consoleErrors,
      exceptions,
      logErrors,
      httpErrors,
      netFails,
    })
  );
  ws.close();
})();
"""
            node_run = subprocess.run(
                [
                    node_bin,
                    "-e",
                    node_script,
                    f"http://127.0.0.1:{port}/index.html",
                    f"ws://127.0.0.1:{cdp_port}{ws_path}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            report = json.loads(node_run.stdout)

            self.assertEqual(report["consoleErrors"], [], f"Console errors: {report['consoleErrors']}")
            self.assertEqual(report["exceptions"], [], f"JS exceptions: {report['exceptions']}")
            self.assertEqual(report["logErrors"], [], f"Browser log errors: {report['logErrors']}")
            self.assertEqual(report["httpErrors"], [], f"HTTP >=400 errors: {report['httpErrors']}")
            self.assertEqual(report["netFails"], [], f"Network failures: {report['netFails']}")

            desk = report["desktop"]
            self.assertIn("6 cenarios | 66 pts theta | 10 atletas", desk["badge"])
            self.assertIn("UTC", desk["footerTs"])
            self.assertGreaterEqual(desk["katexCount"], 15)
            self.assertEqual(desk["katexErrors"], 0)
            self.assertTrue(desk["isWideDesktop"])
            self.assertFalse(desk["overflow1440"])
            self.assertEqual(desk["tabGolSelected"], "true")
            self.assertFalse(desk["panelGolHidden"])
            self.assertEqual(desk["tabLadoSelected"], "true")
            self.assertFalse(desk["panelCompHidden"])
            self.assertTrue(desk["etlHas1377"])
            self.assertTrue(desk["verifierHas1518"])
            self.assertTrue(desk["themeToggled"])

            self.assertFalse(report["m390"]["overflow390"])
            self.assertFalse(report["m390"]["isWide390"])
            self.assertFalse(report["m320"]["overflow320"], f"Overflow em 320px: {report['m320']}")
        finally:
            httpd.shutdown()
            httpd.server_close()
            with contextlib.suppress(Exception):
                proc.terminate()
                proc.wait(timeout=5)
            shutil.rmtree(tmp_profile, ignore_errors=True)


def _extract_js_function(js_source: str, func_name: str) -> str:
    """Extract a top-level helper function body by balanced braces for Node unit verification."""
    marker = f"function {func_name}("
    start = js_source.index(marker)
    brace_start = js_source.index("{", start)
    depth = 0
    for idx in range(brace_start, len(js_source)):
        ch = js_source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js_source[start : idx + 1]
    raise AssertionError(f"Nao foi possivel extrair funcao JS: {func_name}")


class TestE4T02CoachDashboard(BasePOTestCase):
    """Casos de Teste TC-E4-02A e TC-E4-02B (Secao 4 Treinador: Heatmap 3x3, Slider theta e Curva)."""

    def test_tc_e4_02a_coach_section_contracts_and_js_simplex_accuracy(self) -> None:
        html_text = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
        css_text = (REPO_ROOT / "web" / "css" / "styles.css").read_text(encoding="utf-8")
        js_text = (REPO_ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")

        sec4_match = re.search(
            r'<section id="sec-4-treinador"[^>]*>(.*?)</section>',
            html_text,
            re.DOTALL,
        )
        self.assertIsNotNone(sec4_match, "Secao #sec-4-treinador nao encontrada em index.html.")
        sec4_html = sec4_match.group(1)
        self.assertNotIn("Em implementacao na entrega E4-T02", sec4_html)

        for marker in (
            'class="coach-controls-fieldset"',
            "<legend>",
            'id="coach-scenario-select"',
            'id="coach-theta-slider"',
            'type="range"',
            'id="coach-theta-output"',
            'for="coach-theta-slider"',
            'id="coach-kpis"',
            'id="coach-mix-panel"',
            'id="coach-heatmap-body"',
            'id="coach-sensitivity-svg"',
            'id="coach-overview-body"',
            'type="button"',
        ):
            self.assertIn(marker, sec4_html, f"Marcador ausente em #sec-4-treinador: {marker}")

        self.assertIn("::-webkit-slider-runnable-track", css_text)
        self.assertIn("::-moz-range-track", css_text)
        self.assertIn("@supports not (opacity: progress(1, 0, 100))", css_text)
        self.assertIsNone(
            re.search(r"::-webkit-slider-[^,{]*,\s*[^{]*::-moz-range", css_text),
            "Regra CSS nao deve combinar pseudo-elementos WebKit e Firefox na mesma lista.",
        )

        node_bin = shutil.which("node")
        if node_bin:
            solver_js = _extract_js_function(js_text, "extractMatrixAndEmpirical")
            solver_fn = _extract_js_function(js_text, "solveZeroSum3x3")
            eval_fn = _extract_js_function(js_text, "evaluateCoachAtTheta")
            mart_path = (REPO_ROOT / "data" / "processed" / "po_penalties_mart.json").as_posix()

            node_check = f"""
const fs = require("fs");
const ZONES = ["L", "C", "R"];
{solver_js}
{solver_fn}
{eval_fn}
const mart = JSON.parse(fs.readFileSync({json.dumps(mart_path)}, "utf8"));
let maxVDiff = 0;
let maxPDiff = 0;
let maxEvDiff = 0;
let maxFloorDiff = 0;
for (const pt of mart.sensitivity_curves) {{
  const sc = mart.scenarios.find((s) => s.scenario_code === pt.scenario_code);
  const res = evaluateCoachAtTheta(sc, pt.theta);
  maxVDiff = Math.max(maxVDiff, Math.abs(res.vStar - pt.game_value_v_primal));
  maxEvDiff = Math.max(maxEvDiff, Math.abs(res.evVsEmp - pt.expected_vs_empirical_rate));
  maxFloorDiff = Math.max(maxFloorDiff, Math.abs(res.worstFloor - pt.worst_case_floor_rate));
  maxPDiff = Math.max(
    maxPDiff,
    Math.abs(res.p[0] - pt.gk_opt_L),
    Math.abs(res.p[1] - pt.gk_opt_C),
    Math.abs(res.p[2] - pt.gk_opt_R)
  );
}}
console.log(JSON.stringify({{ count: mart.sensitivity_curves.length, maxVDiff, maxPDiff, maxEvDiff, maxFloorDiff }}));
"""
            run = subprocess.run(
                [node_bin, "-e", node_check],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            stats = json.loads(run.stdout)
            self.assertEqual(stats["count"], 66)
            self.assertLess(stats["maxVDiff"], 1e-5)
            self.assertLess(stats["maxPDiff"], 1e-5)
            self.assertLess(stats["maxEvDiff"], 1e-5)
            self.assertLess(stats["maxFloorDiff"], 1e-5)

    def test_tc_e4_02b_coach_browser_interactive_recalculation_and_responsive(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao em navegador headless.")

        browser_bin = _find_chromium_binary()
        node_bin = shutil.which("node")
        if not browser_bin or not node_bin:
            self.skipTest("Chrome/Edge ou Node indisponivel neste ambiente.")

        class _ReusableServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        httpd = _ReusableServer(("127.0.0.1", 0), _QuietRepoHTTPHandler)
        port = httpd.server_address[1]
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        tmp_profile = tempfile.mkdtemp(prefix="po-e4t02-chrome-")
        proc = subprocess.Popen(
            [
                browser_bin,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                f"--user-data-dir={tmp_profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            port_file = Path(tmp_profile) / "DevToolsActivePort"
            for _ in range(80):
                if port_file.exists() and port_file.read_text(encoding="utf-8").strip():
                    break
                time.sleep(0.1)
            self.assertTrue(port_file.exists(), "DevToolsActivePort nao foi criado pelo browser headless.")
            cdp_lines = port_file.read_text(encoding="utf-8").strip().splitlines()
            cdp_port = int(cdp_lines[0])

            node_script = r"""
const url = process.argv[1];
const cdpPort = process.argv[2];

(async () => {
  const targets = await (await fetch(`http://127.0.0.1:${cdpPort}/json`)).json();
  const pageTarget = targets.find((t) => t.type === "page") || targets[0];
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  let seq = 0;
  const pending = new Map();
  const events = [];

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    } else if (msg.method) {
      events.push(msg);
    }
  });

  await new Promise((r) => ws.addEventListener("open", r));
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Network.enable");

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url });

  for (let i = 0; i < 40; i++) {
    const ready = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `document.querySelectorAll("#coach-overview-body tr").length === 6 && document.querySelectorAll("#coach-sensitivity-svg polyline").length === 3`,
    });
    if (ready.result.value) break;
    await new Promise((r) => setTimeout(r, 100));
  }

  const state = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const sel = document.getElementById("coach-scenario-select");
      const slider = document.getElementById("coach-theta-slider");
      const out = document.getElementById("coach-theta-output");
      const kpis = document.getElementById("coach-kpis");
      const mix = document.getElementById("coach-mix-panel");
      const heat = document.getElementById("coach-heatmap-body");
      const readout = document.getElementById("coach-chart-readout");
      const svg = document.getElementById("coach-sensitivity-svg");

      const init = {
        options: sel.options.length,
        overviewRows: document.querySelectorAll("#coach-overview-body tr").length,
        kpisText: kpis.textContent,
        heatRows: heat.querySelectorAll("tr").length,
        svgPolylines: svg.querySelectorAll("polyline").length,
      };

      slider.value = "0.85";
      slider.dispatchEvent(new Event("input", { bubbles: true }));
      const afterSliderC1 = {
        output: out.textContent,
        valuetext: slider.getAttribute("aria-valuetext") || "",
        kpisText: kpis.textContent,
        mixText: mix.textContent,
        heatText: heat.textContent,
        readoutText: readout.textContent,
        circles: svg.querySelectorAll("circle").length,
      };

      document.querySelector('[data-coach-pick="C3_LEFT_FOOT"]').click();
      slider.value = "0";
      slider.dispatchEvent(new Event("input", { bubbles: true }));
      const c3Nash = {
        selected: sel.value,
        kpisText: kpis.textContent,
        mixText: mix.textContent,
      };

      document.getElementById("coach-preset-crit").click();
      const c3Crit = {
        sliderVal: slider.value,
        kpisText: kpis.textContent,
        mixText: mix.textContent,
      };

      return { init, afterSliderC1, c3Nash, c3Crit };
    })()`,
  });

  const overflow1440 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.documentElement.scrollWidth > document.documentElement.clientWidth`,
  });

  await send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await new Promise((r) => setTimeout(r, 250));
  const overflow390 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.documentElement.scrollWidth > document.documentElement.clientWidth`,
  });

  await send("Emulation.setDeviceMetricsOverride", {
    width: 320,
    height: 640,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await new Promise((r) => setTimeout(r, 250));
  const m320 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `({
      overflow320: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      sw320: document.documentElement.scrollWidth,
    })`,
  });

  const consoleErrors = events.filter(
    (e) => e.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(e.params.type)
  );
  const exceptions = events.filter((e) => e.method === "Runtime.exceptionThrown");
  const logErrors = events.filter(
    (e) => e.method === "Log.entryAdded" && ["error", "warning"].includes(e.params.entry.level)
  );
  const httpErrors = events.filter(
    (e) => e.method === "Network.responseReceived" && e.params.response.status >= 400
  );
  const netFails = events.filter((e) => e.method === "Network.loadingFailed");

  console.log(
    JSON.stringify({
      state: state.result.value,
      overflow1440: overflow1440.result.value,
      overflow390: overflow390.result.value,
      m320: m320.result.value,
      consoleErrors,
      exceptions,
      logErrors,
      httpErrors,
      netFails,
    })
  );
  ws.close();
})();
"""
            node_run = subprocess.run(
                [node_bin, "-e", node_script, f"http://127.0.0.1:{port}/index.html", str(cdp_port)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            report = json.loads(node_run.stdout)

            self.assertEqual(report["consoleErrors"], [], f"Console errors: {report['consoleErrors']}")
            self.assertEqual(report["exceptions"], [], f"JS exceptions: {report['exceptions']}")
            self.assertEqual(report["logErrors"], [], f"Browser log errors: {report['logErrors']}")
            self.assertEqual(report["httpErrors"], [], f"HTTP >=400 errors: {report['httpErrors']}")
            self.assertEqual(report["netFails"], [], f"Network failures: {report['netFails']}")

            st = report["state"]
            self.assertEqual(st["init"]["options"], 6)
            self.assertEqual(st["init"]["overviewRows"], 6)
            self.assertEqual(st["init"]["heatRows"], 3)
            self.assertEqual(st["init"]["svgPolylines"], 3)
            self.assertIn("13,94%", st["init"]["kpisText"])
            self.assertIn("Protegido", st["init"]["kpisText"])

            after_c1 = st["afterSliderC1"]
            self.assertIn("0,85", after_c1["output"])
            self.assertIn("theta 0,85", after_c1["valuetext"])
            self.assertIn("Alerta Exploratorio", after_c1["kpisText"])
            self.assertIn("2,86%", after_c1["kpisText"])
            self.assertIn("100,0%", after_c1["mixText"])
            self.assertIn("21,72%", after_c1["heatText"])
            self.assertIn("0,85", after_c1["readoutText"])
            self.assertEqual(after_c1["circles"], 3)

            c3_nash = st["c3Nash"]
            self.assertEqual(c3_nash["selected"], "C3_LEFT_FOOT")
            self.assertIn("12,14%", c3_nash["kpisText"])
            self.assertIn("49,1%", c3_nash["mixText"])

            c3_crit = st["c3Crit"]
            self.assertGreaterEqual(float(c3_crit["sliderVal"]), 0.50)
            self.assertIn("Alerta Exploratorio", c3_crit["kpisText"])

            self.assertFalse(report["overflow1440"])
            self.assertFalse(report["overflow390"])
            self.assertFalse(report["m320"]["overflow320"], f"Overflow em 320px: {report['m320']}")
        finally:
            httpd.shutdown()
            httpd.server_close()
            with contextlib.suppress(Exception):
                proc.terminate()
                proc.wait(timeout=5)
            shutil.rmtree(tmp_profile, ignore_errors=True)


class TestE4T03GoalkeeperAndBridge(unittest.TestCase):
    """Testes E4-T03: Visao de Luva (6 astros + Roleta), Ponte Analista->Goleiro e Excel Audit."""

    def test_tc_e4_03a_glove_and_bridge_contracts_and_math(self) -> None:
        html_text = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
        css_text = (REPO_ROOT / "web" / "css" / "styles.css").read_text(encoding="utf-8")
        js_text = (REPO_ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")

        for fname, content in (("index.html", html_text), ("styles.css", css_text), ("app.js", js_text)):
            self.assertNotIn("\u2014", content, f"Travessao longo proibido encontrado em {fname}.")

        sec5_match = re.search(
            r'<section id="sec-5-goleiro".*?</section>',
            html_text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(sec5_match, "Secao #sec-5-goleiro nao encontrada.")
        sec5_html = sec5_match.group(0)
        self.assertNotIn("Em implementacao na entrega E4-T03", sec5_html)

        sec6_match = re.search(
            r'<section id="sec-6-ponte".*?</section>',
            html_text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(sec6_match, "Secao #sec-6-ponte nao encontrada.")
        sec6_html = sec6_match.group(0)
        self.assertNotIn("Em implementacao na entrega E4-T03", sec6_html)

        for marker in (
            'id="glove-filter-stars"',
            'id="glove-filter-all"',
            'data-glove-theta="0"',
            'class="glove-stars-fieldset"',
            'id="glove-shooter-grid"',
            'id="glove-goal-svg"',
            'role="img"',
            'id="glove-roulette-svg"',
            'id="glove-spin-btn"',
            'id="glove-spin-result"',
            'aria-live="polite"',
        ):
            self.assertIn(marker, sec5_html, f"Marcador ausente em #sec-5-goleiro: {marker}")

        for marker in (
            'id="bridge-target-select"',
            'id="bridge-theta-slider"',
            'id="bridge-theta-output"',
            'id="bridge-live-summary"',
            'id="bridge-steps-grid"',
            'id="bridge-reconcile-body"',
            "validacao_excel_solver.xlsx",
            "Modelo_Solver_LP",
        ):
            self.assertIn(marker, sec6_html, f"Marcador ausente em #sec-6-ponte: {marker}")

        self.assertIn(".bridge-reconcile-table", css_text)
        self.assertIn("--label-6:", css_text)
        self.assertIn(".glove-star-card:has(> input:checked)", css_text)
        self.assertIn("@media (forced-colors: active)", css_text)

        node_bin = shutil.which("node")
        if node_bin:
            needed_fns = "\n".join(
                _extract_js_function(js_text, name)
                for name in (
                    "extractMatrixAndEmpirical",
                    "solveZeroSum3x3",
                    "evaluateCoachAtTheta",
                    "shooterToScenarioAdapter",
                    "allocateIntegerShares",
                    "buildRouletteBands",
                    "resolveTicketBand",
                )
            )
            mart_path = (REPO_ROOT / "data" / "processed" / "po_penalties_mart.json").as_posix()
            node_check = f"""
const fs = require("fs");
const ZONES = ["L", "C", "R"];
const ZONE_LABELS = {{ L: "Esquerda (L)", C: "Centro (C)", R: "Direita (R)" }};
const escapeHtml = (s) => String(s);
const fmtInt = (n) => String(n);
{needed_fns}
const mart = JSON.parse(fs.readFileSync({json.dumps(mart_path)}, "utf8"));
const featured = mart.shooter_scouting.filter((s) => s.is_featured_glove_star).map((s) => s.player);
let maxV0Diff = 0;
let maxV50Diff = 0;
let maxV100Diff = 0;
let maxP50Diff = 0;
let allBandsValid = true;
for (const s of mart.shooter_scouting) {{
  const ad = shooterToScenarioAdapter(s);
  const r0 = evaluateCoachAtTheta(ad, 0.0);
  const r5 = evaluateCoachAtTheta(ad, 0.5);
  const r1 = evaluateCoachAtTheta(ad, 1.0);
  maxV0Diff = Math.max(maxV0Diff, Math.abs(r0.vStar - s.game_value_v_nash));
  maxV50Diff = Math.max(maxV50Diff, Math.abs(r5.vStar - s.game_value_v_theta50));
  maxV100Diff = Math.max(maxV100Diff, Math.abs(r1.vStar - s.best_response_ev_theta1));
  maxP50Diff = Math.max(
    maxP50Diff,
    Math.abs(r5.p[0] - s.gk_theta50_L),
    Math.abs(r5.p[1] - s.gk_theta50_C),
    Math.abs(r5.p[2] - s.gk_theta50_R)
  );
  for (const snap of [r0, r5, r1]) {{
    const k10 = allocateIntegerShares(snap.p, 10);
    if (k10.reduce((a, b) => a + b, 0) !== 10) allBandsValid = false;
    const bands = buildRouletteBands(snap.p);
    const seen = new Set();
    for (let t = 0; t < 100; t++) {{
      const picked = resolveTicketBand(bands, t);
      if (!picked || picked.pctInt <= 0) allBandsValid = false;
      seen.add(t);
    }}
    if (seen.size !== 100) allBandsValid = false;
    if (bands.reduce((a, b) => a + b.pctInt, 0) !== 100) allBandsValid = false;
  }}
}}
console.log(JSON.stringify({{ featured, totalShooters: mart.shooter_scouting.length, maxV0Diff, maxV50Diff, maxV100Diff, maxP50Diff, allBandsValid }}));
"""
            run = subprocess.run(
                [node_bin, "-e", node_check],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            stats = json.loads(run.stdout)
            self.assertEqual(
                stats["featured"],
                ["Harry Kane", "Kylian Mbappé", "Mohamed Salah", "Bruno Fernandes", "Erling Haaland", "Cole Palmer"],
            )
            self.assertEqual(stats["totalShooters"], 10)
            self.assertTrue(stats["allBandsValid"])
            self.assertLess(stats["maxV0Diff"], 1e-5)
            self.assertLess(stats["maxV50Diff"], 1e-5)
            self.assertLess(stats["maxV100Diff"], 1e-5)
            self.assertLess(stats["maxP50Diff"], 1e-5)

    def test_tc_e4_03b_browser_glove_roulette_and_bridge_interactive(self) -> None:
        if TEST_MODE == "fast":
            self.skipTest("Modo fast ativo: pulando verificacao em navegador headless.")

        browser_bin = _find_chromium_binary()
        node_bin = shutil.which("node")
        if not browser_bin or not node_bin:
            self.skipTest("Chrome/Edge ou Node indisponivel neste ambiente.")

        class _ReusableServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        httpd = _ReusableServer(("127.0.0.1", 0), _QuietRepoHTTPHandler)
        port = httpd.server_address[1]
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        tmp_profile = tempfile.mkdtemp(prefix="po-e4t03-chrome-")
        proc = subprocess.Popen(
            [
                browser_bin,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                f"--user-data-dir={tmp_profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            port_file = Path(tmp_profile) / "DevToolsActivePort"
            for _ in range(80):
                if port_file.exists() and port_file.read_text(encoding="utf-8").strip():
                    break
                time.sleep(0.1)
            self.assertTrue(port_file.exists(), "DevToolsActivePort nao foi criado pelo browser headless.")
            cdp_port = int(port_file.read_text(encoding="utf-8").strip().splitlines()[0])

            node_script = r"""
const url = process.argv[1];
const cdpPort = process.argv[2];

(async () => {
  const targets = await (await fetch(`http://127.0.0.1:${cdpPort}/json`)).json();
  const pageTarget = targets.find((t) => t.type === "page") || targets[0];
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  let seq = 0;
  const pending = new Map();
  const events = [];

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    } else if (msg.method) {
      events.push(msg);
    }
  });

  await new Promise((r) => ws.addEventListener("open", r));
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Network.enable");

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url });

  for (let i = 0; i < 40; i++) {
    const ready = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `document.querySelectorAll('#glove-shooter-grid .glove-star-card').length === 6 && document.querySelectorAll('#bridge-reconcile-body tr').length === 6`,
    });
    if (ready.result.value) break;
    await new Promise((r) => setTimeout(r, 100));
  }

  const state = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const starsDefault = Array.from(document.querySelectorAll('#glove-shooter-grid .glove-star-name')).map((el) => el.textContent.trim());
      const sec5Text = document.getElementById("sec-5-goleiro").textContent;
      const jargonHits = ["simplex", "minimax", "empirical bayes", "dualidade", "payoff"].filter((w) =>
        new RegExp("\\\\b" + w + "\\\\b", "i").test(sec5Text)
      );

      document.getElementById("glove-filter-all").click();
      const allCount = document.querySelectorAll('#glove-shooter-grid .glove-star-card').length;
      document.getElementById("glove-filter-stars").click();

      const palmerRadio = document.querySelector('input[name="glove_shooter"][value="Cole Palmer"]');
      palmerRadio.click();
      document.querySelector('[data-glove-theta="0.5"]').click();
      const palmer50Bands = document.getElementById("glove-roulette-bands").textContent;
      const palmerWheelCircles = document.querySelectorAll("#glove-roulette-svg circle").length;

      document.querySelector('input[name="glove_shooter"][value="Harry Kane"]').click();
      document.querySelector('[data-glove-theta="0"]').click();
      document.getElementById("glove-spin-btn").click();
      const afterOneSpin = {
        ticket: document.getElementById("glove-ticket-number").textContent,
        resultText: document.getElementById("glove-spin-result").textContent,
        tallyText: document.getElementById("glove-audit-tally").textContent,
        activeBandCount: document.querySelectorAll(".roulette-band-card.is-band-active").length,
      };
      document.getElementById("glove-batch-btn").click();
      const afterBatchTally = document.getElementById("glove-audit-tally").textContent;
      document.getElementById("glove-reset-btn").click();
      const afterResetTally = document.getElementById("glove-audit-tally").textContent;

      const bridgeSel = document.getElementById("bridge-target-select");
      const bridgeOpts = bridgeSel.options.length;
      const reconcileRows = document.querySelectorAll("#bridge-reconcile-body tr").length;
      const reconcileText = document.getElementById("bridge-reconcile-body").textContent;

      bridgeSel.value = "shooter:Erling Haaland";
      bridgeSel.dispatchEvent(new Event("change", { bubbles: true }));
      const bridgeSlider = document.getElementById("bridge-theta-slider");
      bridgeSlider.value = "0.5";
      bridgeSlider.dispatchEvent(new Event("input", { bubbles: true }));
      const bridgeHaaland50 = {
        summary: document.getElementById("bridge-live-summary").textContent,
        stepsCount: document.querySelectorAll("#bridge-steps-grid .bridge-step-card").length,
        stepsText: document.getElementById("bridge-steps-grid").textContent,
      };

      return {
        starsDefault,
        jargonHits,
        allCount,
        palmer50Bands,
        palmerWheelCircles,
        afterOneSpin,
        afterBatchTally,
        afterResetTally,
        bridgeOpts,
        reconcileRows,
        reconcileText,
        bridgeHaaland50,
      };
    })()`,
  });

  const overflow1440 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.documentElement.scrollWidth > document.documentElement.clientWidth`,
  });

  await send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await new Promise((r) => setTimeout(r, 250));
  const overflow390 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.documentElement.scrollWidth > document.documentElement.clientWidth`,
  });

  await send("Emulation.setDeviceMetricsOverride", {
    width: 320,
    height: 640,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await new Promise((r) => setTimeout(r, 250));
  const m320 = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `({
      overflow320: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      sw320: document.documentElement.scrollWidth,
    })`,
  });

  const consoleErrors = events.filter(
    (e) => e.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(e.params.type)
  );
  const exceptions = events.filter((e) => e.method === "Runtime.exceptionThrown");
  const logErrors = events.filter(
    (e) => e.method === "Log.entryAdded" && ["error", "warning"].includes(e.params.entry.level)
  );
  const httpErrors = events.filter(
    (e) => e.method === "Network.responseReceived" && e.params.response.status >= 400
  );
  const netFails = events.filter((e) => e.method === "Network.loadingFailed");

  console.log(
    JSON.stringify({
      state: state.result.value,
      overflow1440: overflow1440.result.value,
      overflow390: overflow390.result.value,
      m320: m320.result.value,
      consoleErrors,
      exceptions,
      logErrors,
      httpErrors,
      netFails,
    })
  );
  ws.close();
})();
"""
            node_run = subprocess.run(
                [node_bin, "-e", node_script, f"http://127.0.0.1:{port}/index.html", str(cdp_port)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            report = json.loads(node_run.stdout)

            self.assertEqual(report["consoleErrors"], [], f"Console errors: {report['consoleErrors']}")
            self.assertEqual(report["exceptions"], [], f"JS exceptions: {report['exceptions']}")
            self.assertEqual(report["logErrors"], [], f"Browser log errors: {report['logErrors']}")
            self.assertEqual(report["httpErrors"], [], f"HTTP >=400 errors: {report['httpErrors']}")
            self.assertEqual(report["netFails"], [], f"Network failures: {report['netFails']}")

            st = report["state"]
            self.assertEqual(
                st["starsDefault"],
                ["Harry Kane", "Kylian Mbappé", "Mohamed Salah", "Bruno Fernandes", "Erling Haaland", "Cole Palmer"],
            )
            self.assertEqual(st["jargonHits"], [], f"Jargao tecnico vazou para Secao 5: {st['jargonHits']}")
            self.assertEqual(st["allCount"], 10)
            self.assertIn("100%", st["palmer50Bands"])
            self.assertIn("00 a 99", st["palmer50Bands"])
            self.assertGreaterEqual(st["palmerWheelCircles"], 2)

            self.assertRegex(st["afterOneSpin"]["ticket"], r"^\d{2}$")
            self.assertIn("Sinal sorteado", st["afterOneSpin"]["resultText"])
            self.assertIn("Total de sorteios: 1", st["afterOneSpin"]["tallyText"])
            self.assertEqual(st["afterOneSpin"]["activeBandCount"], 1)
            self.assertIn("Total de sorteios: 11", st["afterBatchTally"])
            self.assertIn("0 realizados", st["afterResetTally"])

            self.assertEqual(st["bridgeOpts"], 16)
            self.assertEqual(st["reconcileRows"], 6)
            self.assertIn("Conciliado", st["reconcileText"])
            self.assertNotIn("Divergente", st["reconcileText"])
            self.assertEqual(st["bridgeHaaland50"]["stepsCount"], 4)
            self.assertIn("91,4%", st["bridgeHaaland50"]["stepsText"])

            self.assertFalse(report["overflow1440"])
            self.assertFalse(report["overflow390"])
            self.assertFalse(report["m320"]["overflow320"], f"Overflow em 320px: {report['m320']}")
        finally:
            httpd.shutdown()
            httpd.server_close()
            with contextlib.suppress(Exception):
                proc.terminate()
                proc.wait(timeout=5)
            shutil.rmtree(tmp_profile, ignore_errors=True)


STAGE_REGISTRY: dict[str, list[type[unittest.TestCase]]] = {
    "E1": [TestE1Governance],
    "E2-T01": [TestE2T01BronzeIngestion],
    "E2-T02": [TestE2T02SilverBase],
    "E2-T03": [TestE2T03SilverEnrichment],
    "E2": [TestE2T01BronzeIngestion, TestE2T02SilverBase, TestE2T03SilverEnrichment],
    "E3-T01": [TestE3T01GoldNashSolver],
    "E3-T02": [TestE3T02SensitivityScouting],
    "E3-T03": [TestE3T03DocumentationAndXlsm],
    "E3": [TestE3T01GoldNashSolver, TestE3T02SensitivityScouting, TestE3T03DocumentationAndXlsm],
    "E4-T01": [TestE4T01PortfolioCore],
    "E4-T02": [TestE4T02CoachDashboard],
    "E4-T03": [TestE4T03GoalkeeperAndBridge],
    "E4": [TestE4T01PortfolioCore, TestE4T02CoachDashboard, TestE4T03GoalkeeperAndBridge],
    "ALL": [
        TestE1Governance,
        TestE2T01BronzeIngestion,
        TestE2T02SilverBase,
        TestE2T03SilverEnrichment,
        TestE3T01GoldNashSolver,
        TestE3T02SensitivityScouting,
        TestE3T03DocumentationAndXlsm,
        TestE4T01PortfolioCore,
        TestE4T02CoachDashboard,
        TestE4T03GoalkeeperAndBridge,
    ],
}


def main() -> None:
    global TEST_MODE
    parser = argparse.ArgumentParser(
        description="Switch de Testes e Controle de Risco por Feature (Projeto PO Penaltis)"
    )
    parser.add_argument(
        "--stage",
        choices=list(STAGE_REGISTRY.keys()),
        default="ALL",
        help="Seleciona a etapa/feature alvo para validacao (padrao: ALL)",
    )
    parser.add_argument(
        "--mode",
        choices=["fast", "full"],
        default="full",
        help="fast = apenas contratos locais de codigo/SQL; full = inclui auditoria no BigQuery",
    )
    args = parser.parse_args()
    TEST_MODE = args.mode

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for test_cls in STAGE_REGISTRY[args.stage]:
        suite.addTests(loader.loadTestsFromTestCase(test_cls))

    print(f"=== [TEST SWITCH] Stage={args.stage} | Mode={args.mode} ===")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
