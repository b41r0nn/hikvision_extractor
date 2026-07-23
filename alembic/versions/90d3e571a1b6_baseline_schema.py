"""baseline schema

Revision ID: 90d3e571a1b6
Revises:
Create Date: 2026-07-23 14:52:04.163535

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90d3e571a1b6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # turnos
    op.create_table(
        'turnos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(), nullable=False),
        sa.Column('hora_entrada', sa.Time(), nullable=False),
        sa.Column('hora_salida', sa.Time(), nullable=True),
        sa.Column('tolerancia_minutos', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # empleados
    op.create_table(
        'empleados',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(), nullable=True),
        sa.Column('nombre', sa.String(), nullable=False),
        sa.Column('departamento', sa.String(), nullable=True),
        sa.Column('turno_id', sa.Integer(), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('hora_entrada', sa.Time(), nullable=True),
        sa.Column('tolerancia_minutos', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['turno_id'], ['turnos.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', name='uq_empleados_employee_id'),
    )
    op.create_index('ix_empleados_employee_id', 'empleados', ['employee_id'], unique=True)

    # festivos
    op.create_table(
        'festivos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('descripcion', sa.String(), nullable=False),
        sa.Column('fuente', sa.String(), nullable=True, server_default='holidays'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fecha', name='uq_festivos_fecha'),
    )
    op.create_index('ix_festivos_fecha', 'festivos', ['fecha'], unique=True)

    # registros_asistencia
    op.create_table(
        'registros_asistencia',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empleado_id', sa.String(), nullable=True),
        sa.Column('nombre_empleado', sa.String(), nullable=True),
        sa.Column('fecha', sa.Date(), nullable=True),
        sa.Column('hora', sa.Time(), nullable=True),
        sa.Column('tipo_evento', sa.String(), nullable=True),
        sa.Column('evento_raw', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_registros_asistencia_empleado_id', 'registros_asistencia', ['empleado_id'])
    op.create_index('ix_registros_asistencia_fecha', 'registros_asistencia', ['fecha'])

    # configuracion
    op.create_table(
        'configuracion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clave', sa.String(), nullable=False),
        sa.Column('valor', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clave', name='uq_configuracion_clave'),
    )
    op.create_index('ix_configuracion_clave', 'configuracion', ['clave'], unique=True)

    # permisos
    op.create_table(
        'permisos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(), nullable=False),
        sa.Column('descripcion', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nombre', name='uq_permisos_nombre'),
    )
    op.create_index('ix_permisos_nombre', 'permisos', ['nombre'], unique=True)

    # roles
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nombre', name='uq_roles_nombre'),
    )

    # rol_permiso
    op.create_table(
        'rol_permiso',
        sa.Column('rol_id', sa.Integer(), nullable=False),
        sa.Column('permiso_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['permiso_id'], ['permisos.id'], ),
        sa.ForeignKeyConstraint(['rol_id'], ['roles.id'], ),
        sa.PrimaryKeyConstraint('rol_id', 'permiso_id'),
    )

    # usuarios
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('rol_id', sa.Integer(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('requiere_cambio_password', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['rol_id'], ['roles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username', name='uq_usuarios_username'),
    )
    op.create_index('ix_usuarios_username', 'usuarios', ['username'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_usuarios_username', table_name='usuarios')
    op.drop_table('usuarios')
    op.drop_table('rol_permiso')
    op.drop_table('roles')
    op.drop_index('ix_permisos_nombre', table_name='permisos')
    op.drop_table('permisos')
    op.drop_index('ix_configuracion_clave', table_name='configuracion')
    op.drop_table('configuracion')
    op.drop_index('ix_registros_asistencia_fecha', table_name='registros_asistencia')
    op.drop_index('ix_registros_asistencia_empleado_id', table_name='registros_asistencia')
    op.drop_table('registros_asistencia')
    op.drop_index('ix_festivos_fecha', table_name='festivos')
    op.drop_table('festivos')
    op.drop_index('ix_empleados_employee_id', table_name='empleados')
    op.drop_table('empleados')
    op.drop_table('turnos')
