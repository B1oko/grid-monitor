"""Serial number used to find an inverter again when its IP address changes.

Revision ID: 0006_inverter_serial
Revises: 0005_tariffs
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_inverter_serial"
down_revision: Union[str, None] = "0005_tariffs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inverters", sa.Column("serial_number", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inverters") as batch:
        batch.drop_column("serial_number")
