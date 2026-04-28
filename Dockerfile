# ── Base image ───────────────────────────────────────────────────────────────
# Use CUDA base if GPU available; swap to python:3.10-slim for CPU-only.
FROM python:3.10-slim

# System dependencies for OpenCV, InsightFace, MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgl1 \
        libgstreamer1.0-0 \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/       ./app/
COPY migrations/ ./migrations/
COPY scripts/   ./scripts/
COPY frontend/  ./frontend/
COPY config.yaml .

# Create media directories
RUN mkdir -p media/snapshots media/clips models

EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
