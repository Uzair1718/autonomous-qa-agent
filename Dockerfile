FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN npm install -g @open-pencil/cli

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY .claude ./.claude

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.api_server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
