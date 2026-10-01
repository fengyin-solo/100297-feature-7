"""电梯管理接口：台账维护之外，困人救援按建单、分段记录、复核收口三个接口组织。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.elevator import ElevatorService

router = APIRouter(prefix="/api/elevator", tags=["电梯管理"])

service = ElevatorService()

RUNNING_STATUSES = ["正常运行", "维保中", "困人", "检修中"]
SUMMARY_LABELS = [
    ("正常运行", "正常运行电梯"),
    ("维保中", "维保电梯"),
    ("检修中", "检修电梯"),
    ("待处置困人", "待处置困人"),
    ("缺资料", "资料待补全"),
]


@router.get("/summary")
def summary() -> dict[str, Any]:
    """列表页与维保看板共用：台数随救援进度实时变化。"""
    counts = service.summary()
    return {
        "items": [
            {"key": key, "label": label, "value": counts.get(key, 0)}
            for key, label in SUMMARY_LABELS
        ]
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按电梯编号检索"),
    status: str | None = Query(default=None, description="正常运行、维保中、困人、检修中"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按电梯编号与运行状态过滤电梯列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in RUNNING_STATUSES:
        raise HTTPException(status_code=400, detail=f"状态「{status}」不在允许范围内")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出电梯管理清单：返回全量数据（含困人状态与救援记录）。"""
    items = service.all_entries()
    return {"module": "elevator", "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条电梯明细（含救援记录与困人状态）；不存在时给出可读的错误说明。"""
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
    """台账动作：安排维保、故障检修，以及建单式的困人救援；
    不允许的动作或进行中救援期间的越权动作都会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.post("/{entry_id}/rescue", response_model=ActionResult)
def start_rescue(entry_id: int) -> ActionResult:
    """发起困人救援：建一张救援单，状态进入困人，等待记录到场。"""
    entry, message = service.start_rescue(entry_id)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.put("/{entry_id}/rescue/stages/{stage}", response_model=ActionResult)
def save_stage(entry_id: int, stage: str, payload: EntryPayload) -> ActionResult:
    """逐段落保存（到场/解困/复核）：必须按顺序、本段填齐才落库，
    落库后中途断线或关掉页面，已填段落仍在，重新进场接着往下填。"""
    rescue_id = payload.values.get("rescue_id")
    entry, message = service.save_stage(
        entry_id,
        int(rescue_id) if rescue_id is not None and str(rescue_id).strip() else None,
        stage,
        payload.values,
    )
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.post("/{entry_id}/rescue/complete", response_model=ActionResult)
def complete_rescue(entry_id: int, payload: EntryPayload | None = None) -> ActionResult:
    """复核收口：三段任何一段没填完都不允许收口。"""
    rescue_id = None
    if payload is not None:
        raw = payload.values.get("rescue_id")
        rescue_id = int(raw) if raw is not None and str(raw).strip() else None
    entry, message = service.complete_rescue(entry_id, rescue_id)
    return ActionResult(ok=entry is not None, message=message, entry=entry)
