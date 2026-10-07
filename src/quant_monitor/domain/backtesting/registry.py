"""可执行模型目录；模型身份来自实现，避免 CLI 重复维护版本。"""

from dataclasses import dataclass

from .attention_model import AttentionScoreAllocationModel
from .dividend_yield_model import DividendYieldPercentileAllocationModel
from .swing import PriceSwingModel


@dataclass(frozen=True)
class ModelRegistration:
    """模型实现、入口与输入条件；不包含外部数据或运行状态。"""

    implementation: type
    entry: str
    requirements: str


MODEL_REGISTRY = (
    ModelRegistration(
        AttentionScoreAllocationModel,
        "--strategy-record",
        "前复权日线与关注度参数",
    ),
    ModelRegistration(
        DividendYieldPercentileAllocationModel,
        "--strategy-record",
        "前复权日线和当时可得的真实历史股息率",
    ),
    ModelRegistration(
        PriceSwingModel,
        "--study",
        "冻结不复权日线、现金成本与分红；支持独立资金分账",
    ),
)
