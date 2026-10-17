FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for audio and network probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libportaudio2 \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure data dir exists
RUN mkdir -p /app/data

EXPOSE 8080 10023/udp

CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
