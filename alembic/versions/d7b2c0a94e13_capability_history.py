"""keep every capability measurement, flag one current (S12.5)

`put_capability` overwrote in place, so re-running a variety destroyed the
verdict it disagreed with -- the one thing a reader wants to compare a new
measurement against, and the one a project whose subject is *models changing
over time* can least afford to lose.

Every measurement is now kept. One row per identity carries `current = 1` and
is what routing and the published table read; the rest are history and are
never deleted. The unique constraint becomes a **partial** unique index over
current rows only.

Nothing is destroyed, so nothing needs protecting from destruction: the
deliberate gesture is promotion, not overwrite. Same instinct as the
append-only corpus, as an adjudication never editing a measurement, and as an
invalidated protocol being kept with its status rather than removed.

Revision ID: d7b2c0a94e13
Revises: c3f8a1e5d904
Create Date: 2026-11-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7b2c0a94e13"
down_revision: Union[str, Sequence[str], None] = "c3f8a1e5d904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows are the only measurement there is, so they are current.
    with op.batch_alter_table("capability") as b:
        b.add_column(sa.Column("current", sa.Boolean(), nullable=False,
                               server_default=sa.text("1")))
    op.create_index("ix_capability_current", "capability", ["current"])

    # SQLite cannot drop a named unique *constraint* in place, so the table is
    # rebuilt. `batch_alter_table` does that by copying -- which is why the
    # column above is added first and in its own batch: the copy has to carry
    # it.
    with op.batch_alter_table("capability") as b:
        b.drop_constraint("uq_capability_identity", type_="unique")

    op.create_index("uq_capability_current", "capability",
                    ["model", "tag", "role", "method_version", "script"],
                    unique=True, sqlite_where=sa.text("current = 1"))


def downgrade() -> None:
    # Only current rows can survive: the old constraint cannot hold history.
    op.execute("DELETE FROM capability WHERE current = 0")
    op.drop_index("uq_capability_current", table_name="capability")
    op.drop_index("ix_capability_current", table_name="capability")
    with op.batch_alter_table("capability") as b:
        b.create_unique_constraint(
            "uq_capability_identity",
            ["model", "tag", "role", "method_version", "script"])
        b.drop_column("current")
