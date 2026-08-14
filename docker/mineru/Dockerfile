FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY docker/mineru/requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
        torch==2.9.1 \
        torchvision==0.24.1 \
        --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir \
        -r /tmp/requirements.txt

RUN mkdir -p "${TIKTOKEN_CACHE_DIR}" \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" \
    && chmod -R a+rX "${TIKTOKEN_CACHE_DIR}"

RUN useradd --create-home --uid 1000 appuser

USER appuser

ENTRYPOINT ["python", "/app/src/parsers/mineru_baseline.py"]
