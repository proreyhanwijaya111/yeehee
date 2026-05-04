# yeehee FastAPI Backend — Docker image
# Untuk deploy ke Railway / Render / Fly.io

FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
COPY api/requirements-api.txt .
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt

# Copy source code
COPY . .

# Expose port
EXPOSE 8000

# Start FastAPI (Railway / Render will set PORT env var)
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
