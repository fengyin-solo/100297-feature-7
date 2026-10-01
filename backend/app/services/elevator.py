"""电梯管理业务规则：困人救援分段建单、逐段落库、收口校验，筛选口径也收在这里。"""
from __future__ import annotations

from typing import Any

from app.services import elevator_rules as rules
from app.store import store

MODULE = "elevator"
# 额定载重/维保单位允许先空着，登记后由「缺资料」标记单独提示补全；
# 编号和类型是台账主键信息，登记时就必须有。
REQUIRED_FIELDS = ["电梯编号", "电梯类型"]
ALL_FIELDS = ["电梯编号", "电梯类型", "额定载重", "层站数", "维保单位", "上次维保", "下次维保日"]
RUNNING_STATUSES = ["正常运行", "维保中", "困人", "检修中"]

# 台账动作只动基础状态；真有困人时一律走救援分段接口。
ACTION_TARGETS = {"安排维保": "维保中", "故障检修": "检修中"}


class ElevatorService:
    # ---- 读取 ---------------------------------------------------------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [rules.serialize_entry(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("电梯编号", ""))]
        if status:
            rows = [row for row in rows if row.get("运行状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def all_entries(self) -> list[dict[str, Any]]:
        return [rules.serialize_entry(row) for row in store.rows(MODULE)]

    def summary(self) -> dict[str, int]:
        """列表页与看板共用的汇总口径。"""
        rows = self.all_entries()
        return {
            "正常运行": sum(1 for row in rows if row["运行状态"] == "正常运行"),
            "维保中": sum(1 for row in rows if row["运行状态"] == "维保中"),
            "检修中": sum(1 for row in rows if row["运行状态"] == "检修中"),
            "待处置困人": sum(1 for row in rows if row["待处置"]),
            "缺资料": sum(1 for row in rows if row["缺资料"]),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return rules.serialize_entry(entry) if entry is not None else None

    # ---- 登记 ---------------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ALL_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        entry["status"] = "正常运行"
        entry["rescues"] = []
        rows.append(entry)
        return rules.serialize_entry(entry), []

    # ---- 台账动作 -----------------------------------------------------------
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电梯 {entry_id} 不存在或已归档"
        if rules.active_rescue(entry) is not None:
            return None, "该电梯有困人救援尚未完成，请先完成到场、解困、复核后再执行其他操作"
        if action == "困人救援":
            return self.start_rescue(entry_id)
        if action not in ACTION_TARGETS:
            return None, f"动作「{action}」不属于电梯管理可执行范围"
        target = ACTION_TARGETS[action]
        entry["status"] = target
        return rules.serialize_entry(entry), f"电梯已{action}，当前状态：{target}"

    # ---- 困人救援：建单 / 续填 / 收口 ---------------------------------------
    def start_rescue(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电梯 {entry_id} 不存在或已归档"
        rescue = rules.active_rescue(entry)
        if rescue is not None:
            # 重复点「困人救援」不另建单，回到原单继续填，已填段落不受影响。
            return rules.serialize_entry(entry), f"已有进行中的困人救援（{rules.rescue_status(rescue)}），请继续填写后续段落"
        rescue_id = max(
            (int(item.get("id", 0)) for item in entry.get("rescues") or []),
            default=0,
        ) + 1
        entry.setdefault("rescues", []).append({
            "id": rescue_id,
            "started_at": _now(),
            "completed_at": None,
            "stages": {},
        })
        return rules.serialize_entry(entry), "困人救援已建单，请先记录到场信息"

    def save_stage(
        self,
        entry_id: int,
        rescue_id: int | None,
        stage: str,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """落库当前段落。上一段没填不许跳段；本段缺字段不收口，数据原样保留。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电梯 {entry_id} 不存在或已归档"
        rescue = self._pick_rescue(entry, rescue_id)
        if rescue is None:
            return None, "该电梯没有进行中的困人救援，请先建单"
        if stage not in rules.STAGE_ORDER:
            return None, f"「{stage}」不是救援记录段落，允许的段落为：{'、'.join(rules.STAGE_ORDER)}"
        stages = rescue.setdefault("stages", {})
        expected = rules.next_stage(rescue)
        if expected is None:
            return None, "三段记录已填齐，请执行复核收口，不要重复填写"
        if stage != expected:
            return None, f"救援需按到场、解困、复核顺序记录，请先填写「{expected}」"
        fields = rules.STAGE_FIELDS[stage]
        cleaned: dict[str, str] = {}
        missing: list[str] = []
        for key, label in fields.items():
            raw = values.get(key, values.get(label, ""))
            text = "" if raw is None else str(raw).strip()
            if not text:
                missing.append(label)
            cleaned[key] = text
        if missing:
            # 不返回 entry：本段没落库，前序段落依旧在，页面可接着改。
            return None, f"「{stage}」段落未填完：{'、'.join(missing)}"
        cleaned["saved_at"] = _now()
        stages[stage] = cleaned
        current = rules.rescue_status(rescue)
        if current == "待收口":
            message = "到场、解困、复核均已记录，请执行复核收口"
        else:
            message = f"「{stage}」已保存，请继续记录「{current.removeprefix('待')}」"
        return rules.serialize_entry(entry), message

    def complete_rescue(self, entry_id: int, rescue_id: int | None) -> tuple[dict[str, Any] | None, str]:
        """复核收口：哪一段没填完都不许收口。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电梯 {entry_id} 不存在或已归档"
        rescue = self._pick_rescue(entry, rescue_id)
        if rescue is None:
            return None, "该电梯没有进行中的困人救援，无需收口"
        pending_stage = rules.next_stage(rescue)
        if pending_stage is not None:
            return None, f"救援尚未记录完整，「{pending_stage}」段落没填完，不许收口"
        rescue["completed_at"] = _now()
        entry["status"] = "正常运行"
        return rules.serialize_entry(entry), "困人救援已复核收口，电梯恢复正常运行"

    def _pick_rescue(self, entry: dict[str, Any], rescue_id: int | None) -> dict[str, Any] | None:
        rescue = rules.active_rescue(entry)
        if rescue is None:
            return None
        if rescue_id is not None and int(rescue.get("id", 0)) != rescue_id:
            return None
        return rescue


def _now() -> str:
    """当前时间戳，集中一处方便以后换时区实现。"""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")
