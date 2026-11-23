from django.conf import settings

from .services.telegram import bot_token_configured
from .status import worker_status


def _display_timezone():
    labels = {
        "Etc/GMT+5": "Cuba (UTC-05:00)",
        "America/Havana": "Cuba (UTC-04:00/UTC-05:00)",
    }
    return labels.get(settings.TIME_ZONE, settings.TIME_ZONE)


def global_status(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "worker_status": worker_status(),
        "bot_configured": bot_token_configured(),
        "display_timezone": _display_timezone(),
    }
