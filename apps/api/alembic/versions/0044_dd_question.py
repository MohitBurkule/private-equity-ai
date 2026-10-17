"""management Q&A log for a deal: questions, answers, and the document an answer cites

Revision ID: 0044
Revises: 0043
"""
import sqlalchemy as sa

from alembic import op

revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dd_question',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=False),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('dd_request.id'), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('document_id', sa.String(length=64), sa.ForeignKey('document.id'), nullable=True),
        sa.Column('asked_at', sa.String(length=40), nullable=False),
        sa.Column('answered_at', sa.String(length=40), nullable=True),
    )
    op.create_index(op.f('ix_dd_question_tenant_id'), 'dd_question', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_dd_question_deal'), 'dd_question', ['deal'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_dd_question_deal'), table_name='dd_question')
    op.drop_index(op.f('ix_dd_question_tenant_id'), table_name='dd_question')
    op.drop_table('dd_question')
