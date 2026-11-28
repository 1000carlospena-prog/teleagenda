import shutil
import tempfile
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from posts.forms import ChannelForm, PostForm
from posts.management.commands.scheduler import Command
from posts.models import BotConfig, Channel, Post, ScheduleRule, expand_schedule_rules
from posts.services.telegram import TelegramError, get_bot_token


class BaseDataMixin:
    def setUp(self):
        self.channel = Channel.objects.create(name="Canal de prueba", chat_id="@canal_prueba")
        self.future = timezone.localtime(timezone.now() + timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M"
        )


class PostFormTests(BaseDataMixin, TestCase):
    def test_text_post_valid(self):
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "Hola mundo",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_text_post_requires_text(self):
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "   ",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("text", form.errors)

    def test_text_post_rejects_more_than_4096_chars(self):
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "a" * 4097,
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("text", form.errors)

    def test_photo_requires_file(self):
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.PHOTO,
                "text": "Un pie de foto",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_sticker_rejects_invalid_extension(self):
        upload = SimpleUploadedFile("sticker.png", b"fake-image", content_type="image/png")
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.STICKER,
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            },
            files={"file": upload},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_sticker_discards_text(self):
        upload = SimpleUploadedFile("sticker.webp", b"fake-webp", content_type="image/webp")
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.STICKER,
                "text": "esto debe ignorarse",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            },
            files={"file": upload},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["text"], "")
        self.assertEqual(form.cleaned_data["parse_mode"], "")

    def test_past_schedule_rejected(self):
        past = timezone.localtime(timezone.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "Hola",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": past,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("scheduled_at", form.errors)

    def test_inactive_channel_rejected(self):
        self.channel.is_active = False
        self.channel.save(update_fields=["is_active"])
        form = PostForm(
            data={
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "Hola",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("channel", form.errors)


class ChannelFormTests(TestCase):
    def test_normalizes_public_link(self):
        form = ChannelForm(
            data={"name": "Mi canal", "chat_id": "https://t.me/mi_canal/", "is_active": "on"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["chat_id"], "@mi_canal")

    def test_rejects_invite_link(self):
        form = ChannelForm(
            data={"name": "Mi canal", "chat_id": "https://t.me/+AbCdEf123", "is_active": "on"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("chat_id", form.errors)

    def test_rejects_positive_numeric_id(self):
        form = ChannelForm(
            data={"name": "Mi canal", "chat_id": "123456789", "is_active": "on"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("chat_id", form.errors)


@override_settings(TELEGRAM_BOT_TOKEN="123456:TEST-TOKEN")
class SchedulerTests(BaseDataMixin, TestCase):
    def _due_post(self, **kwargs):
        defaults = {
            "channel": self.channel,
            "kind": Post.Kind.TEXT,
            "text": "Mensaje de prueba",
            "scheduled_at": timezone.now() - timedelta(minutes=1),
        }
        defaults.update(kwargs)
        return Post.objects.create(**defaults)

    @patch("posts.management.commands.scheduler.send_post", return_value=987)
    def test_process_due_marks_post_as_sent(self, send_mock):
        post = self._due_post()
        Command(stdout=StringIO()).process_due()
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.SENT)
        self.assertEqual(post.telegram_message_id, 987)
        self.assertIsNotNone(post.sent_at)
        send_mock.assert_called_once()

    @patch(
        "posts.management.commands.scheduler.send_post",
        side_effect=TelegramError("chat not found"),
    )
    def test_process_due_marks_post_as_failed(self, send_mock):
        post = self._due_post()
        Command(stdout=StringIO()).process_due()
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.FAILED)
        self.assertIn("chat not found", post.error_text)
        send_mock.assert_called_once()

    @patch("posts.management.commands.scheduler.send_post", return_value=1)
    def test_inactive_channel_is_ignored(self, send_mock):
        self.channel.is_active = False
        self.channel.save(update_fields=["is_active"])
        post = self._due_post()
        Command(stdout=StringIO()).process_due()
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.SCHEDULED)
        send_mock.assert_not_called()

    @patch("posts.management.commands.scheduler.send_post", return_value=1)
    def test_future_post_is_not_sent(self, send_mock):
        post = self._due_post(scheduled_at=timezone.now() + timedelta(hours=1))
        Command(stdout=StringIO()).process_due()
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.SCHEDULED)
        send_mock.assert_not_called()


@override_settings(TELEGRAM_BOT_TOKEN="")
class SchedulerTokenTests(BaseDataMixin, TestCase):
    def _due_post(self):
        return Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Esperando token",
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )

    @patch("posts.management.commands.scheduler.send_post")
    def test_due_post_waits_without_token(self, send_mock):
        post = self._due_post()
        Command(stdout=StringIO()).process_due()
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.SCHEDULED)
        send_mock.assert_not_called()

    @patch("posts.management.commands.scheduler.send_post", return_value=55)
    def test_db_token_enables_sending(self, send_mock):
        token = "123456789:" + "A" * 35
        BotConfig.objects.create(pk=1, bot_token=token)
        post = self._due_post()
        Command(stdout=StringIO()).process_due()
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.SENT)
        self.assertEqual(post.telegram_message_id, 55)
        send_mock.assert_called_once()


@override_settings(TELEGRAM_BOT_TOKEN="")
class BotSettingsTests(TestCase):
    token = "123456789:" + "A" * 35

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user("admin", password="clave-segura-123")
        self.client.force_login(self.user)

    def test_page_loads(self):
        response = self.client.get(reverse("bot_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Token del bot")

    def test_save_token(self):
        response = self.client.post(reverse("bot_settings"), {"bot_token": self.token})
        self.assertRedirects(response, reverse("bot_settings"))
        self.assertEqual(BotConfig.objects.get(pk=1).bot_token, self.token)
        self.assertEqual(get_bot_token(), self.token)

    def test_token_is_not_rendered(self):
        BotConfig.objects.create(pk=1, bot_token=self.token)
        response = self.client.get(reverse("bot_settings"))
        self.assertNotContains(response, self.token)
        self.assertContains(response, "Token configurado")

    def test_blank_keeps_current_token(self):
        config = BotConfig.objects.create(pk=1, bot_token=self.token)
        response = self.client.post(reverse("bot_settings"), {"bot_token": ""})
        self.assertRedirects(response, reverse("bot_settings"))
        config.refresh_from_db()
        self.assertEqual(config.bot_token, self.token)

    def test_invalid_token_is_rejected(self):
        response = self.client.post(reverse("bot_settings"), {"bot_token": "no-es-un-token"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Token no válido")
        self.assertFalse(BotConfig.objects.exists())

    def test_status_reports_configured_after_save(self):
        self.client.post(reverse("bot_settings"), {"bot_token": self.token})
        response = self.client.get(reverse("status"))
        self.assertTrue(response.json()["bot_configured"])

    def test_remove_token(self):
        BotConfig.objects.create(pk=1, bot_token=self.token)
        response = self.client.post(reverse("bot_token_remove"))
        self.assertRedirects(response, reverse("bot_settings"))
        self.assertFalse(BotConfig.objects.exists())


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix="teleagenda-test-"),
    TELEGRAM_BOT_TOKEN="123456:TEST-TOKEN",
)
class ViewTests(BaseDataMixin, TestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings

        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user("admin", password="clave-segura-123")
        self.client.force_login(self.user)

    def test_dashboard_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_dashboard_loads(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Publicaciones")

    def test_create_post(self):
        response = self.client.post(
            reverse("post_create"),
            {
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "Primera publicación",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(Post.objects.count(), 1)

    def test_create_post_send_now(self):
        response = self.client.post(
            reverse("post_create"),
            {
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "Mensaje inmediato",
                "parse_mode": Post.ParseMode.HTML,
                "scheduled_at": self.future,
                "send_now": "1",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        post = Post.objects.get()
        self.assertLessEqual(post.scheduled_at, timezone.now())

    def test_send_now_sets_post_due(self):
        post = Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Ahora",
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        response = self.client.post(reverse("post_action", args=[post.pk, "send_now"]))
        self.assertEqual(response.status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.SCHEDULED)
        self.assertLessEqual(post.scheduled_at, timezone.now())

    def test_cancel_post(self):
        post = Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Cancelar",
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        self.client.post(reverse("post_action", args=[post.pk, "cancel"]))
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.CANCELLED)

    def test_delete_channel_with_posts_is_blocked(self):
        Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Bloquea borrado",
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        self.client.post(reverse("channel_delete", args=[self.channel.pk]))
        self.assertTrue(Channel.objects.filter(pk=self.channel.pk).exists())

    def test_status_endpoint(self):
        response = self.client.get(reverse("status"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("worker", payload)
        self.assertIn("pending", payload)
        self.assertTrue(payload["bot_configured"])

    def test_post_form_page_loads(self):
        response = self.client.get(reverse("post_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nueva publicación")

    def test_post_edit_page_loads(self):
        post = Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Editable",
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        response = self.client.get(reverse("post_edit", args=[post.pk]))
        self.assertEqual(response.status_code, 200)

    def test_channels_page_loads(self):
        response = self.client.get(reverse("channels"))
        self.assertEqual(response.status_code, 200)

    def test_channel_discover_page_loads(self):
        response = self.client.get(reverse("channel_discover"))
        self.assertEqual(response.status_code, 200)

    @patch("posts.views.get_recent_chats")
    def test_channel_discover_lists_private_channel(self, chats_mock):
        chats_mock.return_value = [
            {"id": -1001234567890, "type": "channel", "title": "Canal privado"}
        ]
        response = self.client.post(reverse("channel_discover"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Canal privado")
        self.assertContains(response, "-1001234567890")

    def test_channel_add_detected(self):
        response = self.client.post(
            reverse("channel_add_detected"),
            {"name": "Canal detectado", "chat_id": "-1001234567890"},
        )
        self.assertRedirects(response, reverse("channels"))
        self.assertTrue(Channel.objects.filter(chat_id="-1001234567890").exists())

    def test_channel_edit_page_loads(self):
        response = self.client.get(reverse("channel_edit", args=[self.channel.pk]))
        self.assertEqual(response.status_code, 200)

    def test_help_page_loads(self):
        response = self.client.get(reverse("help"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_renders_posts(self):
        Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Visible en la tabla",
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Fallida visible",
            status=Post.Status.FAILED,
            error_text="Error de prueba",
            scheduled_at=timezone.now() - timedelta(hours=1),
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible en la tabla")
        self.assertContains(response, "Error de prueba")

    def test_photo_edit_page_loads(self):
        upload = SimpleUploadedFile("foto.jpg", b"fake-jpeg", content_type="image/jpeg")
        post = Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.PHOTO,
            text="Foto de prueba",
            file=upload,
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        response = self.client.get(reverse("post_edit", args=[post.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Foto de prueba")


class ScheduleRuleTests(BaseDataMixin, TestCase):
    def _rule(self, **kwargs):
        defaults = {
            "name": "Noticias",
            "channel": self.channel,
            "kind": Post.Kind.TEXT,
            "text": "Hola semanal",
            "weekdays": "0,3",
            "times": "09:00:00,13:30:15",
            "repeat_weekly": True,
        }
        defaults.update(kwargs)
        rule = ScheduleRule(**defaults)
        rule.full_clean()
        rule.save()
        return rule

    def _now(self, day, hour=7, minute=0, second=0):
        return timezone.make_aware(datetime(2026, 11, day, hour, minute, second))

    def test_form_parses_days_and_optional_seconds(self):
        from posts.forms import ScheduleRuleForm

        form = ScheduleRuleForm(
            data={
                "name": "Noticias",
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "Hola",
                "parse_mode": Post.ParseMode.HTML,
                "weekdays": ["0", "3"],
                "times": "09:00, 13:30:15",
                "repeat_weekly": "on",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["weekdays"], "0,3")
        self.assertEqual(form.cleaned_data["times"], "09:00:00,13:30:15")

    def test_form_rejects_invalid_time(self):
        from posts.forms import ScheduleRuleForm

        form = ScheduleRuleForm(
            data={
                "name": "Noticias",
                "channel": self.channel.pk,
                "kind": Post.Kind.TEXT,
                "text": "Hola",
                "parse_mode": Post.ParseMode.HTML,
                "weekdays": ["0"],
                "times": "25:00",
                "repeat_weekly": "on",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("times", form.errors)

    def test_initial_generation_keeps_panel_wall_clock_and_seconds(self):
        rule = self._rule()
        with patch("posts.models.timezone.now", return_value=self._now(25)):
            created = rule.generate_initial()
        self.assertEqual(len(created), 2)
        posts = list(Post.objects.filter(rule=rule).order_by("scheduled_at"))
        self.assertEqual(
            [post.scheduled_time_label for post in posts], ["09:00", "13:30:15"]
        )
        self.assertTrue(
            all(timezone.localtime(post.scheduled_at).date().day == 26 for post in posts)
        )

    def test_weekly_expansion_creates_next_week_only_once(self):
        rule = self._rule()
        with patch("posts.models.timezone.now", return_value=self._now(25)):
            rule.generate_initial()
        with patch("posts.models.timezone.now", return_value=self._now(30, 7)):
            expand_schedule_rules()
            expand_schedule_rules()
        self.assertEqual(Post.objects.filter(rule=rule).count(), 6)
        rule.refresh_from_db()
        self.assertEqual(rule.last_generated_week.day, 30)

    def test_stopped_rule_is_not_expanded(self):
        rule = self._rule(is_active=False)
        with patch("posts.models.timezone.now", return_value=self._now(26, 20)):
            expand_schedule_rules()
        self.assertEqual(Post.objects.filter(rule=rule).count(), 0)



@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix="teleagenda-schedule-"),
    TELEGRAM_BOT_TOKEN="123456:TEST-TOKEN",
)
class ScheduleViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.channel = Channel.objects.create(name="Canal", chat_id="@canal_prueba")
        self.user = get_user_model().objects.create_user(
            "admin", password="clave-segura-123"
        )
        self.client.force_login(self.user)

    def test_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("schedule_list"))
        self.assertEqual(response.status_code, 302)

    def test_create_generates_posts(self):
        moment = timezone.make_aware(datetime(2026, 11, 25, 7, 0, 0))
        with patch("posts.models.timezone.now", return_value=moment):
            response = self.client.post(
                reverse("schedule_create"),
                {
                    "name": "Noticias",
                    "channel": self.channel.pk,
                    "kind": Post.Kind.TEXT,
                    "text": "Hola",
                    "parse_mode": Post.ParseMode.HTML,
                    "weekdays": ["0", "3"],
                    "times": "09:00, 13:30:15",
                    "repeat_weekly": "on",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ScheduleRule.objects.count(), 1)
        self.assertEqual(Post.objects.filter(rule__isnull=False).count(), 2)

    def test_toggle_stops_and_cancels_pending(self):
        rule = ScheduleRule.objects.create(
            name="Noticias",
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Hola",
            weekdays="0,3",
            times="09:00:00,13:30:15",
        )
        post = Post.objects.create(
            rule=rule,
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Hola",
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        self.client.post(reverse("schedule_toggle", args=[rule.pk]))
        rule.refresh_from_db()
        post.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertEqual(post.status, Post.Status.CANCELLED)

    def test_dashboard_shows_seconds(self):
        Post.objects.create(
            channel=self.channel,
            kind=Post.Kind.TEXT,
            text="Con segundos",
            scheduled_at=timezone.make_aware(datetime(2030, 1, 1, 9, 0, 15)),
        )
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "09:00:15")
