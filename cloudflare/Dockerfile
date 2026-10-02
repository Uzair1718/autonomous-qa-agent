FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm && rm -rf /var/lib/apt/lists/*
RUN npm install -g @open-pencil/cli

RUN git clone --depth 1 https://github.com/Uzair1718/autonomous-qa-agent.git /app
WORKDIR /app

RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium

EXPOSE 8000

CMD ["uvicorn", "src.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
