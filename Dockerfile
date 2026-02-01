FROM python:3.11-slim

# Add OCI labels to prevent Unraid from auto-detecting wrong config
LABEL org.opencontainers.image.title="TikTok Collections Downloader"
LABEL org.opencontainers.image.description="Automatically monitor and download TikTok collections with organized folder structure"
LABEL org.opencontainers.image.url="https://github.com/trevren11/tik-tok-collections-downloader"
LABEL org.opencontainers.image.source="https://github.com/trevren11/tik-tok-collections-downloader"
LABEL org.opencontainers.image.documentation="https://github.com/trevren11/tik-tok-collections-downloader/blob/main/README.md"
LABEL org.opencontainers.image.vendor="trevren11"
LABEL org.opencontainers.image.authors="trevren11"
LABEL org.opencontainers.image.licenses="MIT"

# Unraid-specific labels
LABEL net.unraid.docker.icon="https://raw.githubusercontent.com/trevren11/tik-tok-collections-downloader/main/icon.png"
LABEL net.unraid.docker.webui="http://[IP]:[PORT:2507]/json/viewer.html"
LABEL net.unraid.docker.managed="true"

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium && playwright install-deps chromium

# Copy application code
COPY tiktok_monitor.py tiktok_collections.py viewer.py viewer.html ./
COPY tests/ ./tests/

# Create volume mount points
VOLUME ["/app/config", "/app/downloads"]

# Expose viewer port (configurable via VIEWER_PORT env var, default 8425)
EXPOSE 8425

# Default command runs the entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
