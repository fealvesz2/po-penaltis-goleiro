import argparse
import csv
import datetime
import os
import sys
import unittest
from pathlib import Path

from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "etl"))
sys.path.insert(0, str(REPO_ROOT / "src" / "models"))

import extract_load_bronze as elb
import transform_silver_base as tsb
import enrich_silver_features as esf
import lp_nash_solver as lns

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


STAGE_REGISTRY: dict[str, list[type[unittest.TestCase]]] = {
    "E1": [TestE1Governance],
    "E2-T01": [TestE2T01BronzeIngestion],
    "E2-T02": [TestE2T02SilverBase],
    "E2-T03": [TestE2T03SilverEnrichment],
    "E2": [TestE2T01BronzeIngestion, TestE2T02SilverBase, TestE2T03SilverEnrichment],
    "E3-T01": [TestE3T01GoldNashSolver],
    "ALL": [
        TestE1Governance,
        TestE2T01BronzeIngestion,
        TestE2T02SilverBase,
        TestE2T03SilverEnrichment,
        TestE3T01GoldNashSolver,
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
