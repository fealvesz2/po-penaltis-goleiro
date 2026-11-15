import base64
import json
import os
import urllib.request
import zipfile
from pathlib import Path

from google.cloud import bigquery

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "dev-plataforma-geral")
DATASET_ID = "po_bronze"
TABLE_ID = "raw_kaggle_penalties_sofascore"
LOCATION = "southamerica-east1"

KAGGLE_DATASET_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "saadmbt/16k-football-penalties-dataset-gk-vs-shooter"
)
DEFAULT_CRED_PATH = Path(
    r"C:\Users\felip\OneDrive\One Note\vault-second-brain\crendencial-api-kaggle.json"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
ZIP_PATH = RAW_DIR / "16k-football-penalties.zip"
CSV_PATH = RAW_DIR / "penalties_dataset_sofascore.csv"

BRONZE_LABELS = {
    "datacloud": "antigravity",
    "domain": "po",
    "layer": "bronze",
}

SCHEMA = [
    bigquery.SchemaField("match_id", "INT64"),
    bigquery.SchemaField("match_date", "DATE"),
    bigquery.SchemaField("competition_stage", "STRING"),
    bigquery.SchemaField("home_team", "STRING"),
    bigquery.SchemaField("away_team", "STRING"),
    bigquery.SchemaField("home_score", "INT64"),
    bigquery.SchemaField("away_score", "INT64"),
    bigquery.SchemaField("penalty_type", "STRING"),
    bigquery.SchemaField("period", "STRING"),
    bigquery.SchemaField("minute", "INT64"),
    bigquery.SchemaField("second", "INT64"),
    bigquery.SchemaField("team_shooting", "STRING"),
    bigquery.SchemaField("player", "STRING"),
    bigquery.SchemaField("position", "STRING"),
    bigquery.SchemaField("shot_type", "STRING"),
    bigquery.SchemaField("outcome", "STRING"),
    bigquery.SchemaField("technique", "STRING"),
    bigquery.SchemaField("body_part", "STRING"),
    bigquery.SchemaField("xg", "FLOAT64"),
    bigquery.SchemaField("player_location_x", "FLOAT64"),
    bigquery.SchemaField("player_location_y", "FLOAT64"),
    bigquery.SchemaField("end_location_x", "FLOAT64"),
    bigquery.SchemaField("end_location_y", "FLOAT64"),
    bigquery.SchemaField("end_location_z", "FLOAT64"),
    bigquery.SchemaField("goalkeeper_name", "STRING"),
    bigquery.SchemaField("goalkeeper_id", "INT64"),
    bigquery.SchemaField("gkCoordinates", "STRING"),
]


def load_kaggle_credentials(cred_path: Path) -> tuple[str, str]:
    with cred_path.open("r", encoding="utf-8") as fh:
        creds = json.load(fh)
    return creds["username"], creds["key"]


def download_and_extract_kaggle(cred_path: Path) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    username, api_key = load_kaggle_credentials(cred_path)
    basic_token = base64.b64encode(f"{username}:{api_key}".encode("utf-8")).decode("ascii")

    req = urllib.request.Request(
        KAGGLE_DATASET_URL,
        headers={"Authorization": f"Basic {basic_token}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read()

    ZIP_PATH.write_bytes(payload)
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        zf.extractall(RAW_DIR)

    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Arquivo esperado nao encontrado apos extracao: {CSV_PATH}")

    print(f"[Kaggle] Download concluido ({len(payload)} bytes) -> {CSV_PATH}")
    return CSV_PATH


def load_csv_to_bigquery_bronze(csv_path: Path) -> None:
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        allow_quoted_newlines=True,
        encoding="UTF-8",
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        labels=BRONZE_LABELS,
    )

    with csv_path.open("rb") as source_file:
        load_job = client.load_table_from_file(
            source_file,
            table_ref,
            location=LOCATION,
            job_config=job_config,
        )

    load_job.result()
    table = client.get_table(table_ref)
    table.labels = BRONZE_LABELS
    table = client.update_table(table, ["labels"])

    print(f"[BigQuery] Job ID: {load_job.job_id}")
    print(f"[BigQuery] Tabela: {table_ref} | Labels: {table.labels}")
    print(f"[BigQuery] Linhas carregadas: {table.num_rows} | Colunas: {len(table.schema)}")


def main() -> None:
    cred_path = Path(os.environ.get("KAGGLE_CRED_PATH", str(DEFAULT_CRED_PATH)))
    csv_path = CSV_PATH if CSV_PATH.exists() else download_and_extract_kaggle(cred_path)
    load_csv_to_bigquery_bronze(csv_path)


if __name__ == "__main__":
    main()
