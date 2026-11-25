from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

from persistence import normalize_database_url


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Set DATABASE_URL in .env before initializing PostgreSQL.")
    engine = create_engine(normalize_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 5})
    schema = (ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
    with engine.raw_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema)
        connection.commit()
    print("PostgreSQL tables are ready.")


if __name__ == "__main__":
    main()
