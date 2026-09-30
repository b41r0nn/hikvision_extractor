"""add_unique_registros_empleado_fecha_hora

Revision ID: b7c4e19a2f30
Revises: ea4c5fd67b9f
Create Date: 2026-09-30 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4e19a2f30'
down_revision: Union[str, Sequence[str], None] = 'ea4c5fd67b9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Elimina duplicados antes de crear el constraint.
    # Conserva el registro con el id menor por cada grupo (empleado_id, fecha, hora).
    op.execute("""
        DELETE FROM registros_asistencia
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM registros_asistencia
            GROUP BY empleado_id, fecha, hora
        )
    """)
    op.create_unique_constraint(
        "uq_registro_empleado_fecha_hora",
        "registros_asistencia",
        ["empleado_id", "fecha", "hora"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_registro_empleado_fecha_hora",
        "registros_asistencia",
        type_="unique",
    )
