import signal
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from posts.models import Post, WorkerState, expand_schedule_rules
from posts.services.telegram import TelegramError, get_bot_token, send_post


class Command(BaseCommand):
    help = "Envía las publicaciones programadas que ya llegaron a su fecha."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Revisa una sola vez, envía lo pendiente y termina.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=settings.SCHEDULER_INTERVAL,
            help=f"Segundos entre revisiones (por defecto {settings.SCHEDULER_INTERVAL}).",
        )

    def handle(self, *args, **options):
        if not get_bot_token():
            self.stdout.write(
                self.style.WARNING(
                    "No hay token del bot configurado. El programador seguirá activo "
                    "y lo tomará cuando lo guardes desde Configuración en el panel."
                )
            )

        interval = max(3, options["interval"])
        once = options["once"]

        self.recover_stale()
        state = WorkerState.get_solo()
        state.running = True
        state.started_at = timezone.now()
        state.last_seen = timezone.now()
        state.save(update_fields=["running", "started_at", "last_seen"])

        stopping = {"value": False}

        def stop_handler(signum, frame):
            stopping["value"] = True

        previous_handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous_handlers[sig] = signal.signal(sig, stop_handler)
            except (ValueError, OSError):
                pass

        self.stdout.write(
            self.style.SUCCESS(
                f"Programador iniciado. Revisando cada {interval}s. Ctrl+C para detener."
            )
        )

        try:
            while not stopping["value"]:
                WorkerState.objects.filter(pk=1).update(
                    running=True, last_seen=timezone.now()
                )
                expand_schedule_rules()
                self.process_due()
                if once:
                    break
                for _ in range(interval):
                    if stopping["value"]:
                        break
                    time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            WorkerState.objects.filter(pk=1).update(
                running=False, last_seen=timezone.now()
            )
            for sig, handler in previous_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass
            self.stdout.write(self.style.WARNING("Programador detenido."))

    def process_due(self):
        if not get_bot_token():
            return

        now = timezone.now()
        due_ids = list(
            Post.objects.filter(
                status=Post.Status.SCHEDULED,
                scheduled_at__lte=now,
                channel__is_active=True,
            )
            .order_by("scheduled_at")
            .values_list("pk", flat=True)[:10]
        )

        for post_id in due_ids:
            claimed = Post.objects.filter(
                pk=post_id, status=Post.Status.SCHEDULED
            ).update(
                status=Post.Status.SENDING,
                started_at=timezone.now(),
                updated_at=timezone.now(),
            )
            if not claimed:
                continue

            try:
                post = Post.objects.select_related("channel").get(pk=post_id)
            except Post.DoesNotExist:
                continue
            try:
                message_id = send_post(post)
            except TelegramError as exc:
                self.fail(post, str(exc))
            except Exception as exc:  # noqa: BLE001 - el worker debe seguir vivo
                self.fail(post, f"Error inesperado: {exc}")
            else:
                Post.objects.filter(pk=post_id).update(
                    status=Post.Status.SENT,
                    sent_at=timezone.now(),
                    telegram_message_id=message_id,
                    error_text="",
                    started_at=None,
                    updated_at=timezone.now(),
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{timezone.localtime():%d/%m %H:%M:%S}] Enviada #{post.pk} "
                        f"a {post.channel.name}."
                    )
                )

    def fail(self, post, message):
        message = (message or "Error desconocido")[:1000]
        Post.objects.filter(pk=post.pk).update(
            status=Post.Status.FAILED,
            error_text=message,
            started_at=None,
            updated_at=timezone.now(),
        )
        self.stdout.write(
            self.style.ERROR(
                f"[{timezone.localtime():%d/%m %H:%M:%S}] Falló #{post.pk} "
                f"({post.channel.name}): {message}"
            )
        )

    def recover_stale(self):
        cutoff = timezone.now() - timedelta(minutes=10)
        stale = Post.objects.filter(
            Q(status=Post.Status.SENDING),
            Q(started_at__lt=cutoff) | Q(started_at__isnull=True, updated_at__lt=cutoff),
        )
        count = stale.count()
        if count:
            stale.update(
                status=Post.Status.FAILED,
                error_text=(
                    "El envío se interrumpió porque el programador se detuvo. "
                    "Verifica el canal antes de reintentar."
                ),
                started_at=None,
                updated_at=timezone.now(),
            )
            self.stdout.write(
                self.style.WARNING(
                    f"Se marcaron {count} publicación(es) interrumpidas como fallidas."
                )
            )
