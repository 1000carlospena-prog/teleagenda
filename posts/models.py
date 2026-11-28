import re
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_STICKER_BYTES = 512 * 1024
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
STICKER_EXTENSIONS = {".webp", ".tgs", ".webm"}

WEEKDAY_CHOICES = [
    (0, "Lunes"),
    (1, "Martes"),
    (2, "Miércoles"),
    (3, "Jueves"),
    (4, "Viernes"),
    (5, "Sábado"),
    (6, "Domingo"),
]
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")


def post_file_path(instance, filename):
    extension = Path(filename).suffix.lower()[:10]
    return f"publicaciones/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


def _file_size(uploaded_file):
    try:
        return uploaded_file.size
    except (OSError, ValueError):
        return None


class Channel(models.Model):
    name = models.CharField("nombre", max_length=120)
    chat_id = models.CharField(
        "chat ID",
        max_length=120,
        unique=True,
        help_text="Ejemplo: @mi_canal o -1001234567890",
    )
    is_active = models.BooleanField("activo", default=True)
    last_check_at = models.DateTimeField("última verificación", null=True, blank=True)
    last_check_ok = models.BooleanField("verificación correcta", null=True, blank=True)
    last_check_error = models.CharField("error de verificación", max_length=500, blank=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)

    class Meta:
        verbose_name = "canal"
        verbose_name_plural = "canales"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.chat_id})"

    def mark_check(self, ok: bool, error: str = ""):
        self.last_check_at = timezone.now()
        self.last_check_ok = ok
        self.last_check_error = (error or "")[:500]
        self.save(update_fields=["last_check_at", "last_check_ok", "last_check_error"])


