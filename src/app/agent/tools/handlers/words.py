"""识别词管理工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext


def words_list(ctx: ToolContext) -> ToolResult:
    """查询识别词配置"""
    try:
        groups = ctx.words_service.get_all_word_groups() or []
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询识别词失败: {e}")
    items = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        items.append(
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "type": g.get("type"),
                "seasons": g.get("seasons"),
                "words_count": len(g.get("words") or []),
                "words": g.get("words") or [],
            }
        )
    return ToolResult(success=True, data={"total": len(items), "items": items})


def words_add(
    ctx: ToolContext,
    word_type: int,
    replaced: str,
    replace: str = "",
    group_id: int = -1,
    offset: str = "",
    season: int | None = None,
    enabled: bool = True,
    tmdb_id: int | None = None,
    tmdb_type: str = "",
    confirmed: bool = False,
) -> ToolResult:
    """新增/更新识别词（屏蔽/替换/集偏移），有副作用需确认"""
    replaced = (replaced or "").strip()
    if not replaced:
        return ToolResult(success=False, error="被替换词不能为空")
    if int(word_type or 0) not in (1, 2, 3):
        return ToolResult(success=False, error="识别词类型仅支持：1=屏蔽，2=替换，3=集偏移")
    if not confirmed:
        type_name = {1: "屏蔽", 2: "替换", 3: "集偏移"}.get(int(word_type), "识别词")
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "add_word",
                "message": f"新增{type_name}识别词「{replaced}」需确认",
                "group_id": group_id,
            },
        )
    try:
        gid = int(group_id or -1)
        if gid == 0:
            if not tmdb_id:
                return ToolResult(success=False, error="新建识别词组需要 tmdb_id")
            ctx.words_service.add_word_group(tmdb_id=int(tmdb_id), tmdb_type=tmdb_type or "tv")
            groups = ctx.words_service.get_all_word_groups() or []
            target = next((g for g in groups if isinstance(g, dict) and str(g.get("id", "")).isdigit()), None)
            gid = int(target["id"]) if target and str(target.get("id", "")).isdigit() else -1
        ctx.words_service.add_or_edit_word(
            wid=0,
            gid=gid,
            group_type="1",
            replaced=replaced,
            replace=replace or "",
            front="",
            back="",
            offset=offset or "",
            whelp="",
            wtype=str(int(word_type)),
            season=int(season) if season is not None else -2,
            enabled=1 if enabled else 0,
            regex=0,
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存识别词失败: {e}")
    return ToolResult(success=True, data={"replaced": replaced, "group_id": gid, "message": "识别词已保存"})


def words_toggle(ctx: ToolContext, word_ids: list[int], enabled: bool, confirmed: bool = False) -> ToolResult:
    """启用/禁用识别词，有副作用需确认"""
    ids = [str(int(i)) for i in (word_ids or []) if int(i) > 0]
    if not ids:
        return ToolResult(success=False, error="识别词 ID 不能为空")
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "toggle_words",
                "message": f"{'启用' if enabled else '禁用'} {len(ids)} 条识别词需确认",
            },
        )
    try:
        ctx.words_service.toggle_words(ids_info=ids, flag="on" if enabled else "off")
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"切换识别词状态失败: {e}")
    return ToolResult(success=True, data={"updated": len(ids), "enabled": enabled})


def words_delete(
    ctx: ToolContext,
    word_ids: list[int] | None = None,
    group_id: int | None = None,
    confirmed: bool = False,
) -> ToolResult:
    """删除识别词/识别词组，有副作用需确认"""
    ids = [str(int(i)) for i in (word_ids or []) if int(i) > 0]
    gid = int(group_id) if group_id else 0
    if not ids and not gid:
        return ToolResult(success=False, error="请提供要删除的识别词 ID 或词组 ID")
    if not confirmed:
        target = f"识别词组 {gid}" if gid else f"{len(ids)} 条识别词"
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "delete_words", "message": f"删除 {target} 需确认"},
        )
    try:
        if gid:
            ctx.words_service.delete_word_group(gid)
        else:
            ctx.words_service.delete_words_by_ids(ids)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"删除识别词失败: {e}")
    return ToolResult(success=True, data={"deleted": gid or len(ids), "message": "已删除"})
