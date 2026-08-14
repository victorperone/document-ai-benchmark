FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY docker/paddleocr/requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
        paddlepaddle==3.2.0 \
        -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
    && python -m pip install --no-cache-dir \
        -r /tmp/requirements.txt

RUN mkdir -p "${TIKTOKEN_CACHE_DIR}" \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" \
    && chmod -R a+rX "${TIKTOKEN_CACHE_DIR}"

RUN useradd --create-home --uid 1000 appuser

USER appuser

ENTRYPOINT ["python", "/app/src/parsers/paddleocr_baseline.py"]
