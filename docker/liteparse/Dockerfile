FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-por \
        libtesseract-dev \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q \
    https://github.com/tesseract-ocr/tessdata/raw/main/osd.traineddata \
    -O /usr/share/tesseract-ocr/5/tessdata/osd.traineddata

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

COPY docker/liteparse/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "import liteparse; print('liteparse OK')" \
    && tesseract --version \
    && tesseract --list-langs

ENTRYPOINT ["python", "/app/src/parsers/liteparse_v2.py"]
