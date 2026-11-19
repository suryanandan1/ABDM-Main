from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRANSACTION_INDEXES = ['consent_id', 'created_at', 'hospital_id', 'kind', 'request_id', 'status', 'transaction_id']


def upgrade() -> None:
    op.drop_table('hip_transactions')
    op.drop_table('hip_link_requests')
    op.drop_table('hiu_patient_summaries')


def downgrade() -> None:
    op.create_table('hip_link_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('patient_id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.String(length=50), nullable=False),
    sa.Column('link_reference', sa.String(length=50), nullable=False),
    sa.Column('abha_address', sa.String(length=100), nullable=False),
    sa.Column('care_context_refs', sa.JSON(), nullable=False),
    sa.Column('otp_hash', sa.String(length=100), nullable=False),
    sa.Column('test_otp', sa.String(length=10), nullable=True),
    sa.Column('otp_expires_at', sa.DateTime(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('link_reference')
    )
    with op.batch_alter_table('hip_link_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hip_link_requests_hospital_id'), ['hospital_id'], unique=False)
    op.create_table('hip_transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('message', sa.String(length=500), nullable=False),
    sa.Column('request_id', sa.String(length=50), nullable=True),
    sa.Column('transaction_id', sa.String(length=50), nullable=True),
    sa.Column('consent_id', sa.String(length=50), nullable=True),
    sa.Column('patient_id', sa.Integer(), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('hip_transactions', schema=None) as batch_op:
        for column in TRANSACTION_INDEXES:
            batch_op.create_index(batch_op.f(f'ix_hip_transactions_{column}'), [column], unique=False)
    op.create_table('hiu_patient_summaries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('patient_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('record_ids', sa.JSON(), nullable=False),
    sa.Column('model', sa.String(length=50), nullable=False),
    sa.Column('generated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('patient_id')
    )
