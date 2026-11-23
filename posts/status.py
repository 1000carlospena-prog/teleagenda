from django.conf import settings
from django.utils import timezone

from .models import WorkerState


def worker_status():
    state = WorkerState.objects.filter(pk=1).first()
    now = timezone.now()

    if state and state.running and state.last_seen:
        age = max(0, int((now - state.last_seen).total_seconds()))
        if age <= settings.WORKER_STALE_SECONDS:
            tone, label, detail = "ok", "Programador en línea", "Revisando publicaciones pendientes."
        else:
            tone, label, detail = (
                "warn",
                "Programador sin señal",
                f"Sin respuesta desde hace {age} segundos.",
            )
    elif state and state.running:
        tone, label, detail = "warn", "Programador sin señal", "Aún no envía su primera señal."
    else:
        tone, label, detail = (
            "off",
            "Programador detenido",
            "Inicia el bot con: python manage.py scheduler",
        )

    return {
        "running": tone == "ok",
        "tone": tone,
        "label": label,
        "detail": detail,
        "last_seen": timezone.localtime(state.last_seen).isoformat() if state and state.last_seen else None,
    }
