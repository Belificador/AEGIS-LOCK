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

La interfaz autentica siempre contra la API AEGIS; el frontend no crea sesiones
simuladas ni contiene contraseñas. El rol se obtiene de PostgreSQL y no de un
valor elegido en el navegador. Usa únicamente una cuenta de prueba cuya
contraseña se te haya entregado por un canal privado; no se publican credenciales
en este repositorio.

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
de Render (las variables `VITE_*` se incorporan al JavaScript y son públicas):

El navegador llama a FastAPI; FastAPI valida la sesión y consulta PostgreSQL. El
navegador nunca recibe la URL ni las credenciales de la base de datos.

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
pip install -r requirements-dev.txt
pip-audit -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 1048576
```

En el **Backend API de Render** configura `ENVIRONMENT=production`, `DATABASE_URL`,
`JWT_SECRET`, `PIN_ENCRYPTION_KEY`, `RATE_LIMIT_STORAGE_URI`, `TELEMETRY_API_KEY`,
`GEMELO_MEDIA_BASE_URL`, `DEMO_OPERATOR_PASSWORD`, `DEMO_ADMIN_PASSWORD`,
`OPENROUTER_API_KEY` y `ALLOWED_ORIGINS`. Si quieres recibir alertas críticas inmediatas,
configura también `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_MAP` y
`TELEGRAM_WEBHOOK_SECRET`. El mapa tiene el formato
`telegram_user_id` o `telegram_user_id:aegis_username`, separado por comas. Los IDs
sin cuenta vinculada reciben el rol de solo lectura `operator`; las cuentas
vinculadas deben existir y estar habilitadas en AEGIS. Cada usuario debe iniciar
el bot con `/start`. El webhook secret
debe ser aleatorio, de al menos 32 caracteres, y contener solo letras, números,
guion o guion bajo. Usa contraseñas aleatorias, únicas por entorno y guardadas
solo como Render Secrets. `PIN_ENCRYPTION_KEY` debe ser independiente de
`JWT_SECRET`; los PIN cifrados antes de esa clave nueva se descifran con el
`JWT_SECRET` existente, así que no lo rotes hasta que esos PIN expiren o se
re-emitan. `RATE_LIMIT_STORAGE_URI` debe usar la URL interna de un Render Key
Value privado con política `noeviction` para no expulsar contadores activos.
Al iniciar, el backend crea el esquema y guarda hashes scrypt de las contraseñas;
nunca pongas secretos en variables `VITE_*` ni en el frontend. No despliegues la
versión endurecida hasta cargar `PIN_ENCRYPTION_KEY` y la conexión interna de
Key Value en el servicio API.
`/health` comprueba también la conexión a la base.

Antes del deploy endurecido, crea un Key Value en la misma región del servicio
API, con acceso externo deshabilitado y política `noeviction`; copia su URL
interna en `RATE_LIMIT_STORAGE_URI` como secreto del servicio. Para generar una
clave localmente usa `python -c 'import secrets; print(secrets.token_urlsafe(48))'`
y registra cada resultado directamente en Render, nunca en Git. Rota también las
contraseñas demo usadas por revisiones antiguas, porque permanecen en el historial
Git aunque ya no estén en los archivos actuales.

El simulador se conecta al relay del servidor del gemelo en `/ws/telemetry` con
la sesión web existente. `server.js` abre el WebSocket saliente a
`wss://aegis-lock-api.onrender.com/ws/telemetry` y manda `TELEMETRY_API_KEY` en
el header HTTP `Authorization`; configura el mismo secreto como
`AEGIS_TELEMETRY_API_KEY` en Render para el gemelo. La clave no se incluye en
ningún JavaScript del navegador.

Los feeds se sirven desde el gemelo con una firma HMAC temporal verificada en
Node; los archivos de `/assets/cameras` siguen protegidos y no se exponen como
una carpeta pública.

El servidor FastAPI también incluye:

- `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/me` y alias `/api/login`.
- `/api/v1/pins/generate`, `/api/v1/pins`, `/api/v1/pins/{id}`, `/api/v1/pins/doors` y validación interna de PINes temporales; Admin gestiona PINes, el Node del gemelo los valida y PostgreSQL conserva su hash/cifrado y vencimiento.
- `/api/v1/analytics/history`, `/api/v1/analytics/errors` y `/api/v1/audit`, protegidas según rol; Admin ve picos, errores y auditoría.
- `/api/v1/cameras/{camera_id}/feed-url` genera URLs HMAC temporales; el video sigue servido por el gemelo sin hacer pública la carpeta de cámaras.
- `target_user` en un PIN es metadato de asignación/auditoría; el teclado de puerta actual identifica el PIN, no a la persona.
- `/ws/telemetry` para emisores autenticados por JWT o por la credencial privada
  servidor-a-servidor; normaliza y valida sobres del gemelo, evalúa umbrales de
  temperatura (>38 °C), 0 V, intrusión y Lockdown, y persiste en PostgreSQL.
- `/ws/dashboard` para retransmitir eventos a clientes autenticados y medir RTT
  con ping/pong de aplicación.
- `POST /api/v1/chat`, asistente Argus con herramientas limitadas y OpenRouter.
- Desde el chat del dashboard, el perfil Administrador puede pedir explícitamente
  `envía el informe general por Telegram`. Argus envía los agregados solo al chat
  privado vinculado a esa cuenta AEGIS, sin aceptar un destino elegido por el modelo.
