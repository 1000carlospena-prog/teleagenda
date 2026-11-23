from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import BotTokenForm, ChannelForm, PostForm
from .models import BotConfig, Channel, Post, WorkerState
from .services.telegram import (
    TelegramError,
    bot_token_configured,
    get_chat,
    get_me,
    get_recent_chats,
)
from .status import worker_status


def _safe_next(request):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("dashboard")


def _format_local(moment):
    return timezone.localtime(moment).strftime("%d/%m/%Y %H:%M")


def _queue_notice(request):
    if worker_status()["running"]:
        messages.success(request, "Publicación en cola. Se enviará en los próximos segundos.")
    else:
        messages.warning(
            request,
            "Publicación en cola, pero el programador está detenido. Inicia el bot para que se envíe.",
        )


@login_required
def dashboard(request):
    status_filter = (request.GET.get("status") or "").strip()
    kind_filter = (request.GET.get("kind") or "").strip()
    channel_filter = (request.GET.get("channel") or "").strip()
    query = (request.GET.get("q") or "").strip()

    if status_filter not in Post.Status.values:
        status_filter = ""
    if kind_filter not in Post.Kind.values:
        kind_filter = ""

    posts = Post.objects.select_related("channel")
    if status_filter:
        posts = posts.filter(status=status_filter)
    if kind_filter:
        posts = posts.filter(kind=kind_filter)
    if channel_filter.isdigit():
        posts = posts.filter(channel_id=int(channel_filter))
    if query:
        posts = posts.filter(Q(text__icontains=query) | Q(channel__name__icontains=query))

    counts = Post.objects.aggregate(
        scheduled=Count("pk", filter=Q(status=Post.Status.SCHEDULED)),
        sent=Count("pk", filter=Q(status=Post.Status.SENT)),
        failed=Count("pk", filter=Q(status=Post.Status.FAILED)),
        total=Count("pk"),
    )

    next_post = (
        Post.objects.select_related("channel")
        .filter(status=Post.Status.SCHEDULED, channel__is_active=True)
        .order_by("scheduled_at")
        .first()
    )

    paginator = Paginator(posts, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)

    context = {
        "page_obj": page_obj,
        "posts": page_obj.object_list,
        "counts": counts,
        "active_channels": Channel.objects.filter(is_active=True).count(),
        "total_channels": Channel.objects.count(),
        "next_post": next_post,
        "status_choices": Post.Status.choices,
        "kind_choices": Post.Kind.choices,
        "channels": Channel.objects.all(),
        "filters": {
            "status": status_filter,
            "kind": kind_filter,
            "channel": channel_filter,
            "q": query,
        },
        "filters_active": bool(status_filter or kind_filter or channel_filter or query),
        "querystring": params.urlencode(),
        "total_results": paginator.count,
    }
    return render(request, "posts/dashboard.html", context)


@login_required
def post_create(request):
    if not Channel.objects.filter(is_active=True).exists():
        messages.warning(request, "Primero agrega y activa un canal de Telegram.")
        return redirect("channel_create")

    send_now = request.POST.get("send_now") == "1"
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES, send_now=send_now)
        if form.is_valid():
            post = form.save()
            if send_now:
                _queue_notice(request)
            else:
                messages.success(
                    request,
                    f"Publicación programada para el {_format_local(post.scheduled_at)}.",
                )
            return redirect("dashboard")
        messages.error(request, "Revisa los campos marcados en rojo.")
    else:
        form = PostForm()

    return render(
        request,
        "posts/post_form.html",
        {"form": form, "is_edit": False, "channels_count": Channel.objects.filter(is_active=True).count()},
    )


@login_required
def post_edit(request, pk):
    post = get_object_or_404(Post.objects.select_related("channel"), pk=pk)
    if not post.can_edit:
        messages.error(
            request,
            "Esta publicación ya se envió o se está enviando; no se puede editar. "
            "Puedes duplicarla para crear una nueva.",
        )
        return redirect("dashboard")

    send_now = request.POST.get("send_now") == "1"
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES, instance=post, send_now=send_now)
        if form.is_valid():
            post = form.save()
            if send_now:
                _queue_notice(request)
            else:
                messages.success(
                    request,
                    f"Cambios guardados. Se enviará el {_format_local(post.scheduled_at)}.",
                )
            return redirect("dashboard")
        messages.error(request, "Revisa los campos marcados en rojo.")
    else:
        form = PostForm(instance=post)

    return render(
        request,
        "posts/post_form.html",
        {
            "form": form,
            "post": post,
            "is_edit": True,
            "channels_count": Channel.objects.filter(is_active=True).count(),
        },
    )


