"""capability records for dialect attestation (S12.5)

What a model can do with one variety, in one role -- generation, discrimination
or comprehension. A byproduct of scanning somebody else: measuring one engine
puts every panel member through controls for the same family, so the finding is
reusable and paying for it twice is waste.

Mirrors `qualification`, which is already a per-(instrument, language)
competence cache keyed by method version.

**This table routes; it never vouches.** It decides who is asked first.
Controls in the live run decide whether an answer is believed, and they run
every time regardless of what is stored here. A stale row costs wasted routing,
never a wrong verdict. Nothing may read it to skip a control.

Revision ID: c3f8a1e5d904
Revises: a1c4e9d7b2f0
Create Date: 2026-11-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3f8a1e5d904"
down_revision: Union[str, Sequence[str], None] = "a1c4e9d7b2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        # generation | discrimination | comprehension. In the key because the
        # three dissociate: a row qualified for discrimination says nothing
        # about generation and must not be read across.
        sa.Column("role", sa.String(length=32), nullable=False),
        # In the key because one variety written in two scripts is two
        # measurements: `sr-me-cyrl` is identified cleanly where `sr-me-latn`
        # cannot be told from Bosnian at all.
        sa.Column("script", sa.String(length=8), nullable=True),
        sa.Column("qualified", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("probes", sa.JSON(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("method_version", sa.String(length=32), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model", "tag", "role", "method_version", "script",
                            name="uq_capability_identity"),
    )
    op.create_index("ix_capability_model", "capability", ["model"])
    op.create_index("ix_capability_tag", "capability", ["tag"])
    op.create_index("ix_capability_role", "capability", ["role"])
    op.create_index("ix_capability_method_version", "capability", ["method_version"])
    op.create_index("ix_capability_measured_at", "capability", ["measured_at"])
    op.create_index("ix_capability_tag_role", "capability", ["tag", "role"])


def downgrade() -> None:
    op.drop_index("ix_capability_tag_role", table_name="capability")
    op.drop_index("ix_capability_measured_at", table_name="capability")
    op.drop_index("ix_capability_method_version", table_name="capability")
    op.drop_index("ix_capability_role", table_name="capability")
    op.drop_index("ix_capability_tag", table_name="capability")
    op.drop_index("ix_capability_model", table_name="capability")
    op.drop_table("capability")
