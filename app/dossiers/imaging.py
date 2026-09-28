"""Pormenores de grelhas digitalizadas, sem interpretar células ou alterar o PDF."""
from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError


def table_regions(image: Image.Image, *, limit=2) -> list[tuple[int, int, int, int]]:
    """Localiza grelhas pelas linhas e interseções, sem conhecer referências ou máquinas."""
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    if min(width, height) < 200:
        return []
    ink = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, width // 55), 1)))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, height // 55))))
    joints = cv2.bitwise_and(horizontal, vertical)
    grid = cv2.morphologyEx(cv2.bitwise_or(horizontal, vertical), cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if min(w, h) < 100 or area < width * height * .01 or area > width * height * .98:
            continue
        count = cv2.connectedComponents(joints[y:y+h, x:x+w])[0] - 1
        if count < 9:
            continue
        # Privilegia tabelas com muitas células pequenas, onde a página inteira
        # perde legibilidade após a redução de resolução feita pelo modelo.
        candidates.append((count / area ** .5, (x, y, x+w, y+h)))
    candidates.sort(reverse=True)
    selected = []
    for _, bounds in candidates:
        x, y, right, bottom = bounds
        area = (right-x) * (bottom-y)
        if any(max(0, min(right, r)-max(x, l)) * max(0, min(bottom, b)-max(y, t))
               >= .9 * min(area, (r-l)*(b-t)) for l, t, r, b in selected):
            continue
        selected.append(bounds)
        if len(selected) == limit:
            break
    margin = max(12, min(width, height) // 80)
    return [(max(0, x-margin), max(0, y-margin), min(width, right+margin), min(height, bottom+margin))
            for x, y, right, bottom in selected]


def table_details(image_bytes: bytes, *, limit=2, orientation: str | None = None) -> list[tuple[str, bytes]]:
    """Amplia grelhas e dá uma vista complementar quando os dois eixos têm texto."""
    if limit <= 0:
        return []
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            original = source.convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError):
        return []
    details = []
    for index, bounds in enumerate(table_regions(original, limit=limit), 1):
        crop = original.crop(bounds)
        normalized = tuple(round(value / (original.width if n % 2 == 0 else original.height), 5)
                           for n, value in enumerate(bounds))
        page_area = original.width * original.height
        large = crop.width * crop.height > page_area * .45
        views = []
        if large and limit > 1:
            transformation = ""
            if orientation == "clockwise":
                crop = crop.rotate(-90, expand=True)
                transformation = ", vista rodada 90° no sentido horário"
            elif orientation == "counterclockwise":
                crop = crop.rotate(90, expand=True)
                transformation = ", vista rodada 90° no sentido anti-horário"
            elif orientation == "upside_down":
                crop = crop.rotate(180, expand=True)
                transformation = ", vista rodada 180°"
            # Quando o inventário não determinou a orientação, conservar a
            # orientação original. A relação altura/largura não interpreta texto.
            # Keep a small overlap and repeat the leading header band. This is
            # deliberately geometric: no OCR or document-specific row is assumed.
            if crop.height >= crop.width:
                header = crop.crop((0, 0, crop.width, min(220, crop.height)))
                step = max(1, (crop.height - header.height) // limit)
                for part in range(limit):
                    top = max(header.height, header.height + part * step - (80 if part else 0))
                    bottom = crop.height if part == limit - 1 else min(crop.height, header.height + (part + 1) * step + 80)
                    body = crop.crop((0, top, crop.width, bottom))
                    view = Image.new("RGB", (crop.width, header.height + body.height), "white")
                    view.paste(header, (0, 0)); view.paste(body, (0, header.height))
                    views.append((part + 1, view, (0, top, crop.width, bottom), "segmento", transformation))
            else:
                header = crop.crop((0, 0, min(260, crop.width), crop.height))
                step = max(1, (crop.width - header.width) // limit)
                for part in range(limit):
                    left = max(header.width, header.width + part * step - (80 if part else 0))
                    right = crop.width if part == limit - 1 else min(crop.width, header.width + (part + 1) * step + 80)
                    body = crop.crop((left, 0, right, crop.height))
                    view = Image.new("RGB", (header.width + body.width, crop.height), "white")
                    view.paste(header, (0, 0)); view.paste(body, (header.width, 0))
                    views.append((part + 1, view, (left, 0, right, crop.height), "segmento", transformation))
        else:
            # Matrizes de distribuição podem ter máquinas num eixo e referências
            # impressas verticalmente no outro. Uma única vista rodada torna esse
            # segundo eixo legível sem enviar quatro rotações indiferenciadas.
            views = [(1, crop, (0, 0, crop.width, crop.height), "original", "")]
            if limit - len(details) > 1:
                # Nas matrizes MTG as referências verticais ficam direitas com
                # a rotação anti-horária; o sentido oposto deixa-as invertidas.
                views.append((2, crop.rotate(90, expand=True),
                              (0, 0, crop.width, crop.height), "complementar", ""))
        for part, view, segment, kind, transformation in views:
            if len(details) >= limit:
                break
            view.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            output = io.BytesIO(); view.save(output, format="PNG")
            suffix = (f"{transformation}, segmento {part}/{len(views)} {segment} nas coordenadas da vista" if kind == "segmento" else
                      ", vista complementar rodada 90° para ler o outro eixo" if kind == "complementar" else "")
            details.append((f"Pormenor {index}{suffix}, região original normalizada {normalized}. "
                "É uma ampliação da MESMA tabela e página; cabeçalhos repetidos dão contexto e não duplicam peças ou quantidades.",
                output.getvalue()))
        if len(details) >= limit:
            break
    return details
