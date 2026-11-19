from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Patient accounts now sign in with their ABHA address (the username) and cover every hospital,
    # so an account is no longer tied to one patient row. Accounts linked the old way are deactivated.
    op.execute("UPDATE users SET is_active = 0 WHERE patient_id IS NOT NULL")
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_patient_id', type_='foreignkey')
        batch_op.drop_constraint('uq_users_patient_id', type_='unique')
        batch_op.drop_column('patient_id')


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('patient_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_users_patient_id', ['patient_id'])
        batch_op.create_foreign_key('fk_users_patient_id', 'patients', ['patient_id'], ['id'])
