FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache

WORKDIR /app

COPY docker/docling/requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt

# Docling / docling-ibm-models may install the GUI-enabled OpenCV package.
# Docker and server environments are headless, so replace it with the
# headless distribution recommended by Docling.
RUN python -m pip uninstall -y \
        opencv-python \
        opencv-python-headless \
    && python -m pip install \
        --no-cache-dir \
        opencv-python-headless==5.0.0.93

RUN mkdir -p "${TIKTOKEN_CACHE_DIR}" \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" \
    && chmod -R a+rX "${TIKTOKEN_CACHE_DIR}"

RUN useradd --create-home --uid 1000 appuser

USER appuser

ENTRYPOINT ["python", "/app/src/parsers/docling_baseline.py"]
