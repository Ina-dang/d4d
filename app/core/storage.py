"""SQLite에 보고서를 보관하고 버전 검사와 검토 변경을 하나의 트랜잭션으로 처리한다."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.schemas import Report


class VersionConflict(Exception):
    """검토자가 읽은 이후 보고서가 바뀌어 변경을 다시 검토해야 한다."""


class Store:
    """동기 저장소. 비동기 실행 흐름에서는 asyncio.to_thread로 호출한다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """성공 시 커밋, 오류 시 롤백하고 어느 경우든 연결을 닫는다."""
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, report: Report) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO reports VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (report.id, report.model_dump_json()),
            )

    def get(self, report_id: str) -> Report | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM reports WHERE id=?", (report_id,)).fetchone()
        return Report.model_validate_json(row[0]) if row else None

    def recent(self) -> list[Report]:
        with self.connect() as db:
            rows = db.execute("SELECT body FROM reports ORDER BY rowid DESC LIMIT 30").fetchall()
        return [Report.model_validate_json(row[0]) for row in rows]

    def mutate(self, report_id: str, version: int, change: Callable[[Report], None]) -> Report:
        """같은 버전의 변경만 원자적으로 저장해 오래된 검토의 덮어쓰기를 막는다."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise KeyError(report_id)
            report = Report.model_validate_json(row[0])
            if report.version != version:
                raise VersionConflict
            if report.status in {"running", "failed"}:
                raise ValueError("실행 중이거나 실패한 보고서는 검토할 수 없습니다.")
            change(report)
            report.version += 1
            db.execute(
                "UPDATE reports SET body=? WHERE id=?", (report.model_dump_json(), report_id)
            )
        return report
