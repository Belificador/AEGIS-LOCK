# AEGIS LOCK · Prototipo de monitoreo local

Dashboard modular para la futura plataforma de monitoreo del gemelo digital. El
prototipo se ejecuta en localhost y no inventa telemetría: las métricas y la
consola esperan eventos reales del modelo.

## Estructura

```text
backend/
  main.py                 FastAPI, CORS y rutas
  config.py               Configuración pydantic-settings
  core/                   JWT, rate limiting, dependencias y middleware
  models/schemas.py       Validación de eventos
  routers/                Auth, telemetría, WebSocket y chat local
  services/               Supabase, reglas y adaptador de IA local
  sql/                    Tabla de persistencia de eventos
  tests/                  Reglas, JWT y flujo WebSocket
frontend/
  index.html              Intro, login, dashboard y modales
  styles/main.css         Entrada CSS con imports por panel
  styles/components/      CSS separado para cada panel y modal
  src/main.js             Transición y ciclo de vida de vistas
  src/components/header/  Barra superior y selector de perfil
  src/components/sidebar-left/ Métricas, historiales y chat
  src/components/viewport/ Estado de conexión y captura de señal
  src/components/sidebar-right/ Consola, emergencia y cierre
  src/auth.js             Login simulado o REST configurable
  src/dataReceiver.js     WebSocket opcional y telemetría demo
```

## Inicio rápido del prototipo

La interfaz funciona en modo de demostración sin Supabase con estas cuentas;
el perfil se obtiene de las credenciales, sin selector de rol:

| Perfil | Usuario | Contraseña |
|---|---|---|
| Operador | `operador` | `AegisOperador2026!` |
| Administrador | `admin` | `AegisAdmin2026!` |

Son credenciales públicas de prototipo y no deben usarse como autenticación
real. En esta etapa no se necesita una cuenta externa.

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Abre `http://localhost:5500`. `aegis-intro.mp4` se reproduce desde el primer
momento; el formulario aparece cuando termina. Si no hay conexión al modelo, las
métricas y los historiales permanecen vacíos y el dashboard indica
**MODELO NO CONECTADO**. Solo los eventos recibidos completan las lecturas.

### Video de introducción

El video está en `frontend/public/media/aegis-intro.mp4` y se sirve directamente
desde el frontend local.

### Autenticación y eventos REST/WebSocket opcionales

Para consumir el login REST en lugar del simulado, configura:

```env
VITE_AUTH_API_URL=http://127.0.0.1:8000/api/login
```

La ruta `/api/login` es alias del backend para el prototipo; también se conserva
`/api/v1/auth/login`. El cliente no envía rol: el backend lo toma de la cuenta
Supabase autenticada. Para telemetría WebSocket configura en `.env`:

```env
VITE_WS_URL=ws://127.0.0.1:8000/ws/dashboard
```

El frontend enviará el JWT en el primer frame de autenticación, nunca en la URL.
Los orígenes web locales permitidos son `localhost:5500` y `127.0.0.1:5500`.

## Backend opcional con Supabase

```bash
cp backend/.env.example backend/.env
# Edita JWT_SECRET, SUPABASE_URL y SUPABASE_KEY.
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 1048576
```

Usa una clave Supabase server-side en `backend/.env`; nunca la copies al
frontend. Ejecuta `backend/sql/001_security_events.sql` en Supabase y asigna
`app_metadata.role` (`operator` o `admin`) a las cuentas. El perfil de la sesión
se obtiene desde Supabase, no desde un campo elegido en el navegador.

El servidor FastAPI también incluye:

- `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/me` y alias `/api/login`.
- `/ws/telemetry` para telemetría de operadores/admin; valida eventos, aplica
  umbrales de temperatura (>38 °C), 0 V, intrusión y Lockdown.
- `/ws/dashboard` para retransmitir eventos a clientes autenticados.
- `POST /api/v1/chat`, listo para un modelo local OpenAI-compatible al definir
  `LOCAL_AI_URL` y `LOCAL_AI_MODEL`.

## Funciones del prototipo

- **Métricas independientes:** consumo, aforo y temperatura tienen módulos
  propios. Sus gráficas se alimentan solo con telemetría recibida y guardan hasta
  siete días de muestras por métrica en el almacenamiento local del navegador;
  sin historial muestran el estado de espera.
- **Visor:** mantiene el contenedor vacío hasta recibir señal. La geometría del
  gemelo y la ubicación real de cámaras se integrarán al conectar el modelo.
- **Chat:** no informa lecturas mientras el modelo está desconectado. No cambia
  claves, puertas ni luces; la IA local aún no está conectada.
- **Lockdown, evacuación y cierre de jornada:** actualizan un estado simulado
  persistente en el navegador. El cierre puede programarse por hora y solo el
  perfil Administrador puede liberar el estado. No envía comandos físicos ni
  reemplaza un sistema de control de acceso certificado.

## Verificación

```bash
.venv/bin/pytest backend/tests -q
cd frontend && npm test && npm run build
```
