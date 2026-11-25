from __future__ import annotations

import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from persistence import normalize_database_url


ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Set DATABASE_URL in .env before seeding PostgreSQL.")

    papers = read_csv(ROOT / "data" / "papers.csv")
    sources = read_csv(ROOT / "data" / "source_registry.csv")
    engine = create_engine(normalize_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 5})
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO research_papers (domain, year, title, authors, venue, method, relevance, url)
            VALUES (:domain, :year, :title, :authors, :venue, :method, :relevance, :url)
            ON CONFLICT (url) DO UPDATE SET
                domain = EXCLUDED.domain,
                year = EXCLUDED.year,
                title = EXCLUDED.title,
                authors = EXCLUDED.authors,
                venue = EXCLUDED.venue,
                method = EXCLUDED.method,
                relevance = EXCLUDED.relevance
        """), [{**row, "year": int(row["year"])} for row in papers])
        connection.execute(text("""
            INSERT INTO data_sources (source_key, provider, title, url, frequency, coverage, limitations)
            VALUES (:source_key, :provider, :title, :url, :frequency, :coverage, :limitations)
            ON CONFLICT (source_key) DO UPDATE SET
                provider = EXCLUDED.provider,
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                frequency = EXCLUDED.frequency,
                coverage = EXCLUDED.coverage,
                limitations = EXCLUDED.limitations
        """), sources)
    print(f"Seeded {len(papers)} cited research papers and {len(sources)} data-source records.")


if __name__ == "__main__":
    main()
