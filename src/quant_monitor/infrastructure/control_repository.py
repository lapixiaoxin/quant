"""研究选择、策略回测、分析和报告的 SQLite 控制面仓储。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.control_plane import (
    AnalysisRequest,
    BacktestRunRecord,
    ReportRecord,
    SelectionRunRecord,
)


class SQLiteControlPlaneRepository:
    """用一个轻量事务库管理跨模块运行索引。"""

    schema_version = 1

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
            current_version = int(row["version"] or 0)
            if current_version > self.schema_version:
                raise RuntimeError(
                    "控制面数据库版本高于当前程序支持版本："
                    f"{current_version} > {self.schema_version}"
                )
            if current_version == 0:
                connection.executescript(
                    """
                    CREATE TABLE analysis_runs (
                        request_id TEXT PRIMARY KEY,
                        requested_at TEXT NOT NULL,
                        completed_at TEXT,
                        trigger TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        symbols_json TEXT NOT NULL,
                        cycles_json TEXT NOT NULL,
                        factors_json TEXT NOT NULL,
                        send INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        error TEXT NOT NULL DEFAULT ''
                    );

                    CREATE TABLE report_records (
                        report_id TEXT PRIMARY KEY,
                        analysis_request_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        report_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        path TEXT NOT NULL,
                        generated_at TEXT NOT NULL,
                        strategy_records_json TEXT NOT NULL,
                        cycles_json TEXT NOT NULL,
                        factors_json TEXT NOT NULL,
                        channels_json TEXT NOT NULL,
                        delivery_status TEXT NOT NULL
                    );

                    CREATE INDEX report_records_symbol_time_idx
                    ON report_records (symbol, generated_at DESC);

                    CREATE TABLE selection_runs (
                        run_id TEXT PRIMARY KEY,
                        universe_id TEXT NOT NULL,
                        horizon TEXT NOT NULL,
                        theme TEXT NOT NULL,
                        requested_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        candidate_count INTEGER NOT NULL,
                        shortlist_count INTEGER NOT NULL,
                        packet_path TEXT NOT NULL,
                        report_path TEXT NOT NULL
                    );

                    CREATE INDEX selection_runs_universe_time_idx
                    ON selection_runs (universe_id, requested_at DESC);

                    CREATE TABLE backtest_runs (
                        run_id TEXT PRIMARY KEY,
                        strategy_record_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        status TEXT NOT NULL,
                        result_path TEXT NOT NULL,
                        total_return REAL,
                        max_drawdown REAL,
                        trade_count INTEGER,
                        error TEXT NOT NULL DEFAULT ''
                    );

                    CREATE INDEX backtest_runs_strategy_time_idx
                    ON backtest_runs (strategy_record_id, started_at DESC);
                    """
                )
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (self.schema_version, datetime.now().astimezone().isoformat()),
                )

    @staticmethod
    def _json(values: object) -> str:
        return json.dumps(values, ensure_ascii=False, sort_keys=True)

    def save_analysis_request(
        self,
        request: AnalysisRequest,
        *,
        status: str = "pending",
    ) -> None:
        packet = request.to_packet()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    request_id, requested_at, trigger, mode, symbols_json,
                    cycles_json, factors_json, send, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    status = excluded.status
                """,
                (
                    request.request_id,
                    request.requested_at.isoformat(),
                    request.trigger.value,
                    request.mode,
                    self._json(packet["symbols"]),
                    self._json(packet["cycles"]),
                    self._json(packet["factor_ids"]),
                    int(request.send),
                    status,
                ),
            )

    def complete_analysis(
        self,
        request_id: str,
        *,
        completed_at: datetime,
        status: str,
        error: str = "",
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_runs
                SET completed_at = ?, status = ?, error = ?
                WHERE request_id = ?
                """,
                (completed_at.isoformat(), status, error, request_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"分析任务不存在：{request_id}")

    def save_report(self, record: ReportRecord) -> None:
        packet = record.to_packet()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO report_records (
                    report_id, analysis_request_id, symbol, report_type,
                    title, path, generated_at, strategy_records_json,
                    cycles_json, factors_json, channels_json, delivery_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.report_id,
                    record.analysis_request_id,
                    record.symbol,
                    record.report_type,
                    record.title,
                    record.path,
                    record.generated_at.isoformat(),
                    self._json(packet["strategy_record_ids"]),
                    self._json(packet["cycles"]),
                    self._json(packet["factor_ids"]),
                    self._json(packet["channels"]),
                    record.delivery_status,
                ),
            )

    def save_selection(self, record: SelectionRunRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO selection_runs (
                    run_id, universe_id, horizon, theme, requested_at,
                    status, candidate_count, shortlist_count,
                    packet_path, report_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.universe_id,
                    record.horizon.value,
                    record.theme,
                    record.requested_at.isoformat(),
                    record.status,
                    record.candidate_count,
                    record.shortlist_count,
                    record.packet_path,
                    record.report_path,
                ),
            )

    def save_backtest(self, record: BacktestRunRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO backtest_runs (
                    run_id, strategy_record_id, symbol, started_at,
                    completed_at, status, result_path, total_return,
                    max_drawdown, trade_count, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.strategy_record_id,
                    record.symbol,
                    record.started_at.isoformat(),
                    (
                        record.completed_at.isoformat()
                        if record.completed_at
                        else None
                    ),
                    record.status,
                    record.result_path,
                    record.total_return,
                    record.max_drawdown,
                    record.trade_count,
                    record.error,
                ),
            )

    def _list(self, table: str, order_by: str) -> list[dict[str, Any]]:
        allowed = {
            "analysis_runs",
            "report_records",
            "selection_runs",
            "backtest_runs",
        }
        if table not in allowed:
            raise ValueError(f"不允许读取控制面表：{table}")
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY {order_by}"  # noqa: S608
            ).fetchall()
        return [dict(row) for row in rows]

    def list_analysis_runs(self) -> list[dict[str, Any]]:
        return self._list("analysis_runs", "requested_at DESC")

    def list_reports(self) -> list[dict[str, Any]]:
        return self._list("report_records", "generated_at DESC")

    def list_selection_runs(self) -> list[dict[str, Any]]:
        return self._list("selection_runs", "requested_at DESC")

    def list_backtest_runs(self) -> list[dict[str, Any]]:
        return self._list("backtest_runs", "started_at DESC")

    def export_snapshot(self) -> dict[str, Any]:
        """提供给静态网页生成器的结构化只读快照。"""

        return {
            "schema_version": self.schema_version,
            "analysis_runs": self.list_analysis_runs(),
            "reports": self.list_reports(),
            "selection_runs": self.list_selection_runs(),
            "backtest_runs": self.list_backtest_runs(),
        }
