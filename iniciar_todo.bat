@echo off
cd /d "%~dp0"
start "TeleAgenda - Panel" cmd /k "call .venv\Scripts\activate.bat && python manage.py runserver 127.0.0.1:8000"
start "TeleAgenda - Bot" cmd /k "call .venv\Scripts\activate.bat && python manage.py scheduler"
