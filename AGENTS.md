# AGENTS.md

Guía para agentes de código que trabajen en este repositorio.

## Proyecto

**TeleAgenda** es un panel web en Django para programar publicaciones de texto, imágenes y stickers en canales de Telegram. El panel administra la cola en SQLite; un proceso independiente (`manage.py scheduler`) es el único que envía mensajes a la Bot API.

- Idioma de la interfaz, mensajes y documentación: **español**.
- Entorno principal: **Windows + PowerShell**.
- No hay repositorio Git inicializado actualmente.

## Stack

- Python 3.12+ (probado con 3.14).
- Django 6.1.3, SQLite, `requests`, `python-dotenv`.
- Templates de Django, CSS y JavaScript vanilla (sin frameworks de frontend).
- Scripts de arranque en `.bat`.

## Lenguajes y protocolos

- **Backend:** Python 3.12+ con Django 6.1.3: ORM, vistas, templates, autenticación y migraciones.
- **Base de datos:** SQLite local (`db.sqlite3`) a través del ORM de Django.
- **Frontend:** HTML5, CSS3 y JavaScript ES6+ vanilla, sin bundler ni frameworks. El panel usa `fetch` para consultar `/estado/` cada 20 segundos y actualizar el estado del worker y los contadores.
- **Panel web:** HTTP en desarrollo (`127.0.0.1:8000`); en producción debe servirse por HTTPS. Usa sesiones con cookies, formularios con protección CSRF y contraseñas hasheadas por Django.
- **Configuración del bot:** el token se guarda desde el panel en la base SQLite (`BotConfig`). `TELEGRAM_BOT_TOKEN` en `.env` sigue funcionando como respaldo opcional.
- **Telegram Bot API:** HTTPS contra `https://api.telegram.org`. Peticiones `POST` con datos de formulario y `multipart/form-data` para adjuntar imágenes o stickers; respuestas JSON. Métodos usados: `getMe` y `getChat` para verificar el bot/canal, `getUpdates` en `get_chat_ids`, y `sendMessage`, `sendPhoto` y `sendSticker` para publicar.
- **Sin webhooks ni WebSocket:** el panel no recibe eventos de Telegram. El scheduler consulta la base de datos SQLite y envía; no hay cola externa ni worker distribuido.
- **Fechas:** se guardan en UTC (`USE_TZ=True`) y se muestran en la zona IANA configurada en `TIME_ZONE` (por defecto `Etc/GMT+5` = Cuba UTC-05:00).
- **Archivos:** se almacenan en el sistema de archivos local, dentro de `media/`.
- **Automatización:** procesos de consola Python, scripts `.bat` y PowerShell.

## Comandos

Usa el Python del entorno virtual:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
node --check static/js/app.js

