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
  services/               PostgreSQL, reglas y adaptador de IA local
  sql/                    Esquema PostgreSQL aplicado al iniciar
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

La interfaz local conserva estas cuentas de demostración; el perfil se obtiene
del registro de cuenta y no de un rol elegido en el navegador:

| Perfil | Usuario | Contraseña |
|---|---|---|
| Operador | `operador` | `AegisOperador2026!` |
| Administrador | `admin` | `AegisAdmin2026!` |

Son credenciales públicas de prototipo y no deben usarse fuera de la presentación.
En Render se conservan como usuarios de prueba, pero el backend verifica sus
contraseñas y guarda únicamente hashes en PostgreSQL.

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

### Autenticación manual y eventos REST/WebSocket

El formulario envía las credenciales a Aegis y obtiene el JWT que exige
`/ws/dashboard`. Configura estos valores en el entorno de build del Static Site
de Render (las variables `VITE_*` se incorporan al compilar):

```env
VITE_AUTH_API_URL=https://aegis-lock-api.onrender.com/api/login
VITE_WS_URL=wss://aegis-lock-api.onrender.com/ws/dashboard
```

La ruta `/api/login` es alias de `/api/v1/auth/login`. El backend toma el rol de
PostgreSQL; el JWT se envía en el primer frame WebSocket, nunca en la URL. Para
apuntar al backend local, sobrescribe `VITE_WS_URL`:

```env
VITE_WS_URL=ws://127.0.0.1:8000/ws/dashboard
```

Los orígenes web locales permitidos son `localhost:5500` y `127.0.0.1:5500`.

## Backend con Render PostgreSQL

```bash
cp backend/.env.example backend/.env
# DATABASE_URL es opcional en local; en Render usa la Internal Database URL.
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 1048576
```

En Render crea `DATABASE_URL`, `JWT_SECRET`, `TELEMETRY_API_KEY`,
`DEMO_OPERATOR_PASSWORD`, `DEMO_ADMIN_PASSWORD` y `ALLOWED_ORIGINS`. Guarda como
secretos los valores sensibles. Para las dos cuentas de prueba usa las
contraseñas actuales de la tabla de arriba. Al iniciar, el backend crea el
esquema y siembra los usuarios con hash scrypt; no pegues la URL de conexión en
el frontend ni en el repositorio. `/health` comprueba también la conexión a la
base.

El simulador se conecta al relay del servidor del gemelo en `/ws/telemetry` con
la sesión web existente. `server.js` abre el WebSocket saliente a
`wss://aegis-lock-api.onrender.com/ws/telemetry` y manda `TELEMETRY_API_KEY` en
el header HTTP `Authorization`; configura el mismo secreto como
`AEGIS_TELEMETRY_API_KEY` en Render para el gemelo. La clave no se incluye en
ningún JavaScript del navegador.

El servidor FastAPI también incluye:

- `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/me` y alias `/api/login`.
- `/ws/telemetry` para emisores autenticados por JWT o por la credencial privada
  servidor-a-servidor; normaliza y valida sobres del gemelo, evalúa umbrales de
  temperatura (>38 °C), 0 V, intrusión y Lockdown, y persiste en PostgreSQL.
- `/ws/dashboard` para retransmitir eventos a clientes autenticados.
- `POST /api/v1/chat`, listo para un modelo local OpenAI-compatible al definir
  `LOCAL_AI_URL` y `LOCAL_AI_MODEL`.

## Funciones del prototipo

- **Métricas independientes:** consumo, aforo y temperatura tienen módulos
  propios. Sus gráficas se alimentan solo con telemetría recibida y guardan hasta
  siete días de muestras por métrica en el almacenamiento local del navegador;
  sin historial muestran el estado de espera.
- **Visor:** carga `models_3d/oficina/edificio.glb` en el viewport central. Las
  alertas de temperatura, voltaje y acceso resaltan zonas identificadas por el
  nombre de nodo del modelo o por `metadata.nodo_3d`/`metadata.node_name`; la
  cámara seleccionada abre el feed suministrado en `metadata`.
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
