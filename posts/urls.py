from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("publicaciones/nueva/", views.post_create, name="post_create"),
    path("publicaciones/<int:pk>/editar/", views.post_edit, name="post_edit"),
    path("publicaciones/<int:pk>/eliminar/", views.post_delete, name="post_delete"),
    path("publicaciones/<int:pk>/accion/<str:action>/", views.post_action, name="post_action"),
    path("programaciones/", views.schedule_list, name="schedule_list"),
    path("programaciones/nueva/", views.schedule_create, name="schedule_create"),
    path("programaciones/<int:pk>/editar/", views.schedule_edit, name="schedule_edit"),
    path("programaciones/<int:pk>/estado/", views.schedule_toggle, name="schedule_toggle"),
    path("programaciones/<int:pk>/eliminar/", views.schedule_delete, name="schedule_delete"),
    path("canales/", views.channels, name="channels"),
    path("canales/detectar/", views.channel_discover, name="channel_discover"),
    path("canales/detectar/agregar/", views.channel_add_detected, name="channel_add_detected"),
    path("canales/nuevo/", views.channel_create, name="channel_create"),
    path("canales/<int:pk>/editar/", views.channel_edit, name="channel_edit"),
    path("canales/<int:pk>/eliminar/", views.channel_delete, name="channel_delete"),
    path("canales/<int:pk>/probar/", views.channel_test, name="channel_test"),
    path("configuracion/", views.bot_settings, name="bot_settings"),
    path("configuracion/quitar/", views.bot_token_remove, name="bot_token_remove"),
    path("ayuda/", views.help_page, name="help"),
    path("bot/probar/", views.telegram_test, name="telegram_test"),
    path("estado/", views.status_json, name="status"),
]
