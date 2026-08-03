// ── Configuración ──────────────────────────────────────────────────────────
// Usar el hostname de la URL actual para que funcione tanto en localhost
// como accediendo por IP desde otro dispositivo de la red, sin hardcodear.
const API = `http://${window.location.hostname}:8000/api`;
let pollingInterval = null;
let syncInterval    = null;
let todosEmpleados  = [];
let todosDeptos     = [];
let deptosFiltrados = new Set();
let currentUser     = null;
let userPermisos    = [];
let rolesCache      = [];
let reportMode      = 'entrada_salida';   // 'entrada_salida' | 'completo'

// ── Utilidades ─────────────────────────────────────────────────────────────
function hoy() {
    // Fecha de Colombia (evita el bug de UTC de toISOString)
    return new Date().toLocaleDateString('es-CO', { timeZone: 'America/Bogota', year:'numeric', month:'2-digit', day:'2-digit' }).split('/').reverse().join('-');
}

function showToast(msg, type = 'info') {
    const toast = document.getElementById('toast');
    const inner = document.getElementById('toast-inner');
    const colors = {
        info:    'background:rgba(30,58,138,0.95); color:#93c5fd; border:1px solid rgba(59,130,246,0.3)',
        success: 'background:rgba(6,78,59,0.95); color:#4ade80; border:1px solid rgba(34,197,94,0.3)',
        error:   'background:rgba(127,29,29,0.95); color:#f87171; border:1px solid rgba(239,68,68,0.3)',
    };
    inner.style.cssText = colors[type] || colors.info;
    inner.textContent   = msg;
    toast.classList.add('visible');
    setTimeout(() => toast.classList.remove('visible'), 4000);
}

function tienePermiso(nombre) {
    return userPermisos.includes(nombre);
}

async function apiFetch(url, options = {}) {
    const token = localStorage.getItem('token');
    options.headers = options.headers || {};
    if (token) options.headers['Authorization'] = `Bearer ${token}`;
    if (options.body && typeof options.body === 'object' && !options.headers['Content-Type']) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(options.body);
    }
    const res = await fetch(url, options);
    if (res.status === 401) {
        logout('Sesión expirada. Ingresa de nuevo.');
    }
    return res;
}

// ── Auth ───────────────────────────────────────────────────────────────────
function showLogin() {
    document.getElementById('login-screen').classList.remove('hidden');
    document.getElementById('password-change-screen').classList.add('hidden');
    document.querySelector('main').classList.add('hidden');
    document.getElementById('sidebar').classList.add('hidden');
}

function showApp() {
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('password-change-screen').classList.add('hidden');
    document.querySelector('main').classList.remove('hidden');
    document.getElementById('sidebar').classList.remove('hidden');
}

function showPasswordChange() {
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('password-change-screen').classList.remove('hidden');
    document.querySelector('main').classList.add('hidden');
    document.getElementById('sidebar').classList.add('hidden');
}

