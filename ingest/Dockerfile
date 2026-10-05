FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vigia_ingest/ vigia_ingest/
CMD ["python", "-m", "vigia_ingest", "loop"]