- `POST /api/v1/telegram/webhook`, Hermes para usuarios autorizados. Resuelve consultas
  de Argus sin historial conversacional ni acciones de escritura desde Telegram.
- Lockdown y evacuación generan avisos al registrarse en auditoría; los accesos
  autorizados de entrada y los cambios de aforo durante evacuación también pueden
  notificar a los IDs autorizados. Los conteos requieren telemetría reciente.
- `python -m backend.jobs.daily_argus_report`, ejecutado por GitHub Actions para
  resumir el día anterior y enviar el reporte a Telegram.

## Funciones del prototipo

- **Métricas independientes:** consumo, aforo y temperatura tienen módulos
  propios. Sus gráficas se alimentan solo con telemetría recibida y guardan hasta
  siete días de muestras por métrica en el almacenamiento local del navegador;
  sin historial muestran el estado de espera.
- **Visor:** carga `models_3d/oficina/edificio.glb`, destaca zonas al recibir
  eventos y permite seleccionar marcadores 3D de las nueve cámaras del gemelo.
  Sus posiciones se mantienen en una tabla ajustable por zona/navgrid.
- **Alarma:** PIN denegado, intrusión, 0 V y temperatura crítica muestran un
  overlay rojo con sonido. El acuse detiene la alarma y registra al operador en
  PostgreSQL.
- **Diagnóstico Admin:** incluye picos de temperatura y potencia/energía
  estimada, desconexiones/403 de la caja negra y gestión de PINes temporales.
- **Argus:** consulta actividad, estado, canales y PINes mediante herramientas
  de backend limitadas por rol. No ejecuta comandos de shell ni controla
  actuadores físicos; el modelo solo propone herramientas autorizadas.
- **Lockdown, evacuación y cierre de jornada:** actualizan un estado simulado
  persistente en el navegador. El cierre puede programarse por hora y solo el
  perfil Administrador puede liberar el estado. No envía comandos físicos ni
  reemplaza un sistema de control de acceso certificado.

### Señales de seguridad que deben vigilarse

- Ráfagas de `LOGIN_FAILED`, `REFRESH_REJECTED`, `401`, `403` y `429`, agrupadas
  por cuenta, IP y ruta. Nunca se registran contraseñas ni tokens.
- Repeticiones de `PIN_VALIDATION_DENIED` o `LOCKOUT` por puerta; correlaciona
  con generación/revocación de PINes y quién hizo el cambio.
- `WebSocket Authentication Failure`, rechazos por origen, desconexiones
  reiteradas y `telemetry_validation_rejected` por fuente.
- Picos de intrusión, pérdida de energía, temperatura crítica, selección
  inusual de cámaras y activación/liberación de protocolos.

Los eventos de auditoría de cuentas, PINes y modos se guardan en PostgreSQL; los
rechazos de tráfico y límites aparecen como logs estructurados de Render. Configura
alertas operativas sobre ráfagas, no sobre una sola señal aislada.

## Verificación

```bash
.venv/bin/pytest backend/tests -q
pip-audit -r requirements.txt
pip-audit -r requirements-dev.txt
npm audit --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

### GitHub Actions para el reporte diario de Argus

Crea el workflow `.github/workflows/argus-daily-report.yml` en la rama principal.
Incluye `schedule` y `workflow_dispatch` para que el reporte corra diariamente y
pueda probarse manualmente. El horario configurado es 08:00 UTC.

GitHub Actions necesita estos Repository Secrets: `ARGUS_REPORT_DATABASE_URL`,
`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`. Las claves
configuradas en Render no se copian automáticamente a GitHub.

El workflow no necesita `DATABASE_URL` con permisos de escritura. Crea un usuario
PostgreSQL de solo lectura y dale `CONNECT` a la base, `USAGE` en el esquema y
`SELECT` únicamente en `security_events`, `latest_telemetry` y `audit_logs`; guarda
su conexión externa en `ARGUS_REPORT_DATABASE_URL`. El workflow define
`ENVIRONMENT=production`, `AEGIS_SERVICE_ROLE=argus_cron`,
`OPENROUTER_APP_NAME=AEGIS LOCK - ARGUS` y `ARGUS_REPORT_TIMEZONE=UTC`.
No guardes estas claves en el YAML ni en variables `VITE_*`.

El reporte calcula los indicadores en PostgreSQL y envía a OpenRouter solo
agregados; no manda PINes ni nombres. Para que entradas y salidas se distingan,
el gemelo debe incluir `metadata.pin_id` y
`metadata.access_direction` (`entry` o `exit`) en los eventos de acceso para
contar entradas y salidas confirmadas. Sin esos campos, Argus informa los accesos
autorizados pero marca su dirección como desconocida.

Para registrar el webhook después de desplegar la API, invoca `setWebhook` desde un
terminal privado, usando el token y secreto configurados en Render:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://aegis-lock-api.onrender.com/api/v1/telegram/webhook\",\"secret_token\":\"${TELEGRAM_WEBHOOK_SECRET}\",\"allowed_updates\":[\"message\"]}"
```

No guardes el comando con valores reales en Git. El endpoint verifica el header
`X-Telegram-Bot-Api-Secret-Token`, limita Hermes a mensajes privados vinculados
con cuentas AEGIS habilitadas y procesa cada `update_id` una sola vez. Telegram
usa herramientas de solo lectura durante esta primera versión. `TELEGRAM_CHAT_ID` en GitHub
Actions sigue siendo el único destino del reporte diario; los mensajes del webhook
responden al chat que originó la consulta.
