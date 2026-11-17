"""add is_favorite to photos

Revision ID: b37c3182b49a
Revises: 701da9212420
Create Date: 2026-11-14 02:13:02.078007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b37c3182b49a'
down_revision: Union[str, Sequence[str], None] = '701da9212420'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE photos ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT FALSE;")

def downgrade() -> None:
    op.execute("ALTER TABLE photos DROP COLUMN is_favorite;")
