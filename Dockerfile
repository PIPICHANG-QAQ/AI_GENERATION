# syntax=docker/dockerfile:1

ARG SERVER_BASE_IMAGE=python:3.11-slim-bookworm
FROM ${SERVER_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        ffmpeg \
        fontconfig \
        fonts-noto-cjk \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libx11-6 \
        libxcb1 \
        libxext6 \
        libxrender1 \
        nginx \
        openjdk-17-jre-headless \
        poppler-utils \
        python3-venv \
        texlive-lang-chinese \
        texlive-latex-extra \
        texlive-xetex \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/python-worker ./backend/python-worker
RUN python3 -m venv /opt/question-engine/venv \
    && /opt/question-engine/venv/bin/python -m pip install --upgrade pip setuptools wheel \
    && /opt/question-engine/venv/bin/pip install -e ./backend/python-worker

COPY backend/target/ai-question-bank-*.jar /app/backend/app.jar
COPY local-platform/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY scripts/docker-entrypoint.sh /app/scripts/docker-entrypoint.sh

RUN chmod +x /app/scripts/docker-entrypoint.sh \
    && mkdir -p /data /app/backend/storage /run/nginx \
    && chown -R www-data:www-data /usr/share/nginx/html

EXPOSE 8080 8018

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
