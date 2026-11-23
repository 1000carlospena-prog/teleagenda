FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN mkdir -p /app/data /app/media

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt supervisor

COPY . .

RUN python manage.py collectstatic --noinput

ENV DB_PATH=/app/data/db.sqlite3
ENV MEDIA_ROOT_PATH=/app/media

EXPOSE 8000

CMD sh -c "python manage.py migrate --noinput && supervisord -n -c /app/supervisord.conf"
