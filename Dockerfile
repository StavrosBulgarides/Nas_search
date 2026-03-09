FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg unrar-free p7zip-full && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY config.example.yml config.yml

RUN mkdir -p /app/data

ENV CONFIG_PATH=/app/config.yml
ENV DB_PATH=/app/data/nas_search.db

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
