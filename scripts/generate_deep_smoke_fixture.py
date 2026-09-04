#!/usr/bin/env python3
"""Generate the deterministic, fully local two-page deep-smoke fixture."""
from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "fixtures" / "deep_smoke"
QR_PAYLOAD = "DOC-AI-BENCHMARK-QR-2026"


def _gf_mul(x: int, y: int) -> int:
    result = 0
    while y:
        if y & 1:
            result ^= x
        y >>= 1
        x = (x << 1) ^ (0x11D if x & 0x80 else 0)
    return result


def _rs_remainder(data: list[int], degree: int) -> list[int]:
    generator = [1]
    root = 1
    for _ in range(degree):
        next_generator = [0] * (len(generator) + 1)
        for index, coefficient in enumerate(generator):
            next_generator[index] ^= coefficient
            next_generator[index + 1] ^= _gf_mul(coefficient, root)
        generator = next_generator
        root = _gf_mul(root, 2)
    remainder = [0] * degree
    for value in data:
        factor = value ^ remainder[0]
        remainder = remainder[1:] + [0]
        for index in range(degree):
            remainder[index] ^= _gf_mul(generator[index + 1], factor)
    return remainder


def _qr_matrix(payload: str) -> list[list[bool]]:
    # QR version 2-L: 34 data codewords + 10 Reed-Solomon codewords.
    bits = [0, 1, 0, 0]
    raw = payload.encode("ascii")
    bits += [(len(raw) >> shift) & 1 for shift in range(7, -1, -1)]
    for value in raw:
        bits += [(value >> shift) & 1 for shift in range(7, -1, -1)]
    bits += [0] * min(4, 34 * 8 - len(bits))
    while len(bits) % 8:
        bits.append(0)
    data = [sum(bits[index + bit] << (7 - bit) for bit in range(8))
            for index in range(0, len(bits), 8)]
    for pad in (0xEC, 0x11) * 20:
        if len(data) == 34:
            break
        data.append(pad)
    codewords = data + _rs_remainder(data, 10)
    stream = [(value >> shift) & 1 for value in codewords for shift in range(7, -1, -1)]

    size = 25
    matrix: list[list[bool | None]] = [[None] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_module(row: int, column: int, value: bool) -> None:
        if 0 <= row < size and 0 <= column < size:
            matrix[row][column] = value
            reserved[row][column] = True

    def finder(top: int, left: int) -> None:
        for row in range(-1, 8):
            for column in range(-1, 8):
                distance = max(abs(row - 3), abs(column - 3))
                set_module(top + row, left + column, distance not in {2, 4})

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)
    for index in range(8, size - 8):
        set_module(6, index, index % 2 == 0)
        set_module(index, 6, index % 2 == 0)
    for row in range(-2, 3):
        for column in range(-2, 3):
            set_module(18 + row, 18 + column, max(abs(row), abs(column)) != 1)
    set_module(size - 8, 8, True)

    format_positions_a = (
        [(row, 8) for row in range(6)] + [(7, 8), (8, 8), (8, 7)]
        + [(8, column) for column in range(5, -1, -1)]
    )
    format_positions_b = (
        [(8, column) for column in range(size - 1, size - 9, -1)]
        + [(row, 8) for row in range(size - 7, size)]
    )
    for row, column in format_positions_a + format_positions_b:
        set_module(row, column, False)

    bit_index = 0
    right = size - 1
    upward = True
    while right > 0:
        if right == 6:
            right -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for column in (right, right - 1):
                if reserved[row][column]:
                    continue
                bit = stream[bit_index] if bit_index < len(stream) else 0
                bit_index += 1
                matrix[row][column] = bool(bit ^ ((row + column) % 2 == 0))
        upward = not upward
        right -= 2

    format_data = 0b01000  # error correction L (01), mask 0 (000)
    value = format_data << 10
    remainder = value
    while remainder.bit_length() >= 11:
        remainder ^= 0x537 << (remainder.bit_length() - 11)
    format_bits = (value | remainder) ^ 0x5412
    for index, ((row_a, col_a), (row_b, col_b)) in enumerate(
        zip(format_positions_a, format_positions_b)
    ):
        bit = bool((format_bits >> index) & 1)
        matrix[row_a][col_a] = bit
        matrix[row_b][col_b] = bit
    return [[bool(value) for value in row] for row in matrix]


def _qr_image() -> Image.Image:
    matrix = _qr_matrix(QR_PAYLOAD)
    scale, border = 8, 4
    image = Image.new("RGB", ((25 + 2 * border) * scale,) * 2, "white")
    draw = ImageDraw.Draw(image)
    for row, values in enumerate(matrix):
        for column, value in enumerate(values):
            if value:
                x = (column + border) * scale
                y = (row + border) * scale
                draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill="black")
    return image


