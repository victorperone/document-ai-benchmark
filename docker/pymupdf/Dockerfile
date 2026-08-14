FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-por \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY docker/pymupdf/requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
        -r /tmp/requirements.txt

RUN mkdir -p "${TIKTOKEN_CACHE_DIR}" \
    && python -c \
        "import tiktoken; tiktoken.get_encoding('o200k_base')" \
    && chmod -R a+rX "${TIKTOKEN_CACHE_DIR}"

RUN useradd \
    --create-home \
    --uid 1000 \
    appuser

USER appuser

ENTRYPOINT ["python", "/app/src/parsers/pymupdf_baseline.py"]