@login_required
@require_POST
def post_delete(request, pk):
    post = get_object_or_404(Post.objects.select_related("channel"), pk=pk)
    was_sent = post.status == Post.Status.SENT
    post.delete()
    if was_sent:
        messages.success(
            request,
            "Registro eliminado. El mensaje original sigue publicado en Telegram.",
        )
    else:
        messages.success(request, "Publicación eliminada.")
    return redirect(_safe_next(request))


@login_required
@require_POST
def post_action(request, pk, action):
    post = get_object_or_404(Post.objects.select_related("channel"), pk=pk)
    next_url = _safe_next(request)

    if action in {"send_now", "retry"}:
        if not post.can_send_now:
            messages.error(request, "Esta publicación no se puede enviar en este momento.")
            return redirect(next_url)
        post.status = Post.Status.SCHEDULED
        post.scheduled_at = timezone.now()
        post.started_at = None
        post.error_text = ""
        post.telegram_message_id = None
        post.save()
        if worker_status()["running"]:
            messages.success(request, "Publicación en cola. Se enviará en los próximos segundos.")
        else:
            messages.warning(
                request,
                "Publicación en cola, pero el programador está detenido. "
                "Inicia el bot para que se envíe.",
            )

    elif action == "cancel":
        if not post.can_cancel:
            messages.error(request, "Esta publicación ya no se puede cancelar.")
            return redirect(next_url)
        post.status = Post.Status.CANCELLED
        post.save()
        messages.success(request, "Publicación cancelada. No se enviará a Telegram.")

    elif action == "duplicate":
        new_post = Post(
            channel=post.channel,
            kind=post.kind,
            text=post.text,
            parse_mode=post.parse_mode,
            disable_preview=post.disable_preview,
            scheduled_at=timezone.now() + timedelta(hours=1),
            status=Post.Status.SCHEDULED,
        )
        if post.file:
            try:
                post.file.open("rb")
                try:
                    new_post.file.save(Path(post.file.name).name, File(post.file), save=False)
                finally:
                    post.file.close()
            except OSError:
                messages.error(request, "No se pudo copiar el archivo de la publicación.")
                return redirect(next_url)
        new_post.save()
        messages.success(request, "Publicación duplicada. Ajusta la fecha y el contenido.")
        return redirect("post_edit", pk=new_post.pk)

    else:
        messages.error(request, "Acción no válida.")
        return redirect(next_url)

    return redirect(next_url)


@login_required
def channels(request):
    channel_list = Channel.objects.annotate(post_count=Count("posts")).order_by("name")
    return render(request, "posts/channels.html", {"channels": channel_list})


def _detected_channels():
    existing = set(Channel.objects.values_list("chat_id", flat=True))
    labels = {"channel": "Canal", "supergroup": "Supergrupo", "group": "Grupo"}
    detected = []
    for chat in get_recent_chats():
        chat_type = chat.get("type") or ""
        if chat_type == "private":
            continue
        username = (chat.get("username") or "").strip()
        numeric_id = str(chat.get("id"))
        suggested_id = f"@{username}" if username else numeric_id
        title = (
            chat.get("title")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or "Canal de Telegram"
        ).strip()
        alternatives = {numeric_id, f"@{username}" if username else ""}
        detected.append(
            {
                "title": title,
                "type": labels.get(chat_type, "Chat"),
                "username": f"@{username}" if username else "",
                "numeric_id": numeric_id,
                "suggested_id": suggested_id,
                "already_added": bool((alternatives - {""}) & existing),
            }
        )
    detected.sort(key=lambda item: item["title"].lower())
    return detected


@login_required
def channel_discover(request):
    chats = None
    if request.method == "POST":
        try:
            chats = _detected_channels()
        except TelegramError as exc:
            messages.error(request, f"No se pudieron detectar canales: {exc}")
    return render(
        request,
        "posts/channel_discover.html",
        {"chats": chats, "searched": request.method == "POST"},
    )


@login_required
@require_POST
def channel_add_detected(request):
    data = request.POST.copy()
    data["is_active"] = "on"
    form = ChannelForm(data)
    if form.is_valid():
        channel = form.save()
        messages.success(request, f"Canal «{channel.name}» agregado.")
        return redirect("channels")
    errors = " ".join(
        str(error) for error_list in form.errors.values() for error in error_list
    )
    messages.error(request, f"No se pudo agregar el canal: {errors}")
    return redirect("channel_discover")


