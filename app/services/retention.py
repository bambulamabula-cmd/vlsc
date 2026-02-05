from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Check, DailyAggregate


class RetentionService:
    """Data retention and storage compaction routines."""

    def cleanup(
        self,
        db: Session,
        raw_checks_days: int = 30,
        aggregate_days: int = 365,
        run_vacuum: bool = True,
    ) -> dict[str, int | bool]:
        raw_checks_days = min(max(raw_checks_days, 7), 30)
        aggregate_days = min(max(aggregate_days, 30), 365)

        now = datetime.now(timezone.utc)
        checks_cutoff = now - timedelta(days=raw_checks_days)
        aggregate_cutoff = now.date() - timedelta(days=aggregate_days)

        deleted_checks = (
            db.query(Check)
            .filter(Check.checked_at < checks_cutoff)
            .delete(synchronize_session=False)
        )
        deleted_aggregates = (
            db.query(DailyAggregate)
            .filter(DailyAggregate.day < aggregate_cutoff)
            .delete(synchronize_session=False)
        )

        db.commit()

        vacuum_ran = False
        if run_vacuum:
            bind = db.bind
            if bind is not None and bind.dialect.name == "sqlite":
                # SQLite VACUUM must run outside a transaction.
                with bind.connect() as conn:
                    conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
                vacuum_ran = True

        return {
            "deleted_checks": int(deleted_checks),
            "deleted_aggregates": int(deleted_aggregates),
            "vacuum": vacuum_ran,
            "raw_checks_days": raw_checks_days,
            "aggregate_days": aggregate_days,
        }
