FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# UI uses Tailwind via the Play CDN (no Node build step for the prototype).
# Production hardening: add a Node build stage that compiles Tailwind to a static
# CSS and drop the CDN <script> in web/index.html.
COPY app/ app/
COPY web/ web/
COPY config.example.yaml ./config.example.yaml

# Config + SQLite state live on a mounted volume.
ENV BRIDGE_CONFIG=/data/config.yaml
ENV BRIDGE_DB=/data/state.db
VOLUME ["/data"]

EXPOSE 8099
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
