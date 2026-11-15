import os
from google.cloud import bigquery

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "dev-plataforma-geral")
BRONZE_TABLE = f"{PROJECT_ID}.po_bronze.raw_kaggle_penalties_sofascore"
SILVER_TABLE = f"{PROJECT_ID}.po_silver.stg_football_penalties_clean"
LOCATION = "southamerica-east1"

SILVER_BASE_DDL = f"""
CREATE OR REPLACE TABLE `{SILVER_TABLE}`
CLUSTER BY has_spatial_coords, outcome, position_group
OPTIONS (
  description = "Camada Silver (E2-T02): 15.726 penaltis de futebol limpos (sem handebol) e 1.377 registros espaciais com coordenadas de baliza normalizadas",
  labels = [("datacloud", "antigravity"), ("domain", "po"), ("layer", "silver")]
) AS
WITH handball_teams AS (
  SELECT team FROM UNNEST([
    'Baerum', 'Byaasen IL', 'Fana', 'Fjellhammer', 'Follo HK Damer',
    'Fredrikstad Bkl', 'Gjerpen Handball Skien U20', 'Larvik HK',
    'Molde HK', 'Oppsal', 'Raelingen', 'Sola', 'Storhamar', 'Tertnes IL'
  ]) AS team
),
parsed AS (
  SELECT
    r.*,
    r.end_location_y IS NOT NULL AS has_spatial_coords,
    IF(r.end_location_x = 100.0, 1.0, -1.0) AS goal_orientation_sign,
    CASE
      WHEN r.end_location_y IS NOT NULL THEN
        ROUND((r.end_location_y - 50.0) * IF(r.end_location_x = 100.0, 1.0, -1.0), 4)
      ELSE NULL
    END AS shot_y_norm,
    SAFE_CAST(REGEXP_EXTRACT(r.gkCoordinates, r'^\\(([0-9.]+),') AS FLOAT64) AS gk_x_raw,
    SAFE_CAST(REGEXP_EXTRACT(r.gkCoordinates, r',\\s*([0-9.]+)\\)$') AS FLOAT64) AS gk_y_raw
  FROM `{BRONZE_TABLE}` r
  WHERE r.home_team NOT IN (SELECT team FROM handball_teams)
    AND r.away_team NOT IN (SELECT team FROM handball_teams)
)
SELECT
  p.*,
  CASE
    WHEN p.gk_y_raw IS NOT NULL THEN
      ROUND((p.gk_y_raw - 50.0) * p.goal_orientation_sign, 4)
    ELSE NULL
  END AS gk_y_norm,
  CASE
    WHEN NOT p.has_spatial_coords THEN NULL
    WHEN p.shot_y_norm <= -1.2 THEN 'L'
    WHEN p.shot_y_norm >= 1.2 THEN 'R'
    ELSE 'C'
  END AS shot_zone,
  (p.period = '2nd' AND (p.minute >= 75 OR ABS(p.home_score - p.away_score) <= 1)) AS is_clutch_situational,
  (p.minute >= 80 AND ABS(p.home_score - p.away_score) <= 1) AS is_clutch_macro,
  CASE
    WHEN p.position IN ('F', 'RW', 'LW') THEN 'Forward'
    WHEN p.position = 'M' THEN 'Midfielder'
    WHEN p.position IN ('D', 'CB', 'RB', 'LB') THEN 'Defender'
    WHEN p.position = 'G' THEN 'Goalkeeper'
    ELSE 'Other'
  END AS position_group,
  CURRENT_TIMESTAMP() AS _silver_loaded_at
FROM parsed p;
"""


def main() -> None:
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    job_config = bigquery.QueryJobConfig(
        labels={"datacloud": "antigravity", "domain": "po", "layer": "silver"}
    )
    query_job = client.query(SILVER_BASE_DDL, job_config=job_config)
    query_job.result()

    table = client.get_table(SILVER_TABLE)
    print(f"[Silver E2-T02] Job ID: {query_job.job_id}")
    print(f"[Silver E2-T02] Tabela: {SILVER_TABLE}")
    print(f"[Silver E2-T02] Total de linhas (futebol limpo): {table.num_rows}")


if __name__ == "__main__":
    main()
