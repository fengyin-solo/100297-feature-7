"""电梯管理接口：维护电梯，覆盖安排维保、困人救援（分段记录）、故障检修等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.elevator import (
    NO_RESCUE_STATUS,
    RESCUE_STAGES,
    ElevatorService,
)

router = APIRouter(prefix="/api/elevator", tags=["电梯管理"])

service = ElevatorService()

LIST_FIELDS = ["电梯编号", "电梯类型", "额定载重", "层站数", "维保单位", "上次维保", "下次维保日", "困人状态"]
STATUSES = ["正常运行", "维保中", "困人", "检修中"]
# 困人状态由救援记录派生：暂无、已报警·待到场、救援中·已到场、已解困·待复核。
RESCUE_STATUS_FILTERS = [
    NO_RESCUE_STATUS,
    "已报警·待到场",
    "救援中·已到场",
    "已解困·待复核",
]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按电梯编号检索"),
    status: str | None = Query(default=None, description="运行状态或困人状态，如 困人、已解困·待复核、暂无"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按电梯编号与状态过滤电梯管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/rescue/board")
def rescue_board() -> dict[str, Any]:
    """维保看板：困人救援待处置台数与资料待补清单，随救援推进实时变化。"""
    return service.rescue_board()


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条电梯明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"电梯 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条电梯，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="电梯已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条电梯执行安排维保、故障检修；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/rescue/start", response_model=ActionResult)
def start_rescue(entry_id: int, payload: EntryPayload) -> ActionResult:
    """困人立案：报警段自动落库，随后从到场段开始分段填写。

    已有进行中救援时拒绝重复立案，避免把处置到一半的记录冲掉。
    """
    entry, message = service.start_rescue(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/rescue/stages/{stage}", response_model=ActionResult)
def save_rescue_stage(entry_id: int, stage: str, payload: EntryPayload) -> ActionResult:
    """保存救援的某一段（到场、解困、复核）。

    段内必填项没填全时只暂存不收口；全部段填完并复核后才收口。
    每次保存都即时落库，断线或关掉页面后可从当前段接着填。
    """
    if stage not in RESCUE_STAGES:
        return ActionResult(
            ok=False,
            message=f"救援分段「{stage}」不存在，可选：{'、'.join(RESCUE_STAGES)}",
        )
    entry, message = service.save_rescue_stage(entry_id, stage, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出电梯管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "elevator", "total": total, "items": items}
