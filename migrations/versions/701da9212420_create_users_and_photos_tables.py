"""create users and photos tables

Revision ID: 701da9212420
Revises: 
Create Date: 2026-11-08 21:09:36.351582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '701da9212420'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT now()
    );
    """)

    op.execute("""
    CREATE TABLE photos (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        filename TEXT NOT NULL,
        size INT NOT NULL,
        pic_hash TEXT NOT NULL,
        pic BYTEA NOT NULL,
        created_at TIMESTAMP DEFAULT now()
    );
    """)

    op.execute("""
    CREATE INDEX photos_user_hash_idx ON photos (user_id, pic_hash);    
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE photos
    """)

    op.execute("""
    DROP TABLE users
    """)