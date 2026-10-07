"""冻结研究装配：保留完整 JSON 证据，由 Agent 撰写飞书报告。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..application.backtest_study import BacktestStudyService, fingerprint
from ..application.capital_study import CapitalStudyService
from ..application.ports import ControlPlaneRepository
from ..domain.control_plane import BacktestRunRecord
from ..domain.models import Instrument, InstrumentType
from ..infrastructure.frozen_history import FrozenCSVHistoryRepository
from ..infrastructure.strategy_catalog import StrategyCatalog


def run_study(
    root: Path,
    path: Path,
    data_dir: Path,
    control: ControlPlaneRepository,
    catalog: StrategyCatalog,
) -> Path:
    """校验冻结规格、登记运行并写出模型结果与代码指纹。"""
    specification = json.loads(path.read_text(encoding="utf-8"))
    handlers = {1: BacktestStudyService, 2: CapitalStudyService}
    required = {
        "study_id",
        "symbol",
        "name",
        "exchange",
        "model_id",
        "model_version",
        "history_path",
        "history_sha256",
    }
    if not isinstance(specification, dict) or not required <= specification.keys():
        raise ValueError("冻结研究规格必须包含身份、模型及行情来源字段")
    version = specification.get("study_schema_version")
    if type(version) is not int or version not in handlers:
        raise ValueError("不支持的冻结研究规格版本")
    study_id, symbol = str(specification["study_id"]), str(specification["symbol"])
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", study_id) or not re.fullmatch(
        r"\d{6}", symbol
    ):
        raise ValueError("研究 ID 或证券代码格式无效")
    record = catalog.record(study_id)
    if not record.applies_to(symbol) or (
        record.parameters_fingerprint != fingerprint(specification)
        or record.backtest_model_id != specification["model_id"]
        or record.backtest_model_version != specification["model_version"]
    ):
        raise ValueError("研究规格与策略目录的模型或参数指纹不一致")
    instrument = Instrument(
        symbol,
        specification["name"],
        specification["exchange"],
        InstrumentType.STOCK,
        (),
        "",
        "",
        500,
        enabled=False,
    )
    started_at = datetime.now().astimezone()
    run_id = f"{study_id}-{started_at:%Y%m%dT%H%M%S%f}"
    result_path = data_dir / "backtests" / symbol / f"{run_id}.json"
    pending = BacktestRunRecord(
        run_id,
        study_id,
        symbol,
        started_at,
        None,
        "running",
        str(result_path.relative_to(root)),
    )
    control.save_backtest(pending)
    try:
        history = FrozenCSVHistoryRepository(
            root / specification["history_path"],
            symbol,
            specification["history_sha256"],
        )
        packet = handlers[version](history).run(instrument, specification)
        packet["generated_at"] = started_at.isoformat()
        packet["source_sha256"] = {
            str(source.relative_to(root)): hashlib.sha256(
                source.read_bytes()
            ).hexdigest()
            for source in (
                root / "src/quant_monitor/domain/backtesting/swing.py",
                root / "src/quant_monitor/application/backtest_study.py",
                root / "src/quant_monitor/infrastructure/frozen_history.py",
                root / "src/quant_monitor/domain/backtesting/capital.py",
                root / "src/quant_monitor/application/capital_study.py",
            )
        }
        result_path.parent.mkdir(parents=True, exist_ok=True)
        with result_path.open("x", encoding="utf-8") as handle:
            json.dump(
                packet,
                handle,
                ensure_ascii=False,
                indent=2,
                default=str,
                allow_nan=False,
            )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        control.save_backtest(
            replace(
                pending,
                status="failed",
                completed_at=datetime.now().astimezone(),
                error=str(error),
            )
        )
        raise ValueError(f"冻结研究回测失败：{error}") from error
    reference = "selected" if version == 1 else specification["reference_configuration"]
    metrics = packet["comparisons"][reference]["full"]["metrics"]
    control.save_backtest(
        replace(
            pending,
            status="completed",
            completed_at=datetime.now().astimezone(),
            total_return=metrics["total_return"],
            max_drawdown=metrics["max_drawdown"],
            trade_count=metrics["trade_count"],
        )
    )
    return result_path