@login_required
def channel_create(request):
    if request.method == "POST":
        form = ChannelForm(request.POST)
        if form.is_valid():
            channel = form.save()
            messages.success(request, f"Canal «{channel.name}» agregado.")
            return redirect("channels")
    else:
        form = ChannelForm()
    return render(
        request,
        "posts/channel_form.html",
        {"form": form, "is_edit": False},
    )


@login_required
def channel_edit(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    if request.method == "POST":
        form = ChannelForm(request.POST, instance=channel)
        if form.is_valid():
            form.save()
            messages.success(request, "Canal actualizado.")
            return redirect("channels")
    else:
        form = ChannelForm(instance=channel)
    return render(
        request,
        "posts/channel_form.html",
        {"form": form, "channel": channel, "is_edit": True},
    )


@login_required
@require_POST
def channel_delete(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    post_count = channel.posts.count()
    if post_count:
        messages.error(
            request,
            f"No se puede eliminar «{channel.name}»: tiene {post_count} publicación(es). "
            "Desactívalo o elimina sus publicaciones primero.",
        )
    else:
        name = channel.name
        channel.delete()
        messages.success(request, f"Canal «{name}» eliminado.")
    return redirect("channels")


@login_required
@require_POST
def channel_test(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    try:
        info = get_chat(channel.chat_id)
    except TelegramError as exc:
        channel.mark_check(False, str(exc))
        messages.error(request, f"No se pudo verificar «{channel.name}»: {exc}")
    else:
        channel.mark_check(True)
        title = info.get("title") or info.get("username") or channel.chat_id
        messages.success(request, f"Conexión correcta con «{title}».")
    return redirect("channels")


@login_required
@require_POST
def telegram_test(request):
    try:
        me = get_me()
    except TelegramError as exc:
        messages.error(request, f"No se pudo conectar con el bot: {exc}")
    else:
        username = f"@{me['username']}" if me.get("username") else me.get("first_name", "el bot")
        messages.success(request, f"Conexión correcta. Bot: {username}.")
    if request.POST.get("next"):
        return redirect(_safe_next(request))
    return redirect("help")


@login_required
def bot_settings(request):
    config = BotConfig.objects.filter(pk=1).first()
    configured = bot_token_configured()
    form = BotTokenForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        token = form.cleaned_data["bot_token"]
        if token:
            config, _ = BotConfig.objects.get_or_create(pk=1)
            config.bot_token = token
            config.save(update_fields=["bot_token", "updated_at"])
            messages.success(
                request,
                "Token guardado. El panel y el programador lo usarán automáticamente.",
            )
            return redirect("bot_settings")
        if configured:
            messages.info(request, "No se cambió el token guardado.")
            return redirect("bot_settings")
        form.add_error("bot_token", "Escribe el token que te entregó @BotFather.")

    return render(
        request,
        "posts/bot_settings.html",
        {
            "form": form,
            "configured": configured,
            "config": config,
            "db_configured": bool(config and config.bot_token),
        },
    )


@login_required
@require_POST
def bot_token_remove(request):
    removed = BotConfig.objects.filter(pk=1).delete()[0]
    if removed:
        messages.success(request, "Token guardado eliminado del panel.")
    else:
        messages.info(request, "No había token guardado en el panel.")
    if settings.TELEGRAM_BOT_TOKEN:
        messages.warning(
            request,
            "Queda un token de respaldo en .env: reinicia el panel y el programador para dejar de usarlo.",
        )
    return redirect("bot_settings")


@login_required
def help_page(request):
    return render(
        request,
        "posts/help.html",
        {
            "scheduler_command": "python manage.py scheduler",
            "chat_ids_command": "python manage.py get_chat_ids",
            "channel_count": Channel.objects.count(),
            "state": WorkerState.objects.filter(pk=1).first(),
        },
    )


@login_required
def status_json(request):
    counts = Post.objects.aggregate(
        scheduled=Count("pk", filter=Q(status=Post.Status.SCHEDULED)),
        failed=Count("pk", filter=Q(status=Post.Status.FAILED)),
    )
    return JsonResponse(
        {
            "worker": worker_status(),
            "bot_configured": bot_token_configured(),
            "pending": counts["scheduled"],
            "failed": counts["failed"],
            "server_time": timezone.localtime().isoformat(),
            "timezone": settings.TIME_ZONE,
        }
    )
