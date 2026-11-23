from django.contrib import admin

from .models import Channel, Post, WorkerState


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ["name", "chat_id", "is_active", "last_check_ok", "last_check_at"]
    list_filter = ["is_active", "last_check_ok"]
    search_fields = ["name", "chat_id"]
    readonly_fields = ["last_check_at", "last_check_ok", "last_check_error", "created_at"]


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ["__str__", "status", "kind", "channel", "scheduled_at", "sent_at"]
    list_filter = ["status", "kind", "channel"]
    search_fields = ["text", "channel__name"]
    date_hierarchy = "scheduled_at"
    readonly_fields = [
        "status",
        "started_at",
        "sent_at",
        "telegram_message_id",
        "error_text",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["channel"]


@admin.register(WorkerState)
class WorkerStateAdmin(admin.ModelAdmin):
    list_display = ["__str__", "running", "started_at", "last_seen"]
    readonly_fields = ["running", "started_at", "last_seen", "last_error"]
