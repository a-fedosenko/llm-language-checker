"""variant scoring columns (S6)

`variant_evidence` existed from the start but could only ever hold the literal
"untested": nothing measured a variant. S6 adds the two columns that make it a
measurement -- the marker rate and the detail of how it was established.

Revision ID: a1c4e9d7b2f0
Revises: fb431915efe4
Note for databases created before this migration existed: `create_all()` makes
the tables without an `alembic_version` row, so `alembic upgrade head` will try
to re-run the baseline and fail with "table job already exists". Stamp it once
first:

    alembic stamp fb431915efe4 && alembic upgrade head

Create Date: 2026-09-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c4e9d7b2f0"
down_revision: Union[str, Sequence[str], None] = "fb431915efe4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("result", sa.Column("s_variant", sa.Float(), nullable=True))
    op.add_column("result", sa.Column("variant_detail", sa.JSON(), nullable=True))
    op.create_index("ix_result_variant_evidence", "result", ["variant_evidence"])


def downgrade() -> None:
    op.drop_index("ix_result_variant_evidence", table_name="result")
    op.drop_column("result", "variant_detail")
    op.drop_column("result", "s_variant")
