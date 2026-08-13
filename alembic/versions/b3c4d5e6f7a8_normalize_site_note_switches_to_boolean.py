"""normalize_site_note_switches_to_boolean

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-06-23

"""

import json
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def has_table(table_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return False
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


_SWITCH_KEYS = ("parse", "message", "chrome", "proxy", "subtitle", "tag", "public")


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("y", "yes", "true", "1")
    return bool(value)


def upgrade() -> None:
    if not has_table("CONFIG_SITE"):
        return
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT ID, NOTE FROM CONFIG_SITE")).fetchall()
    for row in rows:
        note_raw = row.NOTE or "{}"
        try:
            note = json.loads(note_raw)
        except Exception:
            continue
        if not isinstance(note, dict):
            continue
        changed = False
        for key in _SWITCH_KEYS:
            if key in note:
                new_value = _to_bool(note[key])
                if note[key] != new_value:
                    note[key] = new_value
                    changed = True
        if changed:
            conn.execute(
                sa.text("UPDATE CONFIG_SITE SET NOTE = :note WHERE ID = :id"),
                {"note": json.dumps(note, ensure_ascii=False), "id": row.ID},
            )


def downgrade() -> None:
    pass
