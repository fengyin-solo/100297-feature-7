"""电梯困人救援的统一口径：分段规则与状态判定都收在这里。

列表页、详情页、运营看板都只能用这里的函数判定困人状态，避免同一部梯在不同页面
给出两种说法。状态不靠人传，一律从救援记录推导：

- 没有任何救援记录            → 暂无
- 有未收口的救援              → 待到场 / 待解困 / 待复核 / 待收口
- 最近一条救援已复核收口      → 已完成（历史记录仍保留在 rescues 里）
"""
from __future__ import annotations

from typing import Any

# 救援三段，顺序不可跨越：解困必须先到场，复核必须先解困。
STAGE_ORDER = ["到场", "解困", "复核"]

# 每一段必须填齐的字段，key 给接口用，label 直接落库方便回显。
STAGE_FIELDS: dict[str, dict[str, str]] = {
    "到场": {"arrived_at": "到场时间", "rescuers": "到场救援人员"},
    "解困": {"released_at": "解困时间", "trapped_count": "被困人数", "resolution": "现场处置情况"},
    "复核": {"reviewed_at": "复核时间", "reviewer": "复核人", "review_note": "复核意见"},
}

# 空着就要在列表里单独标出的资料项。
INFO_FIELDS = ["额定载重", "维保单位"]


def rescues_of(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """一部电梯的全部困人救援记录，按建单先后排列。"""
    return list(entry.get("rescues") or [])


def active_rescue(entry: dict[str, Any]) -> dict[str, Any] | None:
    """取进行中（还没收口）的救援；没有就返回 None。"""
    for rescue in reversed(rescues_of(entry)):
        if not rescue.get("completed_at"):
            return rescue
    return None


def saved_stages(rescue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return rescue.get("stages") or {}


def rescue_status(rescue: dict[str, Any] | None) -> str:
    """困人状态的唯一取法：暂无 / 待到场 / 待解困 / 待复核 / 待收口 / 已完成。"""
    if rescue is None:
        return "暂无"
    if rescue.get("completed_at"):
        return "已完成"
    stages = saved_stages(rescue)
    for stage in STAGE_ORDER:
        if not stages.get(stage):
            return f"待{stage}"
    # 三段都填齐但还没点收口，仍算待处置，不许当成已完成。
    return "待收口"


def next_stage(rescue: dict[str, Any]) -> str | None:
    """当前该填哪一段；三段齐了返回 None（等着收口）。"""
    stages = saved_stages(rescue)
    for stage in STAGE_ORDER:
        if not stages.get(stage):
            return stage
    return None


def running_status(entry: dict[str, Any]) -> str:
    """设备运行状态：只要有进行中的救援就一定是困人，其余取台账基础状态。"""
    if active_rescue(entry) is not None:
        return "困人"
    return str(entry.get("status") or "正常运行")


def missing_info(entry: dict[str, Any]) -> list[str]:
    """额定载重、维保单位这类关键资料缺哪项就标出哪项。"""
    return [
        field
        for field in INFO_FIELDS
        if not str(entry.get(field) or "").strip()
    ]


def serialize_rescue(rescue: dict[str, Any]) -> dict[str, Any]:
    """给前端的救援记录：在原始数据上补一个推导出来的困人状态。"""
    data = dict(rescue)
    data["rescue_status"] = rescue_status(rescue)
    data["next_stage"] = next_stage(rescue)
    data["stages"] = dict(saved_stages(rescue))
    return data


def serialize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """给前端的电梯记录：运行状态、困人状态、缺资料标记全部现场推导，
    列表接口和详情接口走同一个出口，口径天然一致。"""
    data = {key: value for key, value in entry.items() if key != "rescues"}
    rescue = active_rescue(entry)
    data["rescues"] = [serialize_rescue(item) for item in rescues_of(entry)]
    data["active_rescue"] = serialize_rescue(rescue) if rescue else None
    data["运行状态"] = running_status(entry)
    data["困人状态"] = rescue_status(rescue)
    data["缺资料"] = missing_info(entry)
    data["待处置"] = rescue is not None
    return data
