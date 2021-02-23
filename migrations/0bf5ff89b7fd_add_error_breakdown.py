"""add_error_breakdown

Revision ID: 0bf5ff89b7fd
Revises: a93f710bb8b5
Create Date: 2021-01-26 19:42:24.773967

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0bf5ff89b7fd"
down_revision = "a93f710bb8b5"
branch_labels = ()
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "landing_job",
        sa.Column(
            "error_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("landing_job", "error_breakdown")
    # ### end Alembic commands ###
