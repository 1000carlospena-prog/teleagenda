@echo off
cd /d "%~dp0"
if not exist .venv py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
echo.
echo Listo. Edita .env con tu TELEGRAM_BOT_TOKEN y ejecuta iniciar_todo.bat
pause
