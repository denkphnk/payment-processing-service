"""add outbox status

Revision ID: c22d07ad0bea
Revises: 4ccb9e7a50fe
Create Date: 2026-11-13 21:57:13.209611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c22d07ad0bea'
down_revision: Union[str, Sequence[str], None] = '4ccb9e7a50fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status_enum = sa.Enum(
        "pending",
        "published",
        "failed",
        name="outbox_status",
    )

    status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "outbox",
        sa.Column(
            "status",
            status_enum,
            server_default="pending",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("outbox", "status")

    sa.Enum(
        "pending",
        "published",
        "failed",
        name="outbox_status",
    ).drop(op.get_bind(), checkfirst=True)