"""电梯管理业务规则：状态流转、字段校验、困人救援分段记录与筛选口径都收在这里。

困人救援是一件必须讲清楚的事：
- 报警、到场、解困、复核四段，任何一段必填项没填完都不许收口；
- 每一段都即时落库，中途断线/关页面，已填的段不会丢，重新进场接着填；
- 电梯对外只暴露一个由救援记录派生的「困人状态」，列表与详情共用同一口径；
- 没有进行中的困人记录时，困人状态是「暂无」，而不是「正常」。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "elevator"
REQUIRED_FIELDS = ["电梯编号", "电梯类型", "额定载重"]
PROFILE_FIELDS = ["额定载重", "维保单位"]
STATUS_ORDER = ["正常运行", "维保中", "困人", "检修中"]

# 常规动作只保留维保与检修；困人救援走专门的分段记录接口，不再做瞬时跳转。
ACTION_RULES = {"安排维保": "维保中", "故障检修": "检修中"}
NEGATIVE_ACTIONS: list[str] = []

# 救援四段：key 固定，顺序即处置顺序；每段列出该段收口前必填的项。
RESCUE_STAGE_FIELDS: dict[str, list[str]] = {
    "报警": ["报警时间"],
    "到场": ["到场时间", "到场人员"],
    "解困": ["解困时间", "被困人数"],
    "复核": ["复核时间", "复核结论"],
}
RESCUE_STAGES = list(RESCUE_STAGE_FIELDS.keys())

# 立案即记录报警段，处置人按到场、解困、复核三段往下填；
# 标签按「已经完成到哪一段」派生，当前段没填完不会提前显示完成。
STAGE_STATUS_LABELS = {
    "到场": "已报警·待到场",
    "解困": "救援中·已到场",
    "复核": "已解困·待复核",
}
NO_RESCUE_STATUS = "暂无"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def missing_profile_fields(entry: dict[str, Any]) -> list[str]:
    """额定载重、维保单位是救援联络与处置的关键资料，空着就单独标出来。"""
    return [field for field in PROFILE_FIELDS if not str(entry.get(field) or "").strip()]


def active_rescue(entry: dict[str, Any]) -> dict[str, Any] | None:
    """取该电梯当前未收口的救援记录；历史记录只留在 rescues 里备查。"""
    rescue = entry.get("active_rescue")
    if isinstance(rescue, dict) and rescue.get("finished_at") in (None, ""):
        return rescue
    # 种子数据/旧数据可能只在 rescues 里留了未收口记录，这里兜底找回。
    for item in entry.get("rescues", []) or []:
        if isinstance(item, dict) and item.get("finished_at") in (None, ""):
            entry["active_rescue"] = item
            return item
    return None


def rescue_stage(entry: dict[str, Any]) -> str | None:
    rescue = active_rescue(entry)
    if rescue is None:
        return None
    stage = str(rescue.get("stage") or "")
    return stage if stage in RESCUE_STAGE_FIELDS else RESCUE_STAGES[0]


def rescue_status(entry: dict[str, Any]) -> str:
    """困人状态的唯一口径：有进行中的救援按已完成到的段派生，没有就是「暂无」。"""
    rescue = active_rescue(entry)
    if rescue is None:
        return NO_RESCUE_STATUS
    return STAGE_STATUS_LABELS.get(rescue.get("stage"), "已报警·待到场")


def present_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """列表与详情都走这里，保证两处困人状态永远对得上。"""
    view = dict(entry)
    rescue = active_rescue(entry)
    view["困人状态"] = rescue_status(entry)
    view["困人中"] = rescue is not None
    view["待补资料"] = missing_profile_fields(entry)
    if rescue is not None:
        view["active_rescue"] = _rescue_view(rescue)
    else:
        view.pop("active_rescue", None)
    return view


def _rescue_view(rescue: dict[str, Any]) -> dict[str, Any]:
    """给前端的救援记录视图：补齐每段是否完成、当前段必填项等派生信息。"""
    view = deepcopy(rescue)
    view["阶段顺序"] = list(RESCUE_STAGES)
    view["各段必填"] = {stage: list(fields) for stage, fields in RESCUE_STAGE_FIELDS.items()}
    stages = view.setdefault("stages", {})
    current_index = RESCUE_STAGES.index(rescue.get("stage") or RESCUE_STAGES[1])
    for index, stage in enumerate(RESCUE_STAGES):
        saved = stages.get(stage) or {}
        required = RESCUE_STAGE_FIELDS[stage]
        blank = [field for field in required if not str(saved.get(field) or "").strip()]
        stages[stage] = {
            "fields": {field: saved.get(field, "") for field in required},
            "required": required,
            "missing": blank,
            "completed": not blank and bool(saved),
        }
        if stage == rescue.get("stage"):
            current_index = index
    view["当前段序号"] = current_index
    view["当前段必填"] = list(
        RESCUE_STAGE_FIELDS.get(rescue.get("stage") or RESCUE_STAGES[1], [])
    )
    return view


class ElevatorService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("电梯编号", ""))]
        if status:
            rows = [row for row in rows if rescue_status(row) == status or row.get("status") == status]
        # 资料待补与困中电梯优先排到前面，方便先处置。
        rows = sorted(
            rows,
            key=lambda row: (active_rescue(row) is None, bool(missing_profile_fields(row))),
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return [present_entry(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return present_entry(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 维保单位、层站数等非必填项也原样收下，空着由列表打「资料待补」标。
        for field in ("电梯类型", "层站数", "维保单位", "上次维保", "下次维保日"):
            entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = False
        entry["abnormal"] = False
        entry["rescues"] = []
        rows.append(entry)
        return present_entry(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电梯 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于电梯管理可执行范围（困人救援请走分段处置）"
        if active_rescue(entry) is not None:
            return None, "困人救援尚未复核收口，不能安排维保或检修，请先完成救援记录"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target == "维保中"
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return present_entry(entry), f"电梯已{action}"

    # ------------------------------------------------------------------
    # 困人救援：分段记录、逐段落库、断点续填、全部复核完成才收口
    # ------------------------------------------------------------------

    def start_rescue(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电梯 {entry_id} 不存在或已归档"
        rescue = active_rescue(entry)
        if rescue is not None:
            return None, f"该电梯已有进行中的救援记录（当前段：{rescue.get('stage')}），请继续填写而不是重新立案"

        rescue = {
            "id": max((int(item.get("id", 0)) for item in entry.get("rescues", [])), default=0) + 1,
            "started_at": _now_text(),
            "finished_at": "",
            # 立案即落报警段，处置人从到场段开始填。
            "stage": "到场",
            "救援前状态": entry.get("status", STATUS_ORDER[0]),
            "stages": {"报警": {"报警时间": _now_text()}},
        }
        entry.setdefault("rescues", []).append(rescue)
        entry["active_rescue"] = rescue
        entry["status"] = "困人"
        entry["pending"] = True
        entry["abnormal"] = True
        return present_entry(entry), "困情已立案，报警段已保存，请继续填写到场信息"

    def save_rescue_stage(
        self, entry_id: int, stage: str, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电梯 {entry_id} 不存在或已归档"
        rescue = active_rescue(entry)
        if rescue is None:
            return None, "该电梯没有进行中的困人救援，无法保存救援分段"
        if stage not in RESCUE_STAGE_FIELDS:
            return None, f"救援分段「{stage}」不存在，可选：{'、'.join(RESCUE_STAGES)}"

        current = rescue.get("stage") or RESCUE_STAGES[1]
        current_index = RESCUE_STAGES.index(current)
        target_index = RESCUE_STAGES.index(stage)
        if target_index < current_index:
            return None, f"「{stage}」段已经封存，救援按到场、解困、复核顺序推进，不能回退覆盖"
        if target_index > current_index:
            # 段在后端推进：只有当前段必填项补齐后才会进入下一段，提前提交没有入口。
            return None, f"请先完成当前的「{current}」段，不能提前填写{stage}段"

        # 与该段已有内容合并：网络重试/断线续填时不会把先前填好的字段冲掉。
        saved = dict(rescue.setdefault("stages", {}).get(stage) or {})
        saved.update(self._clean_values(stage, values))
        rescue["stages"][stage] = saved

        blank = [field for field in RESCUE_STAGE_FIELDS[stage] if not str(saved.get(field) or "").strip()]
        if blank:
            rescue["stage"] = stage
            # 只落库不收口：已填的字段先保住，重新进场可以接着填。
            return present_entry(entry), f"「{stage}」段已暂存，还差：{'、'.join(blank)}，补齐后才能进入下一段"

        if stage == RESCUE_STAGES[-1]:
            rescue["stage"] = stage
            rescue["finished_at"] = _now_text()
            entry["active_rescue"] = None
            entry["status"] = rescue.get("救援前状态") or STATUS_ORDER[0]
            entry["pending"] = entry["status"] == "维保中"
            entry["abnormal"] = False
            return present_entry(entry), "复核段已保存，困人救援四段全部完成并收口，电梯状态已恢复"

        next_stage = RESCUE_STAGES[target_index + 1]
        rescue["stage"] = next_stage
        rescue["stages"].setdefault(next_stage, {})
        return present_entry(entry), f"「{stage}」段已完成并保存，已进入{next_stage}段"

    @staticmethod
    def _clean_values(stage: str, values: dict[str, Any]) -> dict[str, str]:
        return {
            field: str(values.get(field) or "").strip()
            for field in RESCUE_STAGE_FIELDS[stage]
            if field in values
        }

    def rescue_board(self) -> dict[str, Any]:
        """维保看板用：待处置台数随救援分段推进实时变化。"""
        rows = store.rows(MODULE)
        # 救援未收口时当前段只可能是到场/解困/复核，即三个待处置环节。
        pending_stages = RESCUE_STAGES[1:]
        stage_counts = {stage: 0 for stage in pending_stages}
        pending_elevators: list[dict[str, Any]] = []
        for row in rows:
            stage = rescue_stage(row)
            if stage not in pending_stages:
                continue
            stage_counts[stage] += 1
            pending_elevators.append({
                "id": int(row.get("id", 0)),
                "电梯编号": row.get("电梯编号", ""),
                "当前段": stage,
                "困人状态": rescue_status(row),
            })
        missing = [
            {"id": int(row.get("id", 0)), "电梯编号": row.get("电梯编号", ""), "缺失字段": missing_profile_fields(row)}
            for row in rows
            if missing_profile_fields(row)
        ]
        return {
            "待处置台数": len(pending_elevators),
            "待处置电梯": pending_elevators,
            "分段台数": stage_counts,
            "资料待补台数": len(missing),
            "资料待补明细": missing,
        }
