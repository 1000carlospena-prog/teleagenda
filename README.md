# TeleAgenda

Bot de Telegram + panel web en Django para programar publicaciones de **texto, imágenes y stickers** en uno o varios canales.

## Qué incluye

- Panel privado con inicio de sesión, estadísticas y filtros.
- Publicaciones de texto (HTML, MarkdownV2 o sin formato), imágenes con caption y stickers.
- Programación por fecha y hora con zona horaria configurable.
- Envío automático mediante un proceso programador independiente.
- Estados: programada, enviando, enviada, fallida y cancelada.
- Acciones: enviar ahora, reintentar, editar, duplicar, cancelar y eliminar.
- Configuración del token del bot desde el panel, sin editar archivos; permite cambiarlo o quitarlo.
- Detección de canales recientes desde el panel, sin usar `get_chat_ids`.
- Botón **Enviar ahora** al crear o editar publicaciones.
- Programaciones semanales: varios días y horas (con segundos opcionales) y opción de repetir todas las semanas.
- Verificación de canales con la API de Telegram y errores visibles.
- Vista previa aproximada del mensaje y atajos de programación.
- Registro de errores de Telegram y recuperación de envíos interrumpidos.

## Requisitos

- Python 3.12 o superior (probado con Python 3.14).
- Una cuenta de Telegram.
- Un bot creado con [@BotFather](https://t.me/BotFather).
- El bot agregado como **administrador** del canal con permiso para **publicar mensajes**.

## Instalación rápida (Windows)

La forma más rápida es ejecutar `instalar.bat` y luego editar `.env`.

Manualmente:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
```

Edita `.env` para la clave de Django y la zona horaria. El token del bot puedes guardarlo desde **Configuración → Token del bot** en el panel; también se acepta `TELEGRAM_BOT_TOKEN` en `.env` como respaldo:

```env
TELEGRAM_BOT_TOKEN=123456789:AA...tu-token...
TIME_ZONE=Etc/GMT+5
```

Después inicia los dos procesos:

```powershell
# Terminal 1: panel web
python manage.py runserver 127.0.0.1:8000

# Terminal 2: programador (debe quedar abierto)
python manage.py scheduler
```

O usa los accesos directos:

- `iniciar_todo.bat` abre el panel y el bot en dos ventanas.
- `iniciar_panel.bat` solo el panel.
- `iniciar_bot.bat` solo el programador.

Abre <http://127.0.0.1:8000> e inicia sesión.

## Conectar el bot y el canal

1. En Telegram abre [@BotFather](https://t.me/BotFather), envía `/newbot`, elige nombre y usuario.
2. En el panel entra a **Configuración → Token del bot** y pega el token. Si prefieres, también puedes usar `TELEGRAM_BOT_TOKEN` en `.env` como respaldo.
3. En tu canal: **Administradores → Agregar administrador → busca el bot → activa «Publicar mensajes»**.
4. En el panel entra a **Canales → Agregar canal**:
   - Canal público: usa `@usuario_del_canal` o `https://t.me/usuario_del_canal`.
   - Canal privado: usa el ID numérico que empieza con `-100`.
5. Pulsa el botón de verificación (✓) para comprobar la conexión.

Para obtener el ID de un canal privado:

```powershell
python manage.py get_chat_ids
```

Si no aparece nada, publica un mensaje en el canal (con el bot ya como administrador) o envía `/start` al bot y vuelve a ejecutar el comando.

## Uso del panel

1. **Nueva publicación**: elige canal y tipo, escribe el contenido, adjunta el archivo si aplica y define fecha y hora.
2. Revisa la vista previa y pulsa **Programar publicación**.
3. El programador revisa la cola cada pocos segundos y envía lo que ya venció. En **Programaciones** puedes crear una tarea con varios días/horas del panel; cada envío se crea como una publicación normal. Con «Publicar todas las semanas» se generan los envíos de la semana siguiente al llegar el lunes; para parar, detén la tarea desde esa lista.
4. En el panel puedes **Enviar ahora**, **Reintentar**, **Editar**, **Duplicar**, **Cancelar** o **Eliminar**.
5. Si el programador está detenido, las publicaciones quedan en cola y se envían cuando lo inicies.

### Estados

| Estado | Significado |
| --- | --- |
| Programada | En cola; se enviará al llegar la fecha. |
| Enviando | El programador la tomó y está enviándola. |
| Enviada | Telegram confirmó el envío. |
| Fallida | Telegram devolvió un error; el detalle aparece en la fila. |
| Cancelada | No se enviará. Puedes editarla para devolverla a la cola. |

## Límites de Telegram

- Texto: hasta **4096** caracteres.
- Caption de imagen: hasta **1024** caracteres.
- Imagen: JPG, PNG o WEBP de hasta **10 MB**.
- Sticker: WEBP, TGS o WEBM de hasta **512 KB**; no admite texto.
- El bot debe seguir siendo administrador del canal.

## Arquitectura

```
Navegador → Django (panel) → SQLite
                              ↑
                    manage.py scheduler → Bot API de Telegram
```

- El panel **no envía nada por sí solo**: solo crea y administra registros.
- El comando `scheduler` es el único que habla con Telegram para publicar.
- Los archivos se guardan en `media/` y la base de datos en `db.sqlite3`.
- La cabecera muestra si el programador está en línea (sondeo cada 20 s).

## Comandos

```powershell
python manage.py runserver          # panel web
python manage.py scheduler          # programador en bucle
python manage.py scheduler --once   # envía lo pendiente una vez y termina
python manage.py scheduler --interval 5
python manage.py get_chat_ids       # muestra chats/canales vistos por el bot
python manage.py createsuperuser
python manage.py changepassword aionx
python manage.py test               # pruebas automatizadas
```

## Configuración

Variables disponibles en `.env`:

| Variable | Descripción | Por defecto |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Respaldo opcional; normalmente se guarda desde Configuración (SQLite) | vacío |
| `TIME_ZONE` | Zona horaria del panel y la cola; `Etc/GMT+5` es Cuba UTC-05:00 | `Etc/GMT+5` |
| `SCHEDULER_INTERVAL` | Segundos entre revisiones | `10` |
| `WORKER_STALE_SECONDS` | Segundos sin señal para marcar el bot caído | `90` |
| `TELEGRAM_TIMEOUT` | Timeout de las peticiones a Telegram | `60` |
| `DJANGO_DEBUG` | Modo depuración | `True` |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos, separados por coma | `127.0.0.1,localhost` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Orígenes confiables para HTTPS | vacío |

El token guardado desde **Configuración** se aplica sin reiniciar procesos. Los demás cambios de `.env` sí requieren reiniciar el panel y el programador.

## Puesta en producción

- Pon `DJANGO_DEBUG=False` y configura `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Sirve el panel con un servidor WSGI (Waitress en Windows, Gunicorn en Linux) detrás de HTTPS.
- Usa WhiteNoise o Nginx para los archivos estáticos.
- Mantén `python manage.py scheduler` como servicio (NSSM, systemd o el Programador de tareas de Windows).
- No expongas el comando del programador por web.
- Haz copias de seguridad de `db.sqlite3` y de la carpeta `media/`.
- Si vas a tener mucho tráfico o varios programadores, migra a PostgreSQL y usa un solo worker para evitar duplicados.
- Nunca subas `.env`, `db.sqlite3` ni `media/` a un repositorio.

## Despliegue en EasyPanel desde Git

El repo incluye `Dockerfile` y `supervisord.conf`, así que EasyPanel solo debe compilar la imagen y levantar un servicio.

1. Sube este proyecto a GitHub y crea el app en EasyPanel con **Deploy from Git**.
2. Selecciona el repo y la rama principal; el tipo de build debe ser **Dockerfile**.
3. Expone el puerto `8000`.
4. Crea un volumen persistente y móntalo en `/app/data`. Crea otro para `/app/media`.
5. Configura estas variables de entorno en EasyPanel:
   - `DJANGO_SECRET_KEY`: clave larga y aleatoria nueva.
   - `DJANGO_DEBUG=False`.
   - `DJANGO_ALLOWED_HOSTS`: el dominio que te dé EasyPanel, separado por comas si hay varios.
   - `DJANGO_CSRF_TRUSTED_ORIGINS`: `https://tu-dominio.easypanel.host` (con `https://`).
   - `TIME_ZONE=Etc/GMT+5` para hora de Cuba.
   - `DB_PATH=/app/data/db.sqlite3`.
   - `MEDIA_ROOT_PATH=/app/media`.
   - `SCHEDULER_INTERVAL=10`.
6. El contenedor ejecuta las migraciones, levanta Gunicorn y levanta el programador automáticamente con Supervisor.
7. Crea el superusuario una vez desde la consola del contenedor:
   `python manage.py createsuperuser`.
8. Entra al panel, guarda el token del bot en **Configuración**, detecta o agrega el canal y prueba el envío.

No pongas `TELEGRAM_BOT_TOKEN` en EasyPanel: el panel lo guarda en la base SQLite persistente. Si lo pones en el entorno, tendrá prioridad el valor guardado desde el panel.

## Solución de problemas

- **«chat not found»**: revisa el chat ID y que el bot siga en el canal.
- **«not enough rights»**: activa «Publicar mensajes» para el bot.
- **No se envía nada**: verifica que el programador esté corriendo; la cabecera debe decir «Programador en línea».
- **Error de HTML/Markdown**: Telegram rechaza etiquetas mal cerradas o caracteres sin escapar; revisa el detalle en la fila.
- **Hora incorrecta**: ajusta `TIME_ZONE` en `.env` y reinicia ambos procesos.
- **Sticker rechazado**: debe ser WEBP/TGS/WEBM, pesar menos de 512 KB y ser un sticker válido.

## Para agentes de código

Las convenciones, comandos y reglas de verificación para asistentes o desarrolladores están en [AGENTS.md](AGENTS.md).

## Estructura del proyecto

```
config/                 Configuración Django
posts/
  models.py             Canales, publicaciones, programaciones semanales y estado del programador
  forms.py              Validación de formularios
  views.py              Panel web
  services/telegram.py  Cliente de la Bot API
  management/commands/  scheduler y get_chat_ids
templates/              Interfaz del panel
static/                 CSS y JavaScript
media/                  Archivos subidos (se crea al usarlo)
```
