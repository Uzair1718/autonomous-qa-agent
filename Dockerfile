FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

# The Playwright image already contains Chromium and its system dependencies.
# Do not install browsers during build/startup.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @open-pencil/cli \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY .claude ./.claude

RUN pip install --no-cache-dir .

EXPOSE 8000

# Override the Playwright image entrypoint so Render starts Uvicorn directly.
ENTRYPOINT []
CMD ["sh", "-c", "uvicorn src.api_server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]