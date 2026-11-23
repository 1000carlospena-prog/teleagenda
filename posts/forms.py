import re
from datetime import timedelta
from pathlib import Path

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from .models import Channel, Post


class ChannelForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = ["name", "chat_id", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Mi canal de noticias"}),
            "chat_id": forms.TextInput(attrs={"placeholder": "@mi_canal o -1001234567890"}),
        }

    def clean_chat_id(self):
        value = (self.cleaned_data.get("chat_id") or "").strip()
        if not value:
            raise forms.ValidationError("Escribe el @usuario o el ID numérico del canal.")

        if value.startswith("http://") or value.startswith("https://"):
            if "t.me/+" in value or "/joinchat/" in value:
                raise forms.ValidationError(
                    "Los enlaces de invitación no sirven. Usa @usuario o el ID numérico."
                )
            value = value.rstrip("/")
            if "t.me/" in value:
                value = "@" + value.split("t.me/")[-1].split("/")[0].split("?")[0]

        if value.startswith("@"):
            username = value[1:]
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username):
                raise forms.ValidationError(
                    "Usuario no válido. Debe empezar con letra y tener entre 5 y 32 caracteres."
                )
            return "@" + username

        if re.fullmatch(r"-?\d+", value):
            if not value.startswith("-"):
                raise forms.ValidationError(
                    "El ID de un canal es negativo (normalmente empieza con -100)."
                )
            return value

        raise forms.ValidationError("Usa un @usuario o un ID numérico que empiece con -100.")


class BotTokenForm(forms.Form):
    bot_token = forms.CharField(
        label="Token del bot",
        max_length=200,
        required=False,
        strip=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "123456789:AA...",
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
    )

    def clean_bot_token(self):
        value = self.cleaned_data.get("bot_token") or ""
        if value and not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", value):
            raise forms.ValidationError(
                "Token no válido. Debe tener el formato 123456789:AA... que entrega @BotFather."
            )
        return value


class PostForm(forms.ModelForm):
    scheduled_at = forms.DateTimeField(
        label="Fecha y hora",
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "data-schedule-input": ""},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
    )

    class Meta:
        model = Post
        fields = ["channel", "kind", "text", "file", "parse_mode", "disable_preview", "scheduled_at"]
        widgets = {
            "kind": forms.RadioSelect(attrs={"class": "kind-input"}),
            "text": forms.Textarea(
                attrs={
                    "rows": 7,
                    "placeholder": "Escribe el mensaje que verá tu audiencia…",
                    "data-text-input": "",
                }
            ),
            "file": forms.ClearableFileInput(
                attrs={
                    "accept": "image/jpeg,image/png,image/webp,.webp,.tgs,.webm",
                    "data-file-input": "",
                }
            ),
        }

    def __init__(self, *args, send_now=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.send_now = send_now
        if send_now:
            self.fields["scheduled_at"].required = False
        self.fields["channel"].queryset = Channel.objects.all()
        self.fields["channel"].empty_label = "Elige un canal…"
        self.fields["channel"].widget.attrs["data-channel-select"] = ""
        self.fields["parse_mode"].widget.attrs["data-parse-mode"] = ""
        self.fields["disable_preview"].widget.attrs["data-disable-preview"] = ""
        self.fields["file"].widget.attrs["data-existing-url"] = (
            self.instance.file.url if self.instance.pk and self.instance.file else ""
        )
        self.fields["file"].widget.attrs["data-existing-name"] = (
            Path(self.instance.file.name).name if self.instance.pk and self.instance.file else ""
        )
        self.fields["file"].widget.attrs["data-existing-image"] = (
            "1" if self.instance.pk and self.instance.file and self.instance.is_previewable_image else ""
        )

        if not self.is_bound and not self.instance.pk:
            available = list(self.fields["channel"].queryset)
            if len(available) == 1:
                self.initial["channel"] = available[0].pk

        if not self.is_bound:
            if self.instance.pk and self.instance.scheduled_at and self.instance.status == Post.Status.SCHEDULED:
                self.initial["scheduled_at"] = timezone.localtime(
                    self.instance.scheduled_at
                ).strftime("%Y-%m-%dT%H:%M")
            else:
                default = timezone.localtime(timezone.now() + timedelta(minutes=10)).replace(
                    second=0, microsecond=0
                )
                self.initial["scheduled_at"] = default.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        text = (cleaned.get("text") or "").strip()
        uploaded_file = cleaned.get("file")
        scheduled_at = cleaned.get("scheduled_at")
        channel = cleaned.get("channel")

        if channel and not channel.is_active:
            self.add_error("channel", "Este canal está inactivo. Actívalo antes de programar.")

        if kind == Post.Kind.TEXT:
            if isinstance(uploaded_file, UploadedFile):
                self.add_error("file", "El tipo Texto no admite archivo. Elige Imagen o Sticker.")
            else:
                cleaned["file"] = None
        elif kind == Post.Kind.STICKER:
            cleaned["text"] = ""
            cleaned["parse_mode"] = Post.ParseMode.NONE
            cleaned["disable_preview"] = False
        elif kind == Post.Kind.PHOTO:
            cleaned["disable_preview"] = False

        if self.send_now:
            cleaned["scheduled_at"] = timezone.now()
        elif scheduled_at:
            tolerance = timezone.now() - timedelta(minutes=2)
            if scheduled_at < tolerance:
                self.add_error("scheduled_at", "Elige una fecha y hora futura.")

        cleaned["text"] = "" if kind == Post.Kind.STICKER else text
        return cleaned

    def save(self, commit=True):
        old_file_name = None
        if self.instance.pk:
            old_file_name = (
                Post.objects.filter(pk=self.instance.pk).values_list("file", flat=True).first()
            )

        post = super().save(commit=False)

        if post.kind == Post.Kind.TEXT:
            if post.file:
                post.file.delete(save=False)
                post.file = None
        elif post.kind == Post.Kind.STICKER:
            post.text = ""
            post.parse_mode = Post.ParseMode.NONE
            post.disable_preview = False

        if post.status in {Post.Status.FAILED, Post.Status.CANCELLED}:
            post.status = Post.Status.SCHEDULED
            post.error_text = ""
            post.started_at = None

        if commit:
            post.save()
            if old_file_name and (not post.file or post.file.name != old_file_name):
                post.file.storage.delete(old_file_name)

        return post
