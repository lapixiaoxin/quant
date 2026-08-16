"""基于 SQLite 的标准化日线历史仓储。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from ...domain.models import (
    DailyBar,
    HistorySummary,
    Instrument,
    MarketBundle,
    ValuationObservation,
)


class SQLiteMarketHistoryRepository:
    """以单文件事务数据库保存中长线研究需要的日线数据。"""

    schema_version = 2

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                    "历史数据库版本高于当前程序支持版本："
                    f"{current_version} > {self.schema_version}"
                )
            if current_version == 0:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS instruments (
                        symbol TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        exchange TEXT NOT NULL,
                        instrument_type TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS daily_bars (
                        symbol TEXT NOT NULL,
                        trading_date TEXT NOT NULL,
                        open REAL NOT NULL,
                        close REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        volume REAL NOT NULL,
                        amount REAL NOT NULL,
                        amplitude_pct REAL NOT NULL,
                        change_pct REAL NOT NULL,
                        turnover_pct REAL NOT NULL,
                        adjustment TEXT NOT NULL,
                        source TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        PRIMARY KEY (symbol, trading_date),
                        FOREIGN KEY (symbol) REFERENCES instruments(symbol)
                    );

                    CREATE INDEX IF NOT EXISTS daily_bars_trading_date_idx
                    ON daily_bars (trading_date);

                    CREATE TABLE IF NOT EXISTS history_syncs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        source TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        first_date TEXT NOT NULL,
                        last_date TEXT NOT NULL,
                        bar_count INTEGER NOT NULL,
                        FOREIGN KEY (symbol) REFERENCES instruments(symbol)
                    );
                    """
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (1, datetime.now().astimezone().isoformat()),
                )
                current_version = 1
            if current_version < 2:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS valuation_observations (
                        valuation_symbol TEXT NOT NULL,
                        observation_date TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        weighting TEXT NOT NULL,
                        history_window TEXT NOT NULL,
                        value REAL NOT NULL,
                        percentile REAL NOT NULL,
                        percentile_20_value REAL NOT NULL,
                        percentile_50_value REAL NOT NULL,
                        percentile_80_value REAL NOT NULL,
                        source TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        PRIMARY KEY (
                            valuation_symbol,
                            observation_date,
                            metric,
                            weighting,
                            history_window
                        )
                    );

                    CREATE INDEX IF NOT EXISTS
                    valuation_observations_date_idx
                    ON valuation_observations (observation_date);
                    """
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (2, datetime.now().astimezone().isoformat()),
                )

    def save_bundle(
        self,
        instrument: Instrument,
        bundle: MarketBundle,
        fetched_at: datetime,
    ) -> None:
        if not bundle.bars:
            raise ValueError(f"{instrument.symbol} 没有可保存的历史日线")
        timestamp = fetched_at.isoformat()
        rows = [
            (
                instrument.symbol,
                bar.trading_date.isoformat(),
                bar.open,
                bar.close,
                bar.high,
                bar.low,
                bar.volume,
                bar.amount,
                bar.amplitude_pct,
                bar.change_pct,
                bar.turnover_pct,
                "qfq",
                bundle.source,
                timestamp,
            )
            for bar in bundle.bars
        ]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO instruments (
                    symbol, name, exchange, instrument_type, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    exchange = excluded.exchange,
                    instrument_type = excluded.instrument_type,
                    updated_at = excluded.updated_at
                """,
                (
                    instrument.symbol,
                    instrument.name,
                    instrument.exchange,
                    instrument.instrument_type.value,
                    timestamp,
                ),
            )
            connection.executemany(
                """
                INSERT INTO daily_bars (
                    symbol, trading_date, open, close, high, low,
                    volume, amount, amplitude_pct, change_pct, turnover_pct,
                    adjustment, source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trading_date) DO UPDATE SET
                    open = excluded.open,
                    close = excluded.close,
                    high = excluded.high,
                    low = excluded.low,
                    volume = excluded.volume,
                    amount = CASE
                        WHEN excluded.amount > 0 THEN excluded.amount
                        ELSE daily_bars.amount
                    END,
                    amplitude_pct = excluded.amplitude_pct,
                    change_pct = excluded.change_pct,
                    turnover_pct = CASE
                        WHEN excluded.turnover_pct > 0
                        THEN excluded.turnover_pct
                        ELSE daily_bars.turnover_pct
                    END,
                    adjustment = excluded.adjustment,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
            connection.execute(
                """
                INSERT INTO history_syncs (
                    symbol, source, fetched_at, first_date, last_date, bar_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument.symbol,
                    bundle.source,
                    timestamp,
                    bundle.bars[0].trading_date.isoformat(),
                    bundle.bars[-1].trading_date.isoformat(),
                    len(bundle.bars),
                ),
            )

    def load_bars(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> tuple[DailyBar, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("历史日线读取数量必须大于 0")
        clauses = ["symbol = ?"]
        parameters: list[object] = [symbol]
        if start_date is not None:
            clauses.append("trading_date >= ?")
            parameters.append(start_date.isoformat())
        if end_date is not None:
            clauses.append("trading_date <= ?")
            parameters.append(end_date.isoformat())
        order = "DESC" if limit is not None else "ASC"
        query = (
            "SELECT trading_date, open, close, high, low, volume, amount, "
            "amplitude_pct, change_pct, turnover_pct "
            "FROM daily_bars WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY trading_date {order}"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self._connect() as connection:
            records = connection.execute(query, parameters).fetchall()
        if limit is not None:
            records.reverse()
        return tuple(
            DailyBar(
                trading_date=date.fromisoformat(row["trading_date"]),
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                volume=float(row["volume"]),
                amount=float(row["amount"]),
                amplitude_pct=float(row["amplitude_pct"]),
                change_pct=float(row["change_pct"]),
                turnover_pct=float(row["turnover_pct"]),
            )
            for row in records
        )

    def save_valuation_observations(
        self,
        observations: tuple[ValuationObservation, ...],
        fetched_at: datetime,
    ) -> None:
        if not observations:
            raise ValueError("没有可保存的指数估值")
        identity = {
            (
                item.valuation_symbol,
                item.metric,
                item.weighting,
                item.history_window,
            )
            for item in observations
        }
        if len(identity) != 1:
            raise ValueError("一次估值保存只能包含同一指数、指标和窗口")
        timestamp = fetched_at.isoformat()
        rows = [
            (
                item.valuation_symbol,
                item.observation_date.isoformat(),
                item.metric,
                item.weighting,
                item.history_window,
                item.value,
                item.percentile,
                item.percentile_20_value,
                item.percentile_50_value,
                item.percentile_80_value,
                item.source,
                item.source_url,
                timestamp,
            )
            for item in observations
        ]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO valuation_observations (
                    valuation_symbol, observation_date, metric, weighting,
                    history_window, value, percentile,
                    percentile_20_value, percentile_50_value,
                    percentile_80_value, source, source_url, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    valuation_symbol, observation_date, metric, weighting,
                    history_window
                ) DO UPDATE SET
                    value = excluded.value,
                    percentile = excluded.percentile,
                    percentile_20_value = excluded.percentile_20_value,
                    percentile_50_value = excluded.percentile_50_value,
                    percentile_80_value = excluded.percentile_80_value,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )

    def load_valuation_observations(
        self,
        valuation_symbol: str,
        *,
        metric: str,
        weighting: str,
        history_window: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[ValuationObservation, ...]:
        clauses = [
            "valuation_symbol = ?",
            "metric = ?",
            "weighting = ?",
            "history_window = ?",
        ]
        parameters: list[object] = [
            valuation_symbol,
            metric,
            weighting,
            history_window,
        ]
        if start_date is not None:
            clauses.append("observation_date >= ?")
            parameters.append(start_date.isoformat())
        if end_date is not None:
            clauses.append("observation_date <= ?")
            parameters.append(end_date.isoformat())
        query = (
            "SELECT valuation_symbol, observation_date, metric, weighting, "
            "history_window, value, percentile, percentile_20_value, "
            "percentile_50_value, percentile_80_value, source, source_url "
            "FROM valuation_observations WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observation_date ASC"
        )
        with self._connect() as connection:
            records = connection.execute(query, parameters).fetchall()
        return tuple(
            ValuationObservation(
                valuation_symbol=str(row["valuation_symbol"]),
                observation_date=date.fromisoformat(row["observation_date"]),
                metric=str(row["metric"]),
                weighting=str(row["weighting"]),
                history_window=str(row["history_window"]),
                value=float(row["value"]),
                percentile=float(row["percentile"]),
                percentile_20_value=float(row["percentile_20_value"]),
                percentile_50_value=float(row["percentile_50_value"]),
                percentile_80_value=float(row["percentile_80_value"]),
                source=str(row["source"]),
                source_url=str(row["source_url"]),
            )
            for row in records
        )

    def summarize(self, symbol: str) -> HistorySummary:
        with self._connect() as connection:
            coverage = connection.execute(
                """
                SELECT
                    COUNT(*) AS bar_count,
                    MIN(trading_date) AS first_date,
                    MAX(trading_date) AS last_date
                FROM daily_bars
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
            latest_sync = connection.execute(
                """
                SELECT source, fetched_at
                FROM history_syncs
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return HistorySummary(
            symbol=symbol,
            bar_count=int(coverage["bar_count"]),
            first_date=(
                date.fromisoformat(coverage["first_date"])
                if coverage["first_date"]
                else None
            ),
            last_date=(
                date.fromisoformat(coverage["last_date"])
                if coverage["last_date"]
                else None
            ),
            last_source=latest_sync["source"] if latest_sync else None,
            updated_at=(
                datetime.fromisoformat(latest_sync["fetched_at"])
                if latest_sync
                else None
            ),
        )
