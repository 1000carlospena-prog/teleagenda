from django.core.management.base import BaseCommand, CommandError

from posts.services.telegram import TelegramError, get_recent_chats


class Command(BaseCommand):
    help = "Muestra los chats y canales que han interactuado con el bot (útil para obtener el chat ID)."

    def handle(self, *args, **options):
        try:
            chats = get_recent_chats()
        except TelegramError as exc:
            raise CommandError(str(exc)) from exc

        if not chats:
            self.stdout.write(
                self.style.WARNING(
                    "No hay chats todavía.\n"
                    "1. Agrega el bot como administrador del canal (con permiso para publicar).\n"
                    "2. Publica algo en el canal o envía /start al bot.\n"
                    "3. Ejecuta de nuevo: python manage.py get_chat_ids"
                )
            )
            return

        self.stdout.write(self.style.SUCCESS("Chats encontrados:"))
        for chat in chats:
            username = f"@{chat['username']}" if chat.get("username") else "sin usuario"
            title = chat.get("title") or " ".join(
                filter(None, [chat.get("first_name"), chat.get("last_name")])
            )
            self.stdout.write(
                f"- {title or '(sin título)'} | tipo: {chat.get('type')} | "
                f"usuario: {username} | chat_id: {chat.get('id')}"
            )
