FROM python:3.13-slim

# fontconfig + Liberation Sans en fallback ; les Arial Narrow bundlées dans
# assets/fonts/ sont indexées plus bas via fc-cache.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fontconfig \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache layer dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code + assets (templates + polices)
COPY . .

# Indexation des Arial Narrow bundlées pour que Pillow les résolve par famille
RUN fc-cache -f /app/assets/fonts || true

EXPOSE 8000
CMD ["sh", "-c", "uvicorn src.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
