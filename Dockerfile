FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN touch /app/db.sqlite3
RUN DJANGO_ENV=development DJANGO_DEBUG=False python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "django_env=\"$(printf '%s' \"${DJANGO_ENV:-development}\" | tr '[:upper:]' '[:lower:]' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')\" && if [ \"$django_env\" = \"production\" ] || [ \"$django_env\" = \"prod\" ]; then exec gunicorn smartassist.wsgi:application --bind 0.0.0.0:8000; else exec python manage.py runserver 0.0.0.0:8000; fi"]