class Post(models.Model):
    class Kind(models.TextChoices):
        TEXT = "texto", "Texto"
        PHOTO = "imagen", "Imagen"
        STICKER = "sticker", "Sticker"

    class Status(models.TextChoices):
        SCHEDULED = "programada", "Programada"
        SENDING = "enviando", "Enviando"
        SENT = "enviada", "Enviada"
        FAILED = "fallida", "Fallida"
        CANCELLED = "cancelada", "Cancelada"

    class ParseMode(models.TextChoices):
        HTML = "HTML", "HTML"
        MARKDOWN = "MarkdownV2", "Markdown (V2)"
        NONE = "", "Sin formato"

    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="posts",
        verbose_name="canal",
    )
    rule = models.ForeignKey(
        "posts.ScheduleRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posts",
        verbose_name="programación semanal",
    )
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, default=Kind.TEXT)
    text = models.TextField("texto", blank=True)
    file = models.FileField("archivo", upload_to=post_file_path, blank=True)
    parse_mode = models.CharField(
        "formato",
        max_length=12,
        choices=ParseMode.choices,
        default=ParseMode.HTML,
        blank=True,
    )
    disable_preview = models.BooleanField("sin vista previa de enlaces", default=False)
    scheduled_at = models.DateTimeField("programada para", db_index=True)
    status = models.CharField(
        "estado",
        max_length=12,
        choices=Status.choices,
        default=Status.SCHEDULED,
        db_index=True,
    )
    started_at = models.DateTimeField("inicio del envío", null=True, blank=True)
    sent_at = models.DateTimeField("enviada", null=True, blank=True)
    telegram_message_id = models.BigIntegerField("ID del mensaje en Telegram", null=True, blank=True)
    error_text = models.TextField("último error", blank=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "publicación"
        verbose_name_plural = "publicaciones"
        ordering = ["-scheduled_at", "-id"]
        indexes = [models.Index(fields=["status", "scheduled_at"], name="posts_status_sched_idx")]

    def __str__(self):
        return f"{self.get_kind_display()} para {self.channel.name} · {self.scheduled_at:%d/%m/%Y %H:%M}"

    @property
    def scheduled_time_label(self):
        value = timezone.localtime(self.scheduled_at)
        return value.strftime("%H:%M:%S" if value.second else "%H:%M")

    @property
    def file_extension(self):
        return Path(self.file.name).suffix.lower() if self.file else ""

    @property
    def is_previewable_image(self):
        return self.file_extension in PHOTO_EXTENSIONS

    @property
    def is_previewable_sticker(self):
        return self.file_extension == ".webp"

    @property
    def can_edit(self):
        return self.status in {self.Status.SCHEDULED, self.Status.FAILED, self.Status.CANCELLED}

    @property
    def can_send_now(self):
        return self.status in {self.Status.SCHEDULED, self.Status.FAILED, self.Status.CANCELLED}

    @property
    def can_cancel(self):
        return self.status in {self.Status.SCHEDULED, self.Status.FAILED}

    @property
    def text_limit(self):
        return 4096 if self.kind == self.Kind.TEXT else 1024

    @property
    def content_preview(self):
        if self.text:
            return " ".join(self.text.split())
        if self.file:
            return Path(self.file.name).name
        return "(sin contenido)"

    def clean(self):
        super().clean()
        self.text = (self.text or "").strip()

        if self.kind == self.Kind.TEXT:
            if not self.text:
                raise ValidationError({"text": "Escribe el texto de la publicación."})
            if len(self.text) > 4096:
                raise ValidationError({"text": "Telegram permite hasta 4096 caracteres en un mensaje."})
            if self.file:
                raise ValidationError({"file": "El tipo Texto no admite archivo. Elige Imagen o Sticker."})
        elif self.kind == self.Kind.PHOTO:
            if not self.file:
                raise ValidationError({"file": "Adjunta una imagen para este tipo de publicación."})
            if len(self.text) > 1024:
                raise ValidationError({"text": "El caption de una imagen admite hasta 1024 caracteres."})
            if self.file_extension not in PHOTO_EXTENSIONS:
                raise ValidationError({"file": "Formato no válido. Usa JPG, PNG o WEBP."})
            size = _file_size(self.file)
            if size is not None and size > MAX_PHOTO_BYTES:
                raise ValidationError({"file": "La imagen supera el límite de 10 MB de Telegram."})
        elif self.kind == self.Kind.STICKER:
            if not self.file:
                raise ValidationError({"file": "Adjunta un sticker (.webp, .tgs o .webm)."})
            if self.text:
                raise ValidationError({"text": "Los stickers no llevan texto ni caption."})
            if self.file_extension not in STICKER_EXTENSIONS:
                raise ValidationError({"file": "Formato no válido. Usa WEBP, TGS o WEBM."})
            size = _file_size(self.file)
            if size is not None and size > MAX_STICKER_BYTES:
                raise ValidationError({"file": "El sticker supera el límite de 512 KB de Telegram."})
            if self.parse_mode:
                self.parse_mode = self.ParseMode.NONE


class ScheduleRule(models.Model):
    name = models.CharField("nombre", max_length=120, default="Programación semanal")
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="rules",
        verbose_name="canal",
    )
    kind = models.CharField("tipo", max_length=10, choices=Post.Kind.choices, default=Post.Kind.TEXT)
    text = models.TextField("texto", blank=True)
    file = models.FileField("archivo", upload_to=post_file_path, blank=True)
    parse_mode = models.CharField(
        "formato",
        max_length=12,
        choices=Post.ParseMode.choices,
        default=Post.ParseMode.HTML,
        blank=True,
    )
    disable_preview = models.BooleanField("sin vista previa de enlaces", default=False)
    weekdays = models.CharField("días", max_length=20)
    times = models.CharField("horas", max_length=500)
    repeat_weekly = models.BooleanField("publicar todas las semanas", default=True)
    is_active = models.BooleanField("activa", default=True)
    last_generated_week = models.DateField("última semana generada", null=True, blank=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "programación semanal"
        verbose_name_plural = "programaciones semanales"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def weekday_list(self):
        values = []
        for item in (self.weekdays or "").split(","):
            value = item.strip()
            if value.isdigit() and int(value) in dict(WEEKDAY_CHOICES):
                if int(value) not in values:
                    values.append(int(value))
        return sorted(values)

    def time_list(self):
        result = []
        for raw in (self.times or "").split(","):
            value = raw.strip()
            if TIME_PATTERN.fullmatch(value):
                parts = [int(part) for part in value.split(":")]
                while len(parts) < 3:
                    parts.append(0)
                result.append(tuple(parts))
        return result

    @property
    def content_preview(self):
        if self.text:
            return " ".join(self.text.split())
        if self.file:
            return Path(self.file.name).name
        return "(sin contenido)"

    def schedule_summary(self):
        days = ", ".join(dict(WEEKDAY_CHOICES)[day] for day in self.weekday_list())
        hours = ", ".join(
            f"{hour:02d}:{minute:02d}" + (f":{second:02d}" if second else "")
            for hour, minute, second in self.time_list()
        )
        return f"{days} · {hours}"

    def clean(self):
        super().clean()
        self.name = (self.name or "").strip() or "Programación semanal"
        self.weekdays = ",".join(str(day) for day in self.weekday_list())
        if not self.weekday_list():
            raise ValidationError({"weekdays": "Elige al menos un día de la semana."})

        parsed = []
        for raw in (self.times or "").split(","):
            value = raw.strip()
            if not value:
                continue
            if not TIME_PATTERN.fullmatch(value):
                raise ValidationError(
                    {"times": f"Hora no válida: «{value}». Usa HH:MM o HH:MM:SS, por ejemplo 09:30:15."}
                )
            parts = [int(part) for part in value.split(":")]
            while len(parts) < 3:
                parts.append(0)
            parsed.append(parts)
        if not parsed:
            raise ValidationError({"times": "Agrega al menos una hora."})
        self.times = ",".join(f"{hour:02d}:{minute:02d}:{second:02d}" for hour, minute, second in parsed)

        self.text = (self.text or "").strip()
        if self.kind == Post.Kind.STICKER:
            self.text = ""
            self.parse_mode = Post.ParseMode.NONE
            self.disable_preview = False
        elif self.kind == Post.Kind.PHOTO:
            self.disable_preview = False

        probe = Post(
            channel=self.channel,
            kind=self.kind,
            text=self.text,
            file=self.file,
            parse_mode=self.parse_mode,
            disable_preview=self.disable_preview,
            scheduled_at=timezone.now(),
        )
        try:
            probe.clean()
        except ValidationError as exc:
            raise ValidationError(exc.message_dict) from exc

    @classmethod
    def current_week(cls, moment=None):
        local_date = timezone.localtime(moment or timezone.now()).date()
        return local_date - timedelta(days=local_date.weekday())

    def generate_for_week(self, week_start, skip_past=False):
        now = timezone.now()
        created = []
        for weekday in self.weekday_list():
            day = week_start + timedelta(days=weekday)
            for hour, minute, second in self.time_list():
                naive = datetime.combine(day, time(hour, minute, second))
                when = timezone.make_aware(naive)
                if skip_past and when <= now:
                    continue
                existing = Post.objects.filter(
                    rule=self,
                    scheduled_at=when,
                    status__in=[Post.Status.SCHEDULED, Post.Status.SENDING],
                )
                if existing.exists():
                    continue
                post = Post(
                    rule=self,
                    channel=self.channel,
                    kind=self.kind,
                    text=self.text,
                    parse_mode=self.parse_mode,
                    disable_preview=self.disable_preview,
                    scheduled_at=when,
                )
                if self.file:
                    self.file.open("rb")
                    try:
                        post.file.save(Path(self.file.name).name, File(self.file), save=False)
                    finally:
                        self.file.close()
                post.save()
                created.append(post)
        self.last_generated_week = week_start
        self.save(update_fields=["last_generated_week", "updated_at"])
        return created

    def generate_initial(self):
        week = self.current_week()
        created = self.generate_for_week(week, skip_past=True)
        if not created:
            created = self.generate_for_week(week + timedelta(days=7))
        return created

    def regenerate(self):
        Post.objects.filter(
            rule=self,
            status=Post.Status.SCHEDULED,
            scheduled_at__gte=timezone.now(),
        ).delete()
        self.last_generated_week = None
        self.save(update_fields=["last_generated_week", "updated_at"])
        return self.generate_initial()


def expand_schedule_rules(now=None):
    current_week = ScheduleRule.current_week(now)
    rules = ScheduleRule.objects.filter(is_active=True, repeat_weekly=True)
    for rule in rules:
        if not rule.last_generated_week:
            rule.generate_for_week(current_week, skip_past=True)
            continue
        cursor = rule.last_generated_week + timedelta(days=7)
        for _ in range(8):
            if cursor > current_week:
                break
            rule.generate_for_week(cursor, skip_past=True)
            cursor += timedelta(days=7)


class BotConfig(models.Model):
    bot_token = models.CharField("token del bot", max_length=200, blank=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "configuración del bot"
        verbose_name_plural = "configuración del bot"

    def __str__(self):
        return "Configuración del bot"

    @classmethod
    def get_solo(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class WorkerState(models.Model):
    running = models.BooleanField("en ejecución", default=False)
    started_at = models.DateTimeField("iniciado", null=True, blank=True)
    last_seen = models.DateTimeField("última señal", null=True, blank=True)
    last_error = models.CharField("último error", max_length=500, blank=True)

    class Meta:
        verbose_name = "estado del programador"
        verbose_name_plural = "estado del programador"

    def __str__(self):
        return "Programador en línea" if self.is_fresh else "Programador detenido"

    @property
    def is_fresh(self):
        if not self.running or not self.last_seen:
            return False
        age = (timezone.now() - self.last_seen).total_seconds()
        return age <= settings.WORKER_STALE_SECONDS

    @classmethod
    def get_solo(cls):
        state, _ = cls.objects.get_or_create(pk=1)
        return state


@receiver(post_delete, sender=Post)
def delete_post_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=ScheduleRule)
def delete_rule_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
