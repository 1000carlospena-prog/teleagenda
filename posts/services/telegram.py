import mimetypes
from pathlib import Path

import requests
from django.conf import settings

from posts.models import BotConfig, Post


class TelegramError(Exception):
    """Error controlado al comunicarse con la API de Telegram."""


def get_bot_token():
    config = BotConfig.objects.filter(pk=1).only("bot_token").first()
    if config and config.bot_token.strip():
        return config.bot_token.strip()
    return (settings.TELEGRAM_BOT_TOKEN or "").strip()


def bot_token_configured():
    return bool(get_bot_token())


def _token():
    token = get_bot_token()
    if not token:
        raise TelegramError(
            "Falta configurar el token del bot. "
            "Entra a Configuración en el panel y pega el token de @BotFather."
        )
    return token


def api_call(method, data=None, files=None, timeout=None):
    url = f"{settings.TELEGRAM_API_BASE}/bot{_token()}/{method}"
    try:
        response = requests.post(
            url,
            data=data or {},
            files=files,
            timeout=timeout or settings.TELEGRAM_TIMEOUT,
        )
    except requests.RequestException:
        raise TelegramError(
            "No se pudo conectar con la API de Telegram. Revisa la conexión a internet."
        ) from None

    try:
        payload = response.json()
    except ValueError:
        raise TelegramError(
            f"Telegram devolvió una respuesta no válida (HTTP {response.status_code})."
        ) from None

    if not payload.get("ok"):
        description = payload.get("description") or f"Error HTTP {response.status_code}"
        raise TelegramError(description)

    return payload.get("result")


def get_me():
    return api_call("getMe", timeout=20)


def get_chat(chat_id):
    return api_call("getChat", data={"chat_id": chat_id}, timeout=30)


def get_updates(offset=None):
    data = {"timeout": 0, "allowed_updates": '["message","channel_post","my_chat_member"]'}
    if offset is not None:
        data["offset"] = offset
    return api_call("getUpdates", data=data, timeout=30)


def get_recent_chats():
    """Devuelve los chats/canales vistos en las últimas actualizaciones del bot."""
    chats = {}
    for update in get_updates():
        for key in (
            "message",
            "edited_message",
            "channel_post",
            "edited_channel_post",
            "my_chat_member",
        ):
            item = update.get(key) or {}
            chat = item.get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is not None:
                chats[chat_id] = chat
    return list(chats.values())


def send_post(post):
    if not post.channel.is_active:
        raise TelegramError("El canal está inactivo.")

    data = {"chat_id": post.channel.chat_id}

    if post.kind == Post.Kind.TEXT:
        data["text"] = post.text
        if post.parse_mode:
            data["parse_mode"] = post.parse_mode
        if post.disable_preview:
            data["disable_web_page_preview"] = "true"
        result = api_call("sendMessage", data=data)

    elif post.kind == Post.Kind.PHOTO:
        if not post.file:
            raise TelegramError("La publicación no tiene imagen adjunta.")
        if post.text:
            data["caption"] = post.text
            if post.parse_mode:
                data["parse_mode"] = post.parse_mode
        with post.file.open("rb") as handle:
            filename = Path(post.file.name).name
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            result = api_call(
                "sendPhoto",
                data=data,
                files={"photo": (filename, handle, content_type)},
            )

    elif post.kind == Post.Kind.STICKER:
        if not post.file:
            raise TelegramError("La publicación no tiene sticker adjunto.")
        with post.file.open("rb") as handle:
            filename = Path(post.file.name).name
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            result = api_call(
                "sendSticker",
                data=data,
                files={"sticker": (filename, handle, content_type)},
            )

    else:
        raise TelegramError("Tipo de publicación no soportado.")

    return result.get("message_id") if result else None
