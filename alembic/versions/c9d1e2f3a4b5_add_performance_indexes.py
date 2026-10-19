"""add_performance_indexes

Revision ID: c9d1e2f3a4b5
Revises: b7c4e19a2f30
Create Date: 2026-10-19 00:00:00.000000

Agrega índices de performance para acelerar:
- Cálculo de tardanzas acumuladas (turno_horario por turno+dia+vigencia)
- Consultas de configuración por clave
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c9d1e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'b7c4e19a2f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Acelera obtener_horario_vigente(): filtra por turno_id + dia_semana +
    # vigente_desde DESC en calcular_tardanzas_acumulado (N+1 sin cache).
    op.create_index(
        'ix_turno_horario_turno_dia_vigencia',
        'turno_horario',
        ['turno_id', 'dia_semana', 'vigente_desde'],
    )

    # Acelera config_service.get/set_*: la tabla configuracion se consulta
    # por clave en cada extracción, backfill y reporte programado.
    op.create_index(
        'ix_configuracion_clave',
        'configuracion',
        ['clave'],
    )


def downgrade() -> None:
    op.drop_index('ix_configuracion_clave', table_name='configuracion')
    op.drop_index('ix_turno_horario_turno_dia_vigencia', table_name='turno_horario')
