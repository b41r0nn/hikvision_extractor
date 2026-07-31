"""add usuario audit columns updated_by updated_at

Revision ID: ea4c5fd67b9f
Revises: f3321bd4c48b
Create Date: 2026-07-31 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea4c5fd67b9f'
down_revision: Union[str, Sequence[str], None] = 'f3321bd4c48b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agrega columnas de auditoría updated_by/updated_at a usuarios.

    updated_by se guarda como Integer sin foreign key real para evitar
    problemas de SQLite con self-referential ALTER TABLE. La aplicación
    controla la integridad referencial al asignar ids de usuarios existentes.
    """
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.add_column(
            sa.Column('updated_by', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False)
        )


def downgrade() -> None:
    """Elimina columnas de auditoría de usuarios."""
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.drop_column('updated_by')
        batch_op.drop_column('updated_at')