def _asset_image(path: Path, *, rotated: bool = False) -> None:
    image = Image.new("RGB", (720, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.rectangle((5, 5, 714, 254), outline="#1f4e79", width=5)
    headline = (
        "REGIAO ROTACIONADA: texto local 2026"
        if rotated
        else "IMAGEM OCR: Orcamento local 2026"
    )
    draw.text((30, 25), headline, fill="black", font=font)
    draw.text((30, 65), "Item rasterizado: Servico tecnico - R$ 1.234,56", fill="black", font=font)
    draw.line((70, 210, 250, 120, 430, 180, 650, 75), fill="#c00000", width=5)
    draw.ellipse((570, 145, 690, 245), outline="#7030a0", width=5)
    draw.text((600, 185), "SELO", fill="#7030a0", font=font)
    if rotated:
        image = image.rotate(90, expand=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _image_object(image: Image.Image) -> tuple[bytes, int, int]:
    rgb = image.convert("RGB")
    return zlib.compress(rgb.tobytes(), 9), rgb.width, rgb.height


def _build_pdf(chart: Image.Image, rotated: Image.Image, qr: Image.Image) -> bytes:
    objects: list[bytes] = []

    def add(value: bytes) -> int:
        objects.append(value)
        return len(objects)

    catalog_id = add(b"")
    pages_id = add(b"")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    image_ids = []
    for image in (chart, rotated, qr):
        compressed, width, height = _image_object(image)
        image_ids.append(add(
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
            f"/Length {len(compressed)} >>\nstream\n".encode() + compressed + b"\nendstream"
        ))

    def text(x: int, y: int, size: int, value: str) -> str:
        return f"BT /F1 {size} Tf {x} {y} Td ({_pdf_escape(value)}) Tj ET\n"

    page1 = text(50, 800, 18, "Benchmark OCR local - Documento oficial")
    page1 += text(50, 775, 11, "Texto digital em portugues: proposta e orcamento numero 2026-001.")
    page1 += text(50, 745, 12, "Tabela de itens")
    for x in (50, 250, 380, 520):
        page1 += f"{x} 620 m {x} 730 l S\n"
    for y in (620, 650, 690, 730):
        page1 += f"50 {y} m 520 {y} l S\n"
    page1 += text(60, 708, 10, "Item") + text(260, 708, 10, "Qtd") + text(390, 708, 10, "Valor")
    page1 += text(60, 667, 10, "Analise documental") + text(260, 667, 10, "2") + text(390, 667, 10, "R$ 500,00")
    page1 += text(60, 632, 10, "OCR de tabelas") + text(260, 632, 10, "1") + text(390, 632, 10, "R$ 234,56")
    page1 += text(50, 590, 11, "Formula: E = mc^2; total = soma(qtd * valor).")
    page1 += text(50, 565, 11, "Codigo: for pagina in documento: extrair(pagina)")
    page1 += "q 470 0 0 170 50 360 cm /ImChart Do Q\n"
    page1 += text(50, 340, 10, "Grafico e diagrama com tendencia crescente.")
    page1 += "q 145 0 0 145 400 185 cm /ImQR Do Q\n"
    page1 += text(385, 165, 9, f"QR: {QR_PAYLOAD}")

    page2 = text(50, 800, 12, "CABECALHO REPETIDO - Documento oficial 2026")
    page2 += text(50, 770, 16, "Pagina rotacionada e regiao rasterizada")
    page2 += text(50, 740, 11, "Conteudo textual deve permanecer legivel e estruturado.")
    page2 += "q 420 0 0 152 70 500 cm /ImChart Do Q\n"
    page2 += "q 0 210 -100 0 470 220 cm /ImRot Do Q\n"
    page2 += text(50, 110, 10, "RODAPE REPETIDO - benchmark offline")

    content_ids = []
    for content in (page1.encode("latin-1"), page2.encode("latin-1")):
        content_ids.append(add(
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream"
        ))
    resources = (
        f"<< /Font << /F1 {font_id} 0 R >> /XObject << "
        f"/ImChart {image_ids[0]} 0 R /ImRot {image_ids[1]} 0 R /ImQR {image_ids[2]} 0 R >> >>"
    )
    page_ids = [
        add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources {resources} /Contents {content_ids[0]} 0 R >>".encode()),
        add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] /Rotate 90 "
            f"/Resources {resources} /Contents {content_ids[1]} 0 R >>".encode()),
    ]
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Count 2 /Kids [{page_ids[0]} 0 R {page_ids[1]} 0 R] >>".encode()
    )

    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(output)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    chart_path = DESTINATION / "chart_text_stamp.png"
    rotated_path = DESTINATION / "rotated_text_region.png"
    qr_path = DESTINATION / "qr_code.png"
    _asset_image(chart_path)
    _asset_image(rotated_path, rotated=True)
    _qr_image().save(qr_path, format="PNG", optimize=False, compress_level=9)
    pdf_path = DESTINATION / "deep_smoke.pdf"
    pdf_path.write_bytes(_build_pdf(
        Image.open(chart_path), Image.open(rotated_path), Image.open(qr_path)
    ))
    files = [pdf_path, chart_path, rotated_path, qr_path]
    manifest = {
        "schema_version": 1,
        "generator": "scripts/generate_deep_smoke_fixture.py",
        "pages": 2,
        "qr_payload": QR_PAYLOAD,
        "features": [
            "title", "portuguese_digital_text", "markdown_table", "formula", "code",
            "chart_diagram", "text_image", "qr", "stamp", "rotated_raster_region",
        ],
        "files": [
            {"path": path.name, "size_bytes": path.stat().st_size, "sha256": _sha(path)}
            for path in files
        ],
    }
    (DESTINATION / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
