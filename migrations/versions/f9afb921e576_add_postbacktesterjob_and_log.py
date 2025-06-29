"""Add PostbackTesterJob and Log

Revision ID: f9afb921e576
Revises: 7146f3062f9c
Create Date: 2025-06-12 03:55:29.849412

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9afb921e576'
down_revision = '7146f3062f9c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('postback_tester_job',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('url_template', sa.Text(), nullable=False),
    sa.Column('interval', sa.Integer(), nullable=False),
    sa.Column('duration', sa.Integer(), nullable=False),
    sa.Column('parameters', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('postback_tester_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=True),
    sa.Column('response_code', sa.Integer(), nullable=True),
    sa.Column('response_text', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['postback_tester_job.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('postback_tester_log')
    op.drop_table('postback_tester_job')
    # ### end Alembic commands ###
