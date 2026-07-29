"""add_configuracion_correo

Revision ID: f3321bd4c48b
Revises: 25e5f322addf
Create Date: 2026-07-29 09:01:34.150868

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3321bd4c48b'
down_revision: Union[str, Sequence[str], None] = '25e5f322addf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'configuracion_correo',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('host', sa.String(), nullable=False),
        sa.Column('puerto', sa.Integer(), nullable=False),
        sa.Column('usuario', sa.String(), nullable=False),
        sa.Column('password_encriptado', sa.String(), nullable=False),
        sa.Column('remitente_nombre', sa.String(), nullable=True),
        sa.Column('seguridad', sa.String(), nullable=False, server_default='starttls'),
        sa.Column('updated_by', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_configuracion_correo_una_sola_fila'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('configuracion_correo')
