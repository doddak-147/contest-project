FROM python:3.13-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app backend ./backend
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app data ./data
COPY --chown=app:app alembic.ini index.html admin.html app.js api.js admin.js style.css ./
COPY --chown=app:app deploy/start.sh ./deploy/start.sh
RUN mkdir -p /app/runtime/catalogue /backups && chown -R app:app /app/runtime /backups \
    && sed -i 's/\r$//' /app/deploy/start.sh && chmod +x /app/deploy/start.sh
USER app
EXPOSE 8000
ENTRYPOINT ["/app/deploy/start.sh"]