async function cambiarPassword() {
    const actual = document.getElementById('pw-actual').value;
    const nuevo  = document.getElementById('pw-nuevo').value;
    const confirmar = document.getElementById('pw-confirmar').value;
    const errorEl = document.getElementById('pw-change-error');
    errorEl.classList.add('hidden');

    if (!actual || !nuevo) {
        errorEl.textContent = 'Completa ambas contraseñas';
        errorEl.classList.remove('hidden');
        return;
    }
    if (nuevo !== confirmar) {
        errorEl.textContent = 'Las nuevas contraseñas no coinciden';
        errorEl.classList.remove('hidden');
        return;
    }
    if (nuevo.length < 6) {
        errorEl.textContent = 'La contraseña debe tener al menos 6 caracteres';
        errorEl.classList.remove('hidden');
        return;
    }

    try {
        const res = await apiFetch(`${API}/auth/cambiar-password`, {
            method: 'POST',
            body: { password_actual: actual, password_nuevo: nuevo }
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            errorEl.textContent = data.detail || 'No se pudo cambiar la contraseña';
            errorEl.classList.remove('hidden');
            return;
        }
        showToast('Contraseña actualizada. Ingresa de nuevo.', 'success');
        logout();
    } catch (e) {
        errorEl.textContent = 'Error conectando con la API';
        errorEl.classList.remove('hidden');
    }
}

async function login() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const errorEl  = document.getElementById('login-error');
    errorEl.classList.add('hidden');
    if (!username || !password) {
        errorEl.textContent = 'Ingresa usuario y contraseña';
        errorEl.classList.remove('hidden');
        return;
    }
    try {
        const res = await fetch(`${API}/auth/login`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        if (!res.ok) {
            errorEl.textContent = 'Usuario o contraseña incorrectos';
            errorEl.classList.remove('hidden');
            return;
        }
        const data = await res.json();
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('username', data.username);
        userPermisos = data.permisos || [];
        if (data.requiere_cambio_password) {
            showPasswordChange();
        } else {
            await initApp();
        }
    } catch (e) {
        errorEl.textContent = 'Error conectando con la API';
        errorEl.classList.remove('hidden');
    }
}

function logout(msg) {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    currentUser = null;
    userPermisos = [];
    if (msg) showToast(msg, 'error');
    showLogin();
}

async function initApp() {
    try {
        const res = await apiFetch(`${API}/auth/me`);
        if (!res.ok) { logout('Sesión inválida'); return; }
        currentUser = await res.json();
        userPermisos = currentUser.permisos || [];
        if (currentUser.requiere_cambio_password) {
            showPasswordChange();
            return;
        }
        document.getElementById('user-info').textContent = `${currentUser.username} · ${currentUser.rol}`;
    } catch (e) { logout('Error validando sesión'); return; }

    showApp();

    // Ocultar Admin si no tiene permisos administrativos
    const adminNav = document.getElementById('nav-admin');
    const adminAny = ['admin_empleados','admin_correo','admin_roles','sync_empleados','forzar_extraccion'].some(p => tienePermiso(p));
    if (adminNav) adminNav.style.display = adminAny ? '' : 'none';

    showView('dashboard');
}

function checkAuth() {
    const token = localStorage.getItem('token');
    if (!token) { showLogin(); return; }
    initApp();
}

// ── Navegación ─────────────────────────────────────────────────────────────
function showView(name) {
    ['dashboard','marcas','reportes','admin'].forEach(v => {
        document.getElementById(`view-${v}`).classList.add('hidden');
        const nav = document.getElementById(`nav-${v}`);
        if (nav) nav.classList.remove('active');
    });
    document.getElementById(`view-${name}`).classList.remove('hidden');
    const nav = document.getElementById(`nav-${name}`);
    if (nav) nav.classList.add('active');

    if (name === 'marcas')   cargarMarcasDelDia();
    if (name === 'reportes') cargarEmpleadosParaReporte();
    if (name === 'admin')    cargarAdmin();
}

function showTab(name) {
    const tabs = ['empleados','turnos','festivos','correo','roles'];
    document.querySelectorAll('.tab-btn').forEach((b, i) => {
        if (i >= tabs.length) return;
        b.classList.toggle('active', tabs[i] === name);
        document.getElementById(`tab-${tabs[i]}`).classList.toggle('active', tabs[i] === name);
    });
    if (name === 'festivos')  cargarFestivos();
    if (name === 'correo')    cargarConfigCorreo();
    if (name === 'empleados') cargarEmpleadosAdmin();
    if (name === 'turnos')    cargarTurnos();
    if (name === 'roles')     cargarUsuariosRoles();
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function cargarDashboard() {
    const fecha = document.getElementById('kpi-date').value || hoy();
    await Promise.all([cargarKPIs(fecha), cargarTardanzas(fecha), cargarMarcas()]);
    await mostrarAvisoExtraccion();
}

async function mostrarAvisoExtraccion() {
    const banner = document.getElementById('extraccion-alerta');
    const bannerInc = document.getElementById('extraccion-incompleta-alerta');
    if (!banner || !bannerInc) return;
    try {
        const res = await apiFetch(`${API}/status`);
        if (!res.ok) return;
        const s = await res.json();

        // Banner 1: extracción atrasada (>26h)
        banner.classList.add('hidden');
        if (s.alerta_retraso_extraccion) {
            const horas = s.horas_desde_ultima_extraccion;
            const ultima = s.ultima_extraccion_exitosa || '—';
            banner.innerHTML = `
                <div class="flex items-start gap-3">
                    <svg class="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M5.071 19h13.858c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                    <div class="flex-1">
                        <div class="font-semibold text-red-300">Extracción automática atrasada</div>
                        <div class="text-xs text-red-200/80 mt-0.5">
                            La última extracción exitosa fue hace <strong>${horas}h</strong>
                            (${ultima}). El ciclo es cada 24h. Revisa el scheduler o reinicia el backend.
                        </div>
                    </div>
                </div>`;
            banner.classList.remove('hidden');
        }

        // Banner 2: extracción incompleta (totalMatches > obtenidos)
        bannerInc.classList.add('hidden');
        if (s.alerta_extraccion_incompleta && Array.isArray(s.extraccion_incompleta) && s.extraccion_incompleta.length > 0) {
            const lines = s.extraccion_incompleta.map(a => {
                const f = a.fecha || '—';
                const ob = a.obtenido ?? 0;
                const es = a.esperado ?? 0;
                return `<div>Extracción del <strong>${f}</strong> puede estar incompleta (<strong>${ob}</strong> de <strong>${es}</strong> eventos)</div>`;
            }).join('');
            bannerInc.innerHTML = `
                <div class="flex items-start gap-3">
                    <svg class="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M5.071 19h13.858c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                    <div class="flex-1">
                        <div class="font-semibold text-red-300">Extracción incompleta</div>
                        <div class="text-xs text-red-200/80 mt-0.5 space-y-0.5">
                            ${lines}
                            <div class="mt-1 opacity-75">Re-corre la extracción para esa fecha o revisa los logs del backend.</div>
                        </div>
                    </div>
                </div>`;
            bannerInc.classList.remove('hidden');
        }
    } catch (e) {
        // silencioso
    }
}

async function cargarKPIs(fecha) {
    try {
        const res  = await apiFetch(`${API}/kpis?fecha=${fecha}`);
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById('kpi-total').textContent     = data.total_marcaciones   ?? '—';
        document.getElementById('kpi-presentes').textContent = data.empleados_con_marca ?? '—';
        document.getElementById('kpi-tardanzas').textContent = data.llegadas_tarde      ?? '—';
        document.getElementById('kpi-tiempo-pct').textContent = data.asistencia_a_tiempo_pct != null ? `${data.asistencia_a_tiempo_pct}%` : '—';
        document.getElementById('kpi-tiempo-sub').textContent = data.llegadas_tarde_pct != null ? `${data.llegadas_tarde_pct}% tarde` : '—';
        document.getElementById('kpi-minutos-perdidos').textContent = data.minutos_perdidos_tardanza != null ? `${data.minutos_perdidos_tardanza} min` : '—';
    } catch (e) {
        console.error('KPIs:', e);
    }
}

async function cargarTardanzas(fecha) {
    const f = fecha || document.getElementById('kpi-date').value || hoy();
    try {
        const res   = await apiFetch(`${API}/tardanzas?fecha=${f}`);
        if (!res.ok) return;
        const data  = await res.json();
        const tbody = document.getElementById('tabla-tardanzas');
        document.getElementById('tardanzas-count').textContent = `${data.length} empleado(s)`;

        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-6 text-slate-500 text-xs">Sin llegadas tarde registradas ✓</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(t => `
            <tr>
                <td class="font-medium text-white">${t.nombre}</td>
                <td><span class="badge-dept">${t.departamento || '—'}</span></td>
                <td class="text-orange-400 font-mono font-semibold">${t.primera_marca}</td>
                <td class="text-slate-400 font-mono">${t.hora_turno}</td>
                <td><span class="badge-late">+${t.tardanza_mins} min</span></td>
            </tr>`).join('');
    } catch(e) { console.error('Tardanzas:', e); }
}

async function cargarMarcas() {
    const fecha = document.getElementById('filter-date').value || hoy();
    try {
        const res  = await apiFetch(`${API}/registros?fecha=${fecha}`);
        if (!res.ok) return;
        const data = await res.json();
        const tbody = document.getElementById('tabla-marcas');
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center py-6 text-slate-500 text-xs">Sin marcas en esta fecha</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(r => `
            <tr>
                <td class="text-sky-300 font-medium">${r.nombre_empleado || '—'}</td>
                <td class="font-mono text-slate-300">${r.hora ? String(r.hora).slice(0,5) : '—'}</td>
                <td class="text-xs text-slate-500">${r.tipo_evento || '—'}</td>
            </tr>`).join('');
    } catch(e) {
        document.getElementById('tabla-marcas').innerHTML =
            '<tr><td colspan="3" class="text-center py-6 text-red-400 text-xs">Error conectando con la API</td></tr>';
    }
}

async function cargarMarcasDelDia() {
    const fecha = document.getElementById('marcas-date').value || hoy();
    try {
        const res  = await apiFetch(`${API}/registros?fecha=${fecha}`);
        if (!res.ok) return;
        const data = await res.json();
        const tbody = document.getElementById('tabla-marcas-dia');
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-8 text-slate-500 text-xs">Sin marcas en esta fecha</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(r => `
            <tr>
                <td class="text-sky-300 font-medium">${r.nombre_empleado || '—'}</td>
                <td class="font-mono text-slate-400 text-xs">${r.fecha || '—'}</td>
                <td class="font-mono text-slate-300">${r.hora ? String(r.hora).slice(0,5) : '—'}</td>
                <td class="text-xs text-slate-500">${r.tipo_evento || '—'}</td>
                <td class="font-mono text-xs text-slate-500">${r.empleado_id || '—'}</td>
            </tr>`).join('');
    } catch(e) {
        document.getElementById('tabla-marcas-dia').innerHTML =
            '<tr><td colspan="5" class="text-center py-8 text-red-400 text-xs">Error conectando con la API</td></tr>';
    }
}

// ── Extracción manual ──────────────────────────────────────────────────────
async function forzarExtraccion() {
    const dStart = document.getElementById('date-start').value || hoy();
    const dEnd   = document.getElementById('date-end').value   || hoy();
    try {
        const res = await apiFetch(`${API}/extraer`, {
            method: 'POST',
            body: { fecha_inicio: dStart, fecha_fin: dEnd }
        });
        if (!res.ok) { throw new Error((await res.json()).detail || 'Error'); }
        const r = await res.json();
        showToast(r.message, 'info');
        document.getElementById('progress-bar').classList.add('visible');
        document.getElementById('btn-extraer').disabled = true;
        if (!pollingInterval) pollingInterval = setInterval(checkStatus, 1000);
    } catch(e) { showToast(e.message || 'Error al contactar con la API', 'error'); }
}

async function checkStatus() {
    try {
        const res  = await apiFetch(`${API}/status`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.is_running) {
            document.getElementById('progress-msg').textContent = data.progress;
        } else if (pollingInterval) {
            clearInterval(pollingInterval); pollingInterval = null;
            document.getElementById('progress-bar').classList.remove('visible');
            document.getElementById('btn-extraer').disabled = false;
            showToast('Extracción completada', 'success');
            cargarDashboard();
        }
    } catch(e) {}
}

// ── Reportes ───────────────────────────────────────────────────────────────
async function cargarEmpleadosParaReporte() {
    try {
        const [empRes] = await Promise.all([
            apiFetch(`${API}/empleados`)
        ]);
        if (!empRes.ok) return;
        const all = await empRes.json();
        // Solo empleados activos aparecen en el reporte
        todosEmpleados = all.filter(e => e.activo);
        todosDeptos = [...new Set(
            todosEmpleados.map(e => e.departamento).filter(Boolean)
        )].sort();
        renderDeptFilter();
        renderEmpList(todosEmpleados);
    } catch(e) { console.error('Empleados reporte:', e); }
}

function renderDeptFilter() {
    const cont = document.getElementById('dept-filter-list');
    if (!todosDeptos.length) {
        cont.innerHTML = '<span class="text-xs text-slate-500">No hay departamentos configurados</span>';
        return;
    }
    cont.innerHTML = todosDeptos.map(d => `
        <label class="flex items-center gap-1.5 cursor-pointer px-3 py-1 rounded-full border border-slate-600 hover:border-sky-500 text-xs text-slate-300 hover:text-sky-300 transition-all">
            <input type="checkbox" class="dept-chk emp-checkbox" value="${d}"
                   onchange="filtrarPorDept()"> ${d}
        </label>`).join('');
}

function filtrarPorDept() {
    const sel = [...document.querySelectorAll('.dept-chk:checked')].map(c => c.value);
    deptosFiltrados = new Set(sel);
    const filtrado  = sel.length
        ? todosEmpleados.filter(e => sel.includes(e.departamento))
        : todosEmpleados;
    renderEmpList(filtrado);
}

function renderEmpList(lista) {
    const cont = document.getElementById('emp-list');
    if (!lista.length) {
        cont.innerHTML = '<p class="text-xs text-slate-500 p-4 text-center">Sin empleados</p>';
        return;
    }
    cont.innerHTML = lista.map(e => `
        <label class="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-800/40 cursor-pointer">
            <input type="checkbox" class="emp-checkbox emp-chk" value="${e.employee_id}" checked>
            <span class="text-sm text-slate-300 flex-1">${e.nombre}</span>
            ${e.departamento ? `<span class="badge-dept text-xs">${e.departamento}</span>` : ''}
        </label>`).join('');
}

function filtrarListaEmpleados() {
    const q = document.getElementById('search-emp').value.toLowerCase();
    const filtrado = todosEmpleados.filter(e =>
        e.nombre.toLowerCase().includes(q) ||
        (e.departamento || '').toLowerCase().includes(q)
    );
    renderEmpList(filtrado);
}

function seleccionarTodos(sel) {
    document.querySelectorAll('.emp-chk').forEach(c => c.checked = sel);
}

function toggleReportMode() {
    reportMode = reportMode === 'entrada_salida' ? 'completo' : 'entrada_salida';
    const btn = document.getElementById('btn-toggle-modo');
    if (btn) btn.textContent = reportMode === 'completo'
        ? 'Completo (todas las marcas)'
        : 'Entrada / Salida';
}

async function generarReporte() {
    const inicio = document.getElementById('rep-start').value;
    const fin    = document.getElementById('rep-end').value;
    if (!inicio || !fin) { showToast('Selecciona un rango de fechas', 'error'); return; }

    const selIds = [...document.querySelectorAll('.emp-chk:checked')].map(c => c.value);
    if (!selIds.length) { showToast('Selecciona al menos un empleado', 'error'); return; }

    const btn = document.getElementById('btn-generar');
    btn.disabled = true;
    btn.textContent = 'Generando...';

    const modo = reportMode;

    try {
        const res = await apiFetch(`${API}/reportes/generar`, {
            method: 'POST',
            body: { fecha_inicio: inicio, fecha_fin: fin, employee_ids: selIds, modo }
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Error desconocido');
        }
        const blob     = await res.blob();
        const url      = URL.createObjectURL(blob);
        const a        = document.createElement('a');
        a.href         = url;
        a.download     = `Asistencia_${inicio}_${fin}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Reporte generado y descargado', 'success');
    } catch(e) {
        showToast(`Error: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg> Generar y Descargar Excel';
    }
}

// ── Admin: Empleados ────────────────────────────────────────────────────────
async function cargarAdmin() {
    await cargarTurnos();
    await cargarEmpleadosAdmin();
}

let adminEmpleados = [];
let adminTurnos = [];

function opcionesTurno(selectedId) {
    return adminTurnos.map(t =>
        `<option value="${t.id}" ${t.id === selectedId ? 'selected' : ''}>${t.nombre}</option>`
    ).join('');
}

async function cargarEmpleadosAdmin() {
    if (!tienePermiso('admin_empleados') && !tienePermiso('sync_empleados')) return;
    try {
        const empRes = await apiFetch(`${API}/empleados`);
        if (!empRes.ok) return;
        const emps = await empRes.json();
        adminEmpleados = emps;

        const tbody = document.getElementById('tabla-empleados');
        if (!emps.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-slate-500 text-xs">No hay empleados sincronizados. Usa el botón de arriba.</td></tr>';
            return;
        }

        tbody.innerHTML = emps.map(e => {
            return `
            <tr id="emp-row-${e.id}" class="${e.activo ? '' : 'opacity-50'}">
                <td class="font-mono text-xs text-slate-400">${e.employee_id}</td>
                <td class="font-medium text-white">${e.nombre}${e.activo ? '' : ' <span class="text-[10px] text-slate-500 ml-1">(Inactivo)</span>'}</td>
                <td class="text-center">
                    <input type="checkbox" id="emp-activo-${e.id}" ${e.activo ? 'checked' : ''}
                           onchange="toggleEmpleadoActivo(${e.id}, this.checked)"
                           class="emp-checkbox" title="Activo / Inactivo">
                </td>
                <td>
                    <input type="text" id="emp-dept-${e.id}" value="${e.departamento || ''}"
                           class="form-input text-xs py-1" placeholder="Área">
                </td>
                <td>
                    <select id="emp-turno-${e.id}" class="form-input text-xs py-1">
                        <option value="">— Sin turno —</option>
                        ${opcionesTurno(e.turno_id)}
                    </select>
                </td>
                <td>
                    <button onclick="guardarEmpleado(${e.id})" class="btn-success text-xs py-1 px-3">Guardar</button>
                </td>
            </tr>`;
        }).join('');
    } catch(e) { console.error('Admin empleados:', e); }
}

async function guardarEmpleado(id) {
    const turnoValue = document.getElementById(`emp-turno-${id}`).value;
    const payload = {
        activo:             document.getElementById(`emp-activo-${id}`).checked,
        departamento:       document.getElementById(`emp-dept-${id}`).value.trim() || null,
        turno_id:           turnoValue ? parseInt(turnoValue) : null,
    };
    try {
        const res = await apiFetch(`${API}/empleados/${id}`, {
            method: 'PUT', body: payload
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
        showToast('Empleado actualizado', 'success');
        cargarEmpleadosAdmin();
        cargarEmpleadosParaReporte();
    } catch(e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function toggleEmpleadoActivo(id, activo) {
    try {
        const res = await apiFetch(`${API}/empleados/${id}`, {
            method: 'PUT', body: { activo }
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
        showToast(activo ? 'Empleado activado' : 'Empleado inactivado', 'success');
        cargarEmpleadosAdmin();
        cargarEmpleadosParaReporte();
    } catch(e) {
        showToast(`Error: ${e.message}`, 'error');
        cargarEmpleadosAdmin();
    }
}

async function sincronizarEmpleados() {
    if (!tienePermiso('sync_empleados')) { showToast('No tienes permiso para sincronizar empleados', 'error'); return; }
    try {
        const btn = document.getElementById('btn-sync-empleados');
        btn.disabled = true;
        const res = await apiFetch(`${API}/empleados/sync`, { method: 'POST' });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        const data = await res.json();
        showToast(data.message, 'info');
        document.getElementById('sync-status').textContent = 'Sincronizando...';
        if (!syncInterval) syncInterval = setInterval(checkSyncStatus, 1000);
    } catch(e) {
        showToast(e.message || 'Error al iniciar sincronización', 'error');
        document.getElementById('btn-sync-empleados').disabled = false;
    }
}

async function checkSyncStatus() {
    try {
        const res  = await apiFetch(`${API}/empleados/sync/status`);
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById('sync-status').textContent = data.progress;
        if (!data.is_running) {
            clearInterval(syncInterval); syncInterval = null;
            document.getElementById('btn-sync-empleados').disabled = false;
            if (data.last_result && !data.last_result.error) {
                const r = data.last_result;
                showToast(`${r.creados} creados, ${r.actualizados} actualizados`, 'success');
            }
            cargarEmpleadosAdmin();
            cargarEmpleadosParaReporte();
        }
    } catch(e) {}
}

// ── Admin: Turnos ───────────────────────────────────────────────────────────
const DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes'];

async function cargarTurnos() {
    if (!tienePermiso('admin_empleados')) return;
    try {
        const res = await apiFetch(`${API}/turnos`);
        if (!res.ok) return;
        adminTurnos = await res.json();
        renderizarTurnos();
    } catch(e) { console.error('Admin turnos:', e); }
}

function renderizarTurnos() {
    const tbody = document.getElementById('tabla-turnos');
    if (!adminTurnos.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-6 text-slate-500 text-xs">No hay turnos. Crea uno con el botón de arriba.</td></tr>';
        return;
    }
    tbody.innerHTML = adminTurnos.map(t => {
        const celdas = t.horarios_hoy.map((h, idx) => {
            if (!h) return `<td class="text-slate-500 text-xs">—</td>`;
            return `<td class="text-xs">
                <div class="font-mono text-white">${h.hora_entrada}</div>
                <div class="text-[10px] text-slate-400">tol: ${h.tolerancia_minutos} min</div>
                <button onclick="mostrarFormVigencia(${t.id}, ${idx})" class="text-[10px] text-sky-400 hover:text-sky-300 mt-1">+ vigencia</button>
            </td>`;
        }).join('');
        return `
        <tr>
            <td class="font-medium text-white">${t.nombre}</td>
            ${celdas}
            <td>
                <button onclick="editarTurno(${t.id})" class="btn-success text-xs py-1 px-2 mb-1">Editar</button>
                <button onclick="eliminarTurno(${t.id})" class="btn-danger text-xs py-1 px-2">Eliminar</button>
            </td>
        </tr>`;
    }).join('');
}

function mostrarFormTurno() {
    document.getElementById('form-turno').classList.remove('hidden');
    document.getElementById('form-vigencia').classList.add('hidden');
    document.getElementById('titulo-form-turno').textContent = 'Nuevo turno';
    document.getElementById('turno-id').value = '';
    document.getElementById('turno-nombre').value = '';
    document.getElementById('turno-salida').value = '';
    const grid = document.getElementById('turno-horarios-grid');
    grid.innerHTML = DIAS_SEMANA.map((dia, idx) => `
        <div class="p-3 rounded-lg bg-slate-900/50 border border-slate-700 space-y-2">
            <p class="text-xs font-semibold text-slate-300">${dia}</p>
            <div>
                <label class="text-[10px] text-slate-400">Entrada</label>
                <input type="time" id="turno-hora-${idx}" class="form-input text-xs py-1" value="07:30">
            </div>
            <div>
                <label class="text-[10px] text-slate-400">Tolerancia (min)</label>
                <input type="number" id="turno-tol-${idx}" class="form-input text-xs py-1" value="10" min="0">
            </div>
        </div>
    `).join('');
}

function cancelarFormTurno() {
    document.getElementById('form-turno').classList.add('hidden');
}

async function guardarTurno() {
    const id = document.getElementById('turno-id').value;
    const horarios = DIAS_SEMANA.map((_, idx) => ({
        dia_semana: idx,
        hora_entrada: document.getElementById(`turno-hora-${idx}`).value,
        tolerancia_minutos: parseInt(document.getElementById(`turno-tol-${idx}`).value) || 0,
    }));
    const payload = {
        nombre: document.getElementById('turno-nombre').value.trim(),
        hora_salida: document.getElementById('turno-salida').value || null,
        horarios,
    };
    try {
        const url = id ? `${API}/turnos/${id}` : `${API}/turnos`;
        const method = id ? 'PUT' : 'POST';
        const res = await apiFetch(url, { method, body: payload });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
        showToast(id ? 'Turno actualizado' : 'Turno creado', 'success');
        cancelarFormTurno();
        await cargarTurnos();
        await cargarEmpleadosAdmin();
    } catch(e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function editarTurno(id) {
    try {
        const res = await apiFetch(`${API}/turnos/${id}`);
        if (!res.ok) throw new Error('No se pudo cargar el turno');
        const t = await res.json();
        document.getElementById('form-turno').classList.remove('hidden');
        document.getElementById('form-vigencia').classList.add('hidden');
        document.getElementById('titulo-form-turno').textContent = `Editar turno: ${t.nombre}`;
        document.getElementById('turno-id').value = t.id;
        document.getElementById('turno-nombre').value = t.nombre;
        document.getElementById('turno-salida').value = t.hora_salida || '';
        const grid = document.getElementById('turno-horarios-grid');
        grid.innerHTML = DIAS_SEMANA.map((dia, idx) => {
            const h = t.horarios_hoy[idx] || { hora_entrada: '07:30', tolerancia_minutos: 10 };
            return `
            <div class="p-3 rounded-lg bg-slate-900/50 border border-slate-700 space-y-2">
                <p class="text-xs font-semibold text-slate-300">${dia}</p>
                <div>
                    <label class="text-[10px] text-slate-400">Entrada</label>
                    <input type="time" id="turno-hora-${idx}" class="form-input text-xs py-1" value="${h.hora_entrada}">
                </div>
                <div>
                    <label class="text-[10px] text-slate-400">Tolerancia (min)</label>
                    <input type="number" id="turno-tol-${idx}" class="form-input text-xs py-1" value="${h.tolerancia_minutos}" min="0">
                </div>
            </div>`;
        }).join('');
    } catch(e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function eliminarTurno(id) {
    if (!confirm('¿Eliminar este turno? Los empleados asignados a él quedarán sin turno.')) return;
    try {
        const res = await apiFetch(`${API}/turnos/${id}`, { method: 'DELETE' });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
        showToast('Turno eliminado', 'success');
        await cargarTurnos();
        await cargarEmpleadosAdmin();
    } catch(e) { showToast(`Error: ${e.message}`, 'error'); }
}

function mostrarFormVigencia(turnoId, diaSemana) {
    document.getElementById('form-vigencia').classList.remove('hidden');
    document.getElementById('form-turno').classList.add('hidden');
    document.getElementById('vigencia-turno-id').value = turnoId;
    document.getElementById('vigencia-dia-semana').value = diaSemana;
    document.getElementById('vigencia-dia-nombre').textContent = DIAS_SEMANA[diaSemana];
    document.getElementById('vigencia-hora').value = '07:30';
    document.getElementById('vigencia-tolerancia').value = '10';
    document.getElementById('vigencia-desde').value = hoy();
}

function cancelarFormVigencia() {
    document.getElementById('form-vigencia').classList.add('hidden');
}

async function guardarVigencia() {
    const payload = {
        dia_semana: parseInt(document.getElementById('vigencia-dia-semana').value),
        hora_entrada: document.getElementById('vigencia-hora').value,
        tolerancia_minutos: parseInt(document.getElementById('vigencia-tolerancia').value) || 0,
        vigente_desde: document.getElementById('vigencia-desde').value,
    };
    const turnoId = document.getElementById('vigencia-turno-id').value;
    try {
        const res = await apiFetch(`${API}/turnos/${turnoId}/horarios`, { method: 'POST', body: payload });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
        showToast('Vigencia guardada', 'success');
        cancelarFormVigencia();
        await cargarTurnos();
    } catch(e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function cargarMarcasSinAsociar() {
    if (!tienePermiso('admin_empleados')) return;
    const tbody = document.getElementById('tabla-sin-asociar');
    try {
        const res  = await apiFetch(`${API}/registros/sin-asociar`);
        if (!res.ok) return;
        const data = await res.json();
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="2" class="text-center py-4 text-slate-500 text-xs">Todas las marcas tienen empleado asociado ✓</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(r => `
            <tr>
                <td class="text-slate-300">${r.nombre || '—'}</td>
                <td class="font-mono text-xs text-slate-400">${r.employee_id || '—'}</td>
            </tr>`).join('');
    } catch(e) {
        tbody.innerHTML = '<tr><td colspan="2" class="text-center py-4 text-red-400 text-xs">Error cargando datos</td></tr>';
    }
}

// ── Admin: Festivos (solo lectura) ──────────────────────────────────────────
async function cargarFestivos() {
    if (!tienePermiso('admin_correo')) return;
    const tbody = document.getElementById('tabla-festivos');
    try {
        const res   = await apiFetch(`${API}/festivos`);
        if (!res.ok) return;
        const data  = await res.json();
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="2" class="text-center py-6 text-slate-500 text-xs">No hay festivos cargados</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(f => `
            <tr>
                <td class="font-mono text-slate-300">${f.fecha}</td>
                <td class="text-white">${f.descripcion}</td>
            </tr>`).join('');
    } catch(e) {
        tbody.innerHTML = '<tr><td colspan="2" class="text-center py-6 text-red-400 text-xs">Error cargando festivos</td></tr>';
    }
}

// ── Admin: Correo ───────────────────────────────────────────────────────────
async function cargarConfigCorreo() {
    if (!tienePermiso('admin_correo')) return;
    try {
        const [cfgRes, legacyRes] = await Promise.all([
            apiFetch(`${API}/config/correo`),
            apiFetch(`${API}/configuracion/correo`),
        ]);
        if (!cfgRes.ok || !legacyRes.ok) return;
        const cfg = await cfgRes.json();
        const legacy = await legacyRes.json();

        document.getElementById('cfg-host').value = cfg.host || '';
        document.getElementById('cfg-puerto').value = cfg.puerto || '';
        document.getElementById('cfg-usuario').value = cfg.usuario || '';
        document.getElementById('cfg-password').value = '';
        document.getElementById('cfg-remitente').value = cfg.remitente_nombre || '';
        document.getElementById('cfg-seguridad').value = cfg.seguridad || 'starttls';

        const meta = document.getElementById('correo-meta');
        if (cfg.updated_at) {
            const fecha = new Date(cfg.updated_at).toLocaleString('es-CO', { timeZone: 'America/Bogota' });
            meta.textContent = `Última actualización: ${fecha}${cfg.updated_by ? ' por ' + cfg.updated_by : ''}`;
        } else {
            meta.textContent = 'Sin configurar';
        }

        // Password placeholder visual
        const pwInput = document.getElementById('cfg-password');
        if (cfg.password_configurado) {
            pwInput.placeholder = '********';
        } else {
            pwInput.placeholder = 'Contraseña requerida para crear config';
        }

        renderDestinatarios(legacy.destinatarios);

        if (legacy.periodicidad) {
            document.getElementById('sem-dia').value   = legacy.periodicidad.semanal.dia;
            const sh = legacy.periodicidad.semanal.hora.toString().padStart(2,'0');
            const sm = legacy.periodicidad.semanal.minuto.toString().padStart(2,'0');
            document.getElementById('sem-hora').value  = `${sh}:${sm}`;
            document.getElementById('men-dia').value    = legacy.periodicidad.mensual.dia;
            const mh = legacy.periodicidad.mensual.hora.toString().padStart(2,'0');
            const mm = legacy.periodicidad.mensual.minuto.toString().padStart(2,'0');
            document.getElementById('men-hora').value = `${mh}:${mm}`;
        }
    } catch(e) { console.error('Config correo:', e); }
}

function setupFormCorreo() {
    const form = document.getElementById('form-correo');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            host: document.getElementById('cfg-host').value.trim(),
            puerto: parseInt(document.getElementById('cfg-puerto').value),
            usuario: document.getElementById('cfg-usuario').value.trim(),
            password: document.getElementById('cfg-password').value || null,
            remitente_nombre: document.getElementById('cfg-remitente').value.trim() || null,
            seguridad: document.getElementById('cfg-seguridad').value,
        };
        try {
            const res = await apiFetch(`${API}/config/correo`, {
                method: 'PUT', body: payload
            });
            const d = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(d.detail || 'Error');
            showToast('Configuración guardada', 'success');
            await cargarConfigCorreo();
        } catch(err) { showToast(err.message || 'Error guardando', 'error'); }
    });
}

function renderDestinatarios(lista) {
    const dests = document.getElementById('correo-destinatarios');
    if (!lista.length) {
        dests.innerHTML = '<span class="text-xs text-slate-500">Sin destinatarios configurados</span>';
        return;
    }
    dests.innerHTML = lista.map(d => `
        <span class="badge-dept text-xs px-3 py-1 flex items-center gap-2">
            ${d}
            <button onclick="eliminarDestinatario('${d}')" class="text-slate-400 hover:text-red-400">×</button>
        </span>`).join('');
}

async function agregarDestinatario() {
    const email = document.getElementById('new-dest-email').value.trim();
    if (!email || !email.includes('@')) { showToast('Ingresa un correo válido', 'error'); return; }
    try {
        const res = await apiFetch(`${API}/configuracion/correo/destinatarios`, {
            method: 'POST', body: { email }
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        const data = await res.json();
        renderDestinatarios(data.destinatarios);
        document.getElementById('new-dest-email').value = '';
        showToast('Destinatario agregado', 'success');
    } catch(e) { showToast(e.message, 'error'); }
}

async function eliminarDestinatario(email) {
    try {
        const res = await apiFetch(`${API}/configuracion/correo/destinatarios/${encodeURIComponent(email)}`, {
            method: 'DELETE'
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        const data = await res.json();
        renderDestinatarios(data.destinatarios);
        showToast('Destinatario eliminado', 'info');
    } catch(e) { showToast(e.message, 'error'); }
}

async function guardarPeriodicidad() {
    const semHora = document.getElementById('sem-hora').value;
    const menHora = document.getElementById('men-hora').value;
    if (!semHora || !menHora) { showToast('Completa las horas', 'error'); return; }

    const payload = {
        semanal: {
            dia:    parseInt(document.getElementById('sem-dia').value),
            hora:   parseInt(semHora.split(':')[0]),
            minuto: parseInt(semHora.split(':')[1]),
        },
        mensual: {
            dia:    parseInt(document.getElementById('men-dia').value),
            hora:   parseInt(menHora.split(':')[0]),
            minuto: parseInt(menHora.split(':')[1]),
        }
    };
    try {
        const res = await apiFetch(`${API}/configuracion/correo/periodicidad`, {
            method: 'POST', body: payload
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        const data = await res.json();
        showToast(data.message, 'success');
    } catch(e) { showToast(e.message, 'error'); }
}

async function probarCorreo() {
    if (!tienePermiso('admin_correo')) { showToast('Sin permiso', 'error'); return; }
    showToast('Enviando correo de prueba...', 'info');
    try {
        const res = await apiFetch(`${API}/configuracion/correo/prueba`, { method: 'POST' });
        const d   = await res.json();
        if (res.ok) showToast(d.message, 'success');
        else showToast(d.detail || 'Error', 'error');
    } catch(e) { showToast('Error al contactar la API', 'error'); }
}

async function probarCorreoConfig() {
    if (!tienePermiso('admin_correo')) { showToast('Sin permiso', 'error'); return; }
    const destinatario = document.getElementById('cfg-test-dest').value.trim();
    if (!destinatario || !destinatario.includes('@')) {
        showToast('Ingresa un correo de prueba válido', 'error'); return;
    }
    const resultEl = document.getElementById('correo-test-result');
    resultEl.classList.remove('hidden', 'text-green-400', 'text-red-400');
    resultEl.textContent = 'Enviando...';
    try {
        const res = await apiFetch(`${API}/config/correo/test`, {
            method: 'POST', body: { destinatario }
        });
        const d = await res.json().catch(() => ({}));
        if (res.ok) {
            resultEl.classList.add('text-green-400');
            resultEl.textContent = d.message || 'Correo enviado';
        } else {
            resultEl.classList.add('text-red-400');
            resultEl.textContent = d.detail || 'Error desconocido';
        }
    } catch(e) {
        resultEl.classList.add('text-red-400');
        resultEl.textContent = 'Error al contactar la API';
    }
}

// ── Admin: Usuarios y Roles ────────────────────────────────────────────────
async function cargarUsuariosRoles() {
    if (!tienePermiso('admin_roles')) { showToast('Sin permiso', 'error'); return; }
    try {
        const [rolesRes, usersRes, permsRes] = await Promise.all([
            apiFetch(`${API}/roles`),
            apiFetch(`${API}/usuarios`),
            apiFetch(`${API}/permisos`),
        ]);
        if (!rolesRes.ok || !usersRes.ok || !permsRes.ok) return;
        const roles = await rolesRes.json();
        const users = await usersRes.json();
        const perms = await permsRes.json();
        rolesCache = roles;

        // Select de roles para nuevo usuario
        const sel = document.getElementById('new-user-rol');
        sel.innerHTML = roles.map(r => `<option value="${r.id}">${r.nombre}</option>`).join('');

        // Tabla usuarios
        const tbodyU = document.getElementById('tabla-usuarios');
        tbodyU.innerHTML = users.map(u => {
            const r = roles.find(x => x.id === u.rol_id);
            return `
            <tr>
                <td class="font-medium text-white">${u.username}</td>
                <td><span class="badge-dept text-xs">${r ? r.nombre : '—'}</span></td>
                <td class="text-center">
                    <input type="checkbox" ${u.activo ? 'checked' : ''} class="emp-checkbox"
                           onchange="toggleUsuario(${u.id}, this.checked)">
                </td>
                <td class="flex gap-1">
                    ${u.id !== currentUser?.id ? `<button onclick="resetearPasswordUsuario(${u.id}, '${u.username}')" class="btn-warning text-xs py-1">Resetear pass</button>` : ''}
                    <button onclick="eliminarUsuario(${u.id})" class="btn-danger text-xs py-1">Eliminar</button>
                </td>
            </tr>`;
        }).join('');

        // Tabla roles
        const tbodyR = document.getElementById('tabla-roles');
        tbodyR.innerHTML = roles.map(r => {
            const permisosAsignados = r.permisos.map(p => p.nombre);
            return `
            <tr>
                <td class="font-medium text-white">${r.nombre}</td>
                <td class="text-xs text-slate-300">
                    <div class="flex flex-wrap gap-1">
                        ${perms.map(p => `
                            <label class="inline-flex items-center gap-1 px-2 py-0.5 rounded border ${permisosAsignados.includes(p.nombre) ? 'border-sky-500/50 bg-sky-500/10' : 'border-slate-600'} cursor-pointer">
                                <input type="checkbox" ${permisosAsignados.includes(p.nombre) ? 'checked' : ''}
                                       onchange="togglePermisoRol(${r.id}, ${p.id}, this.checked)"
                                       class="emp-checkbox">
                                <span class="text-slate-400">${p.nombre}</span>
                            </label>
                        `).join('')}
                    </div>
                </td>
                <td>
                    ${r.nombre !== 'Admin' && r.nombre !== 'Reportes' ? `<button onclick="eliminarRol(${r.id})" class="btn-danger text-xs py-1">Eliminar</button>` : ''}
                </td>
            </tr>`;
        }).join('');
    } catch(e) { console.error('Usuarios/Roles:', e); }
}

async function crearUsuario() {
    const username = document.getElementById('new-user-username').value.trim();
    const password = document.getElementById('new-user-password').value;
    const rol_id   = parseInt(document.getElementById('new-user-rol').value);
    if (!username || !password || !rol_id) { showToast('Completa todos los campos', 'error'); return; }
    try {
        const res = await apiFetch(`${API}/usuarios`, {
            method: 'POST', body: { username, password, rol_id }
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        showToast('Usuario creado', 'success');
        document.getElementById('new-user-username').value = '';
        document.getElementById('new-user-password').value = '';
        cargarUsuariosRoles();
    } catch(e) { showToast(e.message, 'error'); }
}

async function toggleUsuario(id, activo) {
    try {
        const res = await apiFetch(`${API}/usuarios/${id}`, {
            method: 'PUT', body: { activo }
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        showToast('Usuario actualizado', 'success');
    } catch(e) { showToast(e.message, 'error'); cargarUsuariosRoles(); }
}

async function eliminarUsuario(id) {
    if (!confirm('¿Eliminar este usuario?')) return;
    try {
        const res = await apiFetch(`${API}/usuarios/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        showToast('Usuario eliminado', 'info');
        cargarUsuariosRoles();
    } catch(e) { showToast(e.message, 'error'); }
}


async function resetearPasswordUsuario(id, username) {
    // Doble seguridad: no permitir auto-reset.
    if (id === currentUser?.id) {
        showToast('No puedes resetear tu propia contraseña', 'error');
        return;
    }
    // Confirmación destructiva: escribir el username exacto.
    const confirmacion = prompt(`Para resetear la contraseña de "${username}", escribí el nombre de usuario exacto:`);
    if (confirmacion === null) return; // Canceló.
    if (confirmacion.trim() !== username) {
        showToast('El usuario no coincide. Cancelado.', 'error');
        return;
    }

    try {
        const res = await apiFetch(`${API}/usuarios/${id}/resetear-password`, { method: 'POST' });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        const data = await res.json();
        mostrarPasswordTemporal(data.password_temporal);
        cargarUsuariosRoles();
    } catch(e) { showToast(e.message, 'error'); }
}


function mostrarPasswordTemporal(password) {
    document.getElementById('reset-password-temp').value = password;
    document.getElementById('modal-reset-password').classList.remove('hidden');
}


function cerrarModalResetPassword() {
    document.getElementById('reset-password-temp').value = '';
    document.getElementById('modal-reset-password').classList.add('hidden');
}


function copiarPasswordTemporal() {
    const input = document.getElementById('reset-password-temp');
    input.select();
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value)
            .then(() => showToast('Contraseña copiada', 'success'))
            .catch(() => showToast('No se pudo copiar automático — selecciona el texto y Ctrl+C', 'warning'));
    } else {
        showToast('No se pudo copiar automático — selecciona el texto y Ctrl+C', 'warning');
    }
}


async function crearRol() {
    const nombre = document.getElementById('new-rol-nombre').value.trim();
    if (!nombre) { showToast('Ingresa un nombre de rol', 'error'); return; }
    try {
        const res = await apiFetch(`${API}/roles`, { method: 'POST', body: { nombre } });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        showToast('Rol creado', 'success');
        document.getElementById('new-rol-nombre').value = '';
        cargarUsuariosRoles();
    } catch(e) { showToast(e.message, 'error'); }
}

async function togglePermisoRol(rolId, permId, asignar) {
    try {
        const res = await apiFetch(`${API}/roles/${rolId}/permisos${!asignar ? '/' + permId : ''}`, {
            method: asignar ? 'POST' : 'DELETE',
            body: asignar ? { permiso_id: permId } : undefined
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        showToast(asignar ? 'Permiso asignado' : 'Permiso removido', 'success');
    } catch(e) { showToast(e.message, 'error'); cargarUsuariosRoles(); }
}

async function eliminarRol(id) {
    if (!confirm('¿Eliminar este rol?')) return;
    try {
        const res = await apiFetch(`${API}/roles/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error((await res.json()).detail || 'Error');
        showToast('Rol eliminado', 'info');
        cargarUsuariosRoles();
    } catch(e) { showToast(e.message, 'error'); }
}

// ── Init ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const fechaHoy = hoy();
    ['kpi-date','filter-date','date-start','date-end','marcas-date'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = fechaHoy;
    });

    // Fecha default para el generador de reportes (inicio de semana en Colombia)
    const hoyDate = new Date(fechaHoy + 'T00:00:00');
    const diaSem = hoyDate.getDay(); // 0=dom, 1=lun...
    const diasAtras = diaSem === 0 ? 6 : diaSem - 1;
    const lunes = new Date(hoyDate);
    lunes.setDate(hoyDate.getDate() - diasAtras);
    const repStart = document.getElementById('rep-start');
    const repEnd   = document.getElementById('rep-end');
    if (repStart) repStart.value = lunes.toLocaleDateString('es-CO', { timeZone: 'America/Bogota', year:'numeric', month:'2-digit', day:'2-digit' }).split('/').reverse().join('-');
    if (repEnd)   repEnd.value   = fechaHoy;

    setupFormCorreo();
    checkAuth();
});
