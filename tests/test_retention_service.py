from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import text

from app.models import Check, DailyAggregate
from app.services.retention import RetentionService


class _Query:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count

    def filter(self, *_args, **_kwargs):
        return self

    def delete(self, synchronize_session=False):
        assert synchronize_session is False
        return self.deleted_count


class _SessionStub:
    def __init__(self, bind, deleted_checks: int = 2, deleted_aggregates: int = 3):
        self.bind = bind
        self._deleted_checks = deleted_checks
        self._deleted_aggregates = deleted_aggregates
        self.commit_calls = 0

    def query(self, model):
        if model is Check:
            return _Query(self._deleted_checks)
        if model is DailyAggregate:
            return _Query(self._deleted_aggregates)
        raise AssertionError(f"unexpected model: {model}")

    def commit(self):
        self.commit_calls += 1


def test_cleanup_runs_vacuum_with_autocommit_for_sqlite() -> None:
    calls: list[tuple[str, object | None]] = []

    class _Conn:
        def execution_options(self, **kwargs):
            calls.append(("execution_options", kwargs.get("isolation_level")))
            return self

        def execute(self, statement):
            calls.append(("execute", statement))

        def __enter__(self):
            calls.append(("enter", None))
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit", None))

    class _Bind:
        dialect = SimpleNamespace(name="sqlite")

        def connect(self):
            calls.append(("connect", None))
            return _Conn()

    session = _SessionStub(bind=_Bind())
    report = RetentionService().cleanup(session, run_vacuum=True)

    assert session.commit_calls == 1
    assert report["vacuum"] is True
    assert ("connect", None) in calls
    assert ("execution_options", "AUTOCOMMIT") in calls
    assert any(name == "execute" and str(payload) == str(text("VACUUM")) for name, payload in calls)


def test_cleanup_skips_vacuum_for_non_sqlite() -> None:
    class _Bind:
        dialect = SimpleNamespace(name="postgresql")

        def connect(self):
            raise AssertionError("connect should not be called for non-sqlite dialect")

    session = _SessionStub(bind=_Bind())
    report = RetentionService().cleanup(session, run_vacuum=True)

    assert session.commit_calls == 1
    assert report["vacuum"] is False
