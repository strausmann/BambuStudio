FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY web/ web/
COPY config.example.yaml ./config.example.yaml

# Config + SQLite state live on a mounted volume.
ENV BRIDGE_CONFIG=/data/config.yaml
ENV BRIDGE_DB=/data/state.db
VOLUME ["/data"]

EXPOSE 8099
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
