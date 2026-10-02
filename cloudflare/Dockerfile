FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/usr/local/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates xz-utils && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://nodejs.org/dist/v22.23.3/node-v22.23.3-linux-x64.tar.xz \
    | tar -xJ -C /usr/local --strip-components=1

RUN npm install -g @open-pencil/cli

RUN mkdir -p /app \
    && curl -fsSL https://codeload.github.com/Uzair1718/autonomous-qa-agent/tar.gz/refs/heads/main \
    | tar -xz --strip-components=1 -C /app

WORKDIR /app

RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium

EXPOSE 8000

CMD ["uvicorn", "src.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
