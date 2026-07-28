"""add turno_horario

Revision ID: 25e5f322addf
Revises: 90d3e571a1b6
Create Date: 2026-07-28 08:01:21.613368

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25e5f322addf'
down_revision: Union[str, Sequence[str], None] = '90d3e571a1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea la tabla turno_horario con versionado por vigencia."""
    op.create_table(
        'turno_horario',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('turno_id', sa.Integer(), nullable=False),
        sa.Column('dia_semana', sa.SmallInteger(), nullable=False),
        sa.Column('hora_entrada', sa.Time(), nullable=False),
        sa.Column('tolerancia_minutos', sa.Integer(), nullable=False),
        sa.Column('vigente_desde', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['turno_id'], ['turnos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_turno_horario_turno_dia_vigencia',
        'turno_horario',
        ['turno_id', 'dia_semana', 'vigente_desde'],
        unique=True,
    )


def downgrade() -> None:
    """Elimina la tabla turno_horario."""
    op.drop_index('ix_turno_horario_turno_dia_vigencia', table_name='turno_horario')
    op.drop_table('turno_horario')
