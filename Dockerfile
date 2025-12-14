# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

VOLUME ["/app/data"]

ENTRYPOINT ["python", "src/main.py"]
CMD ["--config", "src/config.yaml"]