.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
.\.venv\Scripts\python.exe manage.py scheduler
.\.venv\Scripts\python.exe manage.py scheduler --once
.\.venv\Scripts\python.exe manage.py get_chat_ids
.\.venv\Scripts\python.exe manage.py makemigrations
.\.venv\Scripts\python.exe manage.py migrate
```

No hay linter configurado. Antes de dar por terminado un cambio ejecuta `manage.py check`, los tests y `node --check` si tocaste JavaScript.

## Arquitectura

- `config/`: configuración Django; `TIME_ZONE` y el token se leen del `.env`.
- `posts/models.py`: `Channel`, `Post`, `ScheduleRule`, `WorkerState` y `BotConfig`, límites de Telegram y validaciones. `ScheduleRule.generate_initial()` crea publicaciones normales; `expand_schedule_rules()` genera la semana siguiente para las reglas activas con `repeat_weekly`.
- `posts/forms.py`: validación de canales y publicaciones.
- `posts/views.py`: panel, CRUD, acciones y endpoint de estado.
- `posts/services/telegram.py`: cliente centralizado de la Bot API.
- `posts/management/commands/scheduler.py`: worker que expande las programaciones semanales, reclama y envía publicaciones vencidas.
- `templates/posts/bot_settings.html`: configuración del token desde el panel; permite cambiarlo y quitarlo.
- `templates/posts/channel_discover.html`: detección de canales recientes desde Telegram.
- `templates/`: interfaz del panel.
- `static/css/app.css` y `static/js/app.js`: estilos e interacciones; no hay build step.
- `db.sqlite3`, `media/` y `.env`: datos locales; nunca deben versionarse.
- `Dockerfile`, `supervisord.conf` y `.dockerignore`: despliegue en EasyPanel con Gunicorn + scheduler en un mismo contenedor.

### Flujo de envío

1. El panel crea un `Post` en estado `programada`.
2. El scheduler busca publicaciones vencidas, las pasa a `enviando` y llama a `send_post`.
3. Si Telegram confirma, marca `enviada`; si falla, guarda el error y marca `fallida`.
4. El panel solo consulta el estado; **no envía mensajes desde las vistas**.

## Reglas de desarrollo

- Mantén toda la interfaz y los textos visibles en español.
- Respeta los tokens y clases existentes de `app.css`; evita estilos inline.
- No agregues frameworks JS ni dependencias nuevas sin necesidad.
- Cualquier envío a Telegram debe pasar por `posts/services/telegram.py` y ejecutarse desde el scheduler.
- Respeta los límites: texto 4096, caption 1024, imagen JPG/PNG/WEBP 10 MB, sticker WEBP/TGS/WEBM 512 KB.
- Si cambias modelos, crea la migración correspondiente y ejecútala.
- Agrega o actualiza tests en `posts/tests.py` para cambios de comportamiento.
- No incluyas secretos, tokens, contraseñas ni rutas locales sensibles en el código ni en la documentación.
- No ejecutes procesos en segundo plano sin detenerlos al terminar la verificación.
- Los archivos de prueba o canales temporales deben eliminarse antes de finalizar.

## Configuración

Variables en `.env` (ver `.env.example`): `TELEGRAM_BOT_TOKEN`, `TIME_ZONE`, `SCHEDULER_INTERVAL`, `WORKER_STALE_SECONDS`, `TELEGRAM_TIMEOUT`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS`.

El token normalmente se guarda desde **Configuración** en el panel y se almacena en SQLite; si existe, tiene prioridad sobre `.env`. El panel y el scheduler lo leen en cada uso, así que un token nuevo se aplica sin reiniciar procesos. Si usas el respaldo de `.env`, reinicia ambos.

El bot debe ser administrador del canal con permiso para publicar mensajes.

## Crear y conectar el bot de Telegram

1. Abre Telegram y busca **@BotFather** (la cuenta oficial con verificación).
2. Envía `/newbot`, elige un nombre visible y un usuario que termine en `bot`.
3. Copia el token que devuelve BotFather (formato `123456789:AA...`). Es un secreto: no lo subas al repositorio ni lo compartas.
4. En el panel entra a **Configuración → Token del bot** y pega el token. Se guarda en SQLite y no se vuelve a mostrar. `TELEGRAM_BOT_TOKEN` en `.env` queda como respaldo opcional.
5. Crea el canal o usa uno existente. En Telegram entra en **Administradores → Agregar administrador → selecciona el bot → activa «Publicar mensajes»**. El bot debe seguir siendo administrador.
6. No hace falta reiniciar: el panel y el scheduler leen el token guardado en cada uso.
7. En el panel entra a **Canales → Agregar canal**:
   - Canal público: `@usuario_del_canal` o `https://t.me/usuario_del_canal`.
   - Canal privado: el ID numérico que empieza por `-100`.
8. Pulsa el botón de verificación del canal. La verificación consulta `getChat`; la guía consulta `getMe` para mostrar los datos del bot.
9. Si no conoces el ID de un canal privado, publica un mensaje en el canal con el bot ya como administrador y ejecuta:
   ```powershell
   .\.venv\Scripts\python.exe manage.py get_chat_ids
   ```
10. Haz una prueba: crea una publicación de texto, progránala para dentro de unos minutos o usa **Enviar ahora**, y confirma que pasa a **Enviada**.

Si Telegram responde «chat not found» o «not enough rights», revisa el ID y los permisos del bot. Si el token se filtra, usa `/revoke` en BotFather y actualiza `.env`.

## Verificación mínima

```powershell
node --check static/js/app.js
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

La suite actual tiene 51 pruebas. Un cambio está listo cuando los tests pasan, no hay migraciones pendientes y la interfaz probada no deja datos temporales.
