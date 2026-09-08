"""
数据库迁移工具模块
支持跨数据库类型的数据导出与导入（如 SQLite ↔ MySQL ↔ PostgreSQL）

导出策略：
- 使用 SQLAlchemy 反射获取表结构
- 遍历所有表读取数据
- 序列化为 JSON 格式（兼容性好、易于调试）

导入策略：
- 先禁用外键约束（如适用）
- 按拓扑顺序清空表（避免外键冲突）
- 批量插入数据
- 恢复外键约束
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine

from app.db.database_factory import DatabaseFactory
from app.utils import ExceptionUtils
from app.utils.string_utils import StringUtils


class _CustomJSONEncoder(json.JSONEncoder):
    """处理 datetime/date/Decimal 等不可直接 JSON 序列化的类型"""

    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, bytes):
            return o.decode("utf-8", errors="replace")
        return super().default(o)


def _serialize_value(value: Any) -> Any:
    """将数据库值序列化为 JSON 兼容类型"""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _deserialize_value(value: Any) -> Any:
    """将 JSON 值反序列化为数据库可接受类型（保持原样，由 SQLAlchemy 自动处理）"""
    return value


def get_all_table_names(engine: Engine) -> list[str]:
    """获取数据库中所有表名"""
    inspector = inspect(engine)
    return inspector.get_table_names()


def _quote_identifier(engine: Engine, name: str) -> str:
    """根据数据库方言返回正确的标识符引号"""
    if DatabaseFactory.is_mysql(engine):
        return f"`{name}`"
    return f'"{name}"'


def get_table_data(engine: Engine, table_name: str, limit: int | None = None) -> list[dict[str, Any]]:
    """读取指定表的所有数据"""
    with engine.connect() as conn:
        # 使用 text() 构造查询，表名通过方言引号处理，limit 转为整数
        safe_limit = int(limit) if limit is not None else None
        quoted = _quote_identifier(engine, table_name)
        sql = f"SELECT * FROM {quoted}"  # nosec B608
        if safe_limit is not None:
            sql += f" LIMIT {safe_limit}"  # nosec B608
        result = conn.execute(text(sql))
        columns = result.keys()
        rows = []
        for row in result:
            rows.append({col: _serialize_value(val) for col, val in zip(columns, row, strict=False)})
        return rows


def export_database(
    engine: Engine, include_tables: list[str] | None = None, exclude_tables: list[str] | None = None
) -> dict[str, Any]:
    """
    导出数据库中所有表的数据

    :param engine: 源数据库引擎
    :param include_tables: 仅导出这些表（默认全部）
    :param exclude_tables: 排除这些表（默认无）
    :return: 包含元数据和表数据的字典
    """
    table_names = get_all_table_names(engine)
    exclude = set(exclude_tables or [])
    if include_tables:
        table_names = [t for t in table_names if t in include_tables]
    table_names = [t for t in table_names if t not in exclude]

    export_data = {
        "meta": {
            "dialect": engine.url.drivername,
            "exported_at": datetime.now().isoformat(),
        },
        "tables": {},
    }

    for table_name in table_names:
        try:
            rows = get_table_data(engine, table_name)
            # 统一 SIZE 相关字段为 bigint（字节数），兼容老 SQLite 中的字符串如 "27.72G"
            if table_name == "SEARCH_RESULT_INFO" or table_name == "CONFIG_SITE":
                for row in rows:
                    size_val = row.get("SIZE")
                    if isinstance(size_val, str):
                        row["SIZE"] = StringUtils.num_filesize(size_val)
            elif table_name == "SITE_BRUSH_TASK":
                for row in rows:
                    size_val = row.get("SEED_SIZE")
                    if isinstance(size_val, str):
                        row["SEED_SIZE"] = StringUtils.num_filesize(size_val)
            export_data["tables"][table_name] = rows
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            export_data["tables"][table_name] = {"error": str(e)}

    return export_data


def _sort_tables_topological(engine: Engine, table_names: list[str]) -> list[str]:
    """
    按外键依赖关系对表进行拓扑排序（被依赖的表在前）
    这样清空数据时可以先清空子表，再清空父表；插入时可以先插入父表，再插入子表。
    """
    metadata = MetaData()
    metadata.reflect(bind=engine, only=table_names)

    # SQLAlchemy 的 sorted_tables 已经按依赖顺序排好（父表在前，子表在后）
    sorted_names = [t.name for t in metadata.sorted_tables]
    # 只保留在 table_names 中的表
    return [t for t in sorted_names if t in table_names]


def import_database(
    engine: Engine,
    data: dict[str, Any],
    include_tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
    batch_size: int = 1000,
    clear_before_import: bool = True,
):
    """
    将导出的数据导入到目标数据库

    :param engine: 目标数据库引擎
    :param data: export_database 返回的数据字典
    :param include_tables: 仅导入这些表（默认全部）
    :param exclude_tables: 排除这些表（默认无）
    :param batch_size: 批量插入大小
    :param clear_before_import: 导入前是否清空目标表
    """
    tables_data = data.get("tables", {})
    table_names = list(tables_data.keys())

    exclude = set(exclude_tables or [])
    if include_tables:
        table_names = [t for t in table_names if t in include_tables]
    table_names = [t for t in table_names if t not in exclude]

    # 获取目标数据库中真实存在的表
    existing_tables = set(get_all_table_names(engine))
    table_names = [t for t in table_names if t in existing_tables]

    # 拓扑排序：父表在前，子表在后（插入时需要）
    sorted_insert = _sort_tables_topological(engine, table_names)
    # 清空顺序反过来：先清空子表，再清空父表
    sorted_clear = list(reversed(sorted_insert))

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # 1. 禁用外键检查（MySQL/SQLite 支持）
            if DatabaseFactory.is_mysql(engine):
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            elif DatabaseFactory.is_sqlite(engine):
                conn.execute(text("PRAGMA foreign_keys = OFF"))
            elif DatabaseFactory.is_postgresql(engine):
                # PostgreSQL 没有全局外键开关，需要逐表处理
                pass

            # 2. 清空表
            if clear_before_import:
                for table_name in sorted_clear:
                    rows = tables_data.get(table_name)
                    if isinstance(rows, dict) and "error" in rows:
                        continue
                    if not rows:
                        continue
                    try:
                        quoted_table = _quote_identifier(engine, table_name)
                        conn.execute(text(f"DELETE FROM {quoted_table}"))  # nosec B608
                    except Exception as e:
                        ExceptionUtils.exception_traceback(e)

            # 3. 插入数据
            metadata = MetaData()
            metadata.reflect(bind=engine, only=sorted_insert)
            sa_tables = {t.name: t for t in metadata.sorted_tables}

            for table_name in sorted_insert:
                rows = tables_data.get(table_name)
                if isinstance(rows, dict) and "error" in rows:
                    continue
                if not rows:
                    continue

                sa_table = sa_tables.get(table_name)
                if sa_table is None:
                    continue

                # 只插入目标表实际存在的列：备份文件可能来自不同版本，
                # 多余列直接过滤，避免新旧版本 schema 差异导致整行插入失败
                insert_columns = set(sa_table.columns.keys())

                # 获取需要截断的列（避免 MySQL Data too long 错误）
                truncate_columns = {}
                for col in sa_table.columns:
                    col_len = getattr(col.type, "length", None)
                    if col_len is not None:
                        truncate_columns[col.name] = col_len

                # 分批插入，单条捕获异常跳过有问题的行
                for i in range(0, len(rows), batch_size):
                    batch = rows[i : i + batch_size]
                    for row in batch:
                        if truncate_columns:
                            new_row = {}
                            for k, v in row.items():
                                if k not in insert_columns:
                                    continue
                                max_len = truncate_columns.get(k)
                                if max_len is not None and isinstance(v, str) and len(v) > max_len:
                                    new_row[k] = v[:max_len]
                                else:
                                    new_row[k] = v
                            row = new_row
                        else:
                            row = {k: v for k, v in row.items() if k in insert_columns}
                        if not row:
                            continue
                        try:
                            conn.execute(sa_table.insert(), [row])
                        except Exception as e:
                            # 跳过有问题的行，避免中断整个导入流程
                            ExceptionUtils.exception_traceback(e)

            # 4. 恢复外键检查
            if DatabaseFactory.is_mysql(engine):
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            elif DatabaseFactory.is_sqlite(engine):
                conn.execute(text("PRAGMA foreign_keys = ON"))

            trans.commit()
        except Exception:
            trans.rollback()
            raise


def export_to_file(
    engine: Engine, filepath: str, include_tables: list[str] | None = None, exclude_tables: list[str] | None = None
):
    """导出数据库到 JSON 文件"""
    data = export_database(engine, include_tables=include_tables, exclude_tables=exclude_tables)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, cls=_CustomJSONEncoder)


def import_from_file(
    engine: Engine,
    filepath: str,
    include_tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
    batch_size: int = 1000,
    clear_before_import: bool = True,
):
    """从 JSON 文件导入数据到数据库"""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    import_database(
        engine,
        data,
        include_tables=include_tables,
        exclude_tables=exclude_tables,
        batch_size=batch_size,
        clear_before_import=clear_before_import,
    )


def migrate_database(
    source_engine: Engine, target_engine: Engine, exclude_tables: list[str] | None = None, batch_size: int = 1000
):
    """
    便捷方法：直接从源数据库迁移到目标数据库
    要求目标数据库表结构已经通过 Alembic/Base.metadata.create_all() 创建好
    """
    data = export_database(source_engine, exclude_tables=exclude_tables)
    import_database(target_engine, data, exclude_tables=exclude_tables, batch_size=batch_size)
