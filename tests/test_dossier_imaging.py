"""A preparação visual conserva a página e encontra grelhas também de lado."""
import base64
import io
import json

import httpx
import pytest
from PIL import Image, ImageDraw

from app.dossiers import imaging, provider
from app.dossiers.models import Inventory


def scanned_grid():
    image = Image.new("RGB", (1600, 1100), "white")
    draw = ImageDraw.Draw(image)
    draw.text((950, 160), "DOCUMENTO DE FABRICO", fill="black")
    for x in range(80, 681, 75):
        draw.line((x, 70, x, 570), fill="black", width=3)
    for y in range(70, 571, 100):
        draw.line((80, y, 680, y), fill="black", width=3)
    return image


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_table_is_localized_after_scan_rotation(angle):
    image = scanned_grid().rotate(angle, expand=True)
    before = image.tobytes()
    regions = imaging.table_regions(image)
    assert len(regions) == 1
    crop = image.crop(regions[0])
    assert sorted(crop.size)[0] >= 500 and sorted(crop.size)[1] >= 600
    assert crop.width * crop.height < image.width * image.height / 3
    output = io.BytesIO()
    image.save(output, format="PNG")
    details = imaging.table_details(output.getvalue())
    assert len(details) == 2 and all("MESMA tabela" in label for label,_ in details)
    assert "vista complementar" in details[1][0]
    with Image.open(io.BytesIO(details[0][1])) as original_view:
        assert original_view.size == crop.size
        expected_companion = original_view.rotate(90, expand=True).tobytes()
    with Image.open(io.BytesIO(details[1][1])) as companion:
        assert companion.size == (crop.height,crop.width)
        assert companion.tobytes() == expected_companion
    assert image.tobytes() == before


def test_blank_page_does_not_create_table_details():
    output = io.BytesIO()
    Image.new("RGB", (1600, 1100), "white").save(output, format="PNG")
    assert imaging.table_details(output.getvalue()) == []
    assert imaging.table_details(output.getvalue(), limit=0) == []


def test_matrix_covering_most_of_page_is_segmented_with_header_context():
    image=Image.new('RGB',(1200,1600),'white');draw=ImageDraw.Draw(image)
    for x in range(20,1181,80):draw.line((x,20,x,1580),fill='black',width=3)
    for y in range(20,1581,80):draw.line((20,y,1180,y),fill='black',width=3)
    regions=imaging.table_regions(image)
    assert regions and (regions[0][2]-regions[0][0])*(regions[0][3]-regions[0][1]) > image.width*image.height*.65
    output=io.BytesIO();image.save(output,format='PNG')
    details=imaging.table_details(output.getvalue(),limit=2)
    assert len(details)==2 and all('segmento' in label for label,_ in details)


def test_large_region_is_rotated_only_after_orientation_was_identified(monkeypatch):
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1199, 79), fill="red")
    draw.rectangle((0, 80, 79, 1599), fill="blue")
    monkeypatch.setattr(imaging, "table_regions", lambda _image, limit: [(0, 0, 1200, 1600)])
    output = io.BytesIO(); image.save(output, format="PNG")

    unknown = imaging.table_details(output.getvalue(), limit=2)
    assert all("vista rodada" not in label for label, _ in unknown)
    details = imaging.table_details(output.getvalue(), limit=2, orientation="clockwise")

    assert len(details) == 2
    assert all("vista rodada 90° no sentido horário" in label for label, _ in details)
    assert all("coordenadas da vista" in label for label, _ in details)
    rotated = image.rotate(-90, expand=True)
    header = rotated.crop((0, 0, 260, 1200))
    body = rotated.crop((260, 0, 1010, 1200))
    expected = Image.new("RGB", (1010, 1200), "white")
    expected.paste(header, (0, 0)); expected.paste(body, (260, 0))
    with Image.open(io.BytesIO(details[0][1])) as first:
        assert first.size == expected.size
        assert first.tobytes() == expected.tobytes()


def test_detail_budget_preserves_every_original_and_physical_page_number(monkeypatch):
    config = {"base_url": "https://model.example/v1", "model": "vision", "api_key": "private",
              "api_format": "responses", "timeout_s": 2, "max_tokens": 2000}
    monkeypatch.setattr(provider, "table_details", lambda data, limit:
        [(f"MESMA tabela: vista {n}", data + b"-detail") for n in range(limit)])
    originals = [(n, f"original-{n}".encode()) for n in range(1, 8)]
    def transport(request):
        content = json.loads(request.content)["input"][0]["content"]
        image_items = [(content[i-1]["text"], part["image_url"]) for i, part in enumerate(content)
                       if part["type"] == "input_image"]
        assert len(image_items) == 20
        for number, original in originals:
            uri = "data:image/png;base64," + base64.b64encode(original).decode()
            assert (f"Página física {number}:", uri) in image_items
        assert all(any(caption.startswith(f"Página física {n}:") for n, _ in originals)
                   for caption, _ in image_items)
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message",
            "content": [{"type": "output_text", "text": '{"pages":[{"page":1,"kind":"other"}]}'}]}]})
    provider.VisionProvider(config, transport=httpx.MockTransport(transport)).request("Read", Inventory, originals)
