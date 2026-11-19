import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for test_id, parameters in bind.execute(sa.text("SELECT id, parameters FROM lab_tests")).all():
        items = json.loads(parameters) if isinstance(parameters, str) else parameters
        if any("loinc_code" in p for p in items or []):
            cleaned = [{k: v for k, v in p.items() if k != "loinc_code"} for p in items]
            bind.execute(sa.text("UPDATE lab_tests SET parameters = :p WHERE id = :id"),
                         {"p": json.dumps(cleaned), "id": test_id})
    with op.batch_alter_table('lab_tests', schema=None) as batch_op:
        batch_op.drop_column('loinc_code')
    with op.batch_alter_table('lab_results', schema=None) as batch_op:
        batch_op.drop_column('loinc_code')
    op.drop_table('term_mappings')


def downgrade() -> None:
    op.create_table('term_mappings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('source_text', sa.String(length=200), nullable=False),
    sa.Column('loinc_code', sa.String(length=20), nullable=False),
    sa.Column('display', sa.String(length=300), nullable=False),
    sa.Column('confirmed_by_id', sa.Integer(), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['confirmed_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hospital_id', 'source_text')
    )
    with op.batch_alter_table('lab_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('loinc_code', sa.String(length=20), nullable=True))
    with op.batch_alter_table('lab_tests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('loinc_code', sa.String(length=20), nullable=True))
