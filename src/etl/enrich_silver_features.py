import os
from google.cloud import bigquery

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "dev-plataforma-geral")
SILVER_TABLE = f"{PROJECT_ID}.po_silver.stg_football_penalties_clean"
LOCATION = "southamerica-east1"

SILVER_ENRICH_DDL = f"""
CREATE OR REPLACE TABLE `{SILVER_TABLE}`
CLUSTER BY has_spatial_coords, outcome, position_group
OPTIONS (
  description = "Camada Silver Enriquecida (E2-T03): 15.726 penaltis de futebol e 1.377 espaciais com detailed_outcome (143 defesas vs 58 fora/trave), gk_zone e body_part_clean (996 destros e 381 canhotos)",
  labels = [("datacloud", "antigravity"), ("domain", "po"), ("layer", "silver")]
) AS
WITH base AS (
  SELECT
    match_id, match_date, competition_stage, home_team, away_team,
    home_score, away_score, penalty_type, period, minute, second,
    team_shooting, player, position, shot_type, outcome, technique,
    body_part, xg, player_location_x, player_location_y,
    end_location_x, end_location_y, end_location_z,
    goalkeeper_name, goalkeeper_id, gkCoordinates,
    has_spatial_coords, goal_orientation_sign, shot_y_norm,
    gk_x_raw, gk_y_raw, gk_y_norm, shot_zone,
    is_clutch_situational, is_clutch_macro, position_group
  FROM `{SILVER_TABLE}`
),
player_known_foot AS (
  SELECT
    player,
    ARRAY_AGG(body_part ORDER BY cnt DESC LIMIT 1)[OFFSET(0)] AS modal_foot
  FROM (
    SELECT player, body_part, COUNT(*) AS cnt
    FROM base
    WHERE body_part IS NOT NULL AND body_part != '' AND player IS NOT NULL AND player != ''
    GROUP BY player, body_part
  )
  GROUP BY player
),
known_left_unimputed AS (
  SELECT player FROM UNNEST([
    'Aarón Martín', 'Adam Karabec', 'Allan Okello', 'Alphonso Davies',
    'André Ayew', 'Angelo Stiller', 'Antonín Barák', 'Isaac Romero',
    'Karol Świderski', 'Keven Schlotterbeck', 'Matías Soulé', 'Maxwel Cornet',
    'Nico Paz', 'Randy Nteka', 'Rayan Philippe', 'Sven Mijnans'
  ]) AS player
),
enriched AS (
  SELECT
    b.*,
    CASE
      WHEN b.outcome = 'scored' THEN 'scored'
      WHEN NOT b.has_spatial_coords THEN 'missed_unclassified'
      WHEN b.gkCoordinates IS NULL OR b.gkCoordinates = '' THEN 'saved_by_gk'
      ELSE 'off_target_or_post'
    END AS detailed_outcome,
    CASE
      WHEN NOT b.has_spatial_coords THEN NULL
      WHEN b.gkCoordinates IS NULL OR b.gkCoordinates = '' THEN b.shot_zone
      WHEN b.gk_y_norm <= -0.1 THEN 'L'
      WHEN b.gk_y_norm >= 0.1 THEN 'R'
      ELSE 'C'
    END AS gk_zone,
    CASE
      WHEN b.body_part IS NOT NULL AND b.body_part != '' THEN b.body_part
      WHEN pf.modal_foot IS NOT NULL THEN pf.modal_foot
      WHEN b.player IN (SELECT player FROM known_left_unimputed) THEN 'left-foot'
      WHEN b.has_spatial_coords THEN 'right-foot'
      ELSE NULL
    END AS body_part_clean
  FROM base b
  LEFT JOIN player_known_foot pf
    ON b.player = pf.player
)
SELECT
  e.*,
  CASE
    WHEN NOT e.has_spatial_coords OR e.body_part_clean IS NULL THEN NULL
    WHEN e.shot_zone = 'C' THEN 'Center'
    WHEN (e.body_part_clean = 'right-foot' AND e.shot_zone = 'L')
      OR (e.body_part_clean = 'left-foot' AND e.shot_zone = 'R') THEN 'Natural'
    ELSE 'Opposite'
  END AS tactical_corner,
  CURRENT_TIMESTAMP() AS _silver_loaded_at
FROM enriched e;
"""


def main() -> None:
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    job_config = bigquery.QueryJobConfig(
        labels={"datacloud": "antigravity", "domain": "po", "layer": "silver"}
    )
    query_job = client.query(SILVER_ENRICH_DDL, job_config=job_config)
    query_job.result()

    check_sql = f"""
    SELECT
      COUNTIF(has_spatial_coords) AS spatial_total,
      COUNTIF(has_spatial_coords AND detailed_outcome = 'scored') AS spatial_scored,
      COUNTIF(has_spatial_coords AND detailed_outcome = 'saved_by_gk') AS spatial_saved,
      COUNTIF(has_spatial_coords AND detailed_outcome = 'off_target_or_post') AS spatial_off_post,
      COUNTIF(has_spatial_coords AND body_part_clean = 'right-foot') AS spatial_right_foot,
      COUNTIF(has_spatial_coords AND body_part_clean = 'left-foot') AS spatial_left_foot,
      COUNTIF(has_spatial_coords AND (body_part_clean IS NULL OR gk_zone IS NULL OR shot_zone IS NULL)) AS spatial_nulls
    FROM `{SILVER_TABLE}`
    """
    summary = dict(list(client.query(check_sql, job_config=job_config).result())[0])
    print(f"[Silver E2-T03] Job ID: {query_job.job_id}")
    print(f"[Silver E2-T03] Resumo Validado: {summary}")


if __name__ == "__main__":
    main()
