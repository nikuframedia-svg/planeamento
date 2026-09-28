"""Integração da entrada PDF, checkpoints, conferência e controlo de versões.

O modelo é simulado de forma explícita; não se mede aqui a precisão de uma API.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import stat
import threading
import os
import time
from pathlib import Path
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.config import settings
from app.dossiers import DossierError, cpis, macro, material, pdf, pipeline, provider, store, inbox
from app.dossiers.models import (Extraction, Inventory, Piece, REQUIRED_FIELDS,
                                 difference_decision_fingerprint, need_key, ref_key)
from app.web import dossier_routes
from app.web.planning_app import app


@pytest.fixture(autouse=True)
def isolated_dossiers(tmp_path, monkeypatch):
    isolated = dataclasses.replace(settings, data_dir=tmp_path, admin_token="test-administration")
    for module in (store, provider, dossier_routes):
        monkeypatch.setattr(module, "settings", isolated)
    for key in provider.CONFIG_ENV.values():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MES_DOSSIER_WORKER_DISABLED", "1")
    monkeypatch.delenv("MES_DOSSIER_INBOX", raising=False)


def pdf_bytes(pages=2, suffix=""):
    document = FPDF()
    document.set_creation_date(datetime(2026, 9, 14, tzinfo=timezone.utc))
    for n in range(pages):
        document.add_page()
        document.set_font("Helvetica", size=15)
        document.cell(text=f"OF265931 | drawing REF-A | {n+1} | {suffix}")
    return bytes(document.output())


def piece_values(ref="REF-A", quantity=6, length=1200, page=2, **kwargs):
    data = {"component_ref": ref, "drawing_ref": "REF-A", "material_type": "Tubo redondo",
            "profile": "114x3", "grade": "S275JR", "quantity_required": quantity, "length_mm": length,
            **kwargs}
    data["evidence"] = {k: {"page": page, "text": str(v)} for k, v in data.items() if v is not None}
    return Piece.model_validate(data).model_dump()


def tool_response(arguments):
    return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None,
        "tool_calls": [{"type": "function", "id": "call_0", "function": {
            "name": "record_result", "arguments": arguments}}]}}]}


def context(of="OF265931", *, rows=None, status="Em Aberto"):
    return {"production_order": of, "sales_order": "OV2607672", "customer": "Cliente",
            "designation": "Colunas 3 m", "status": status, "delivery_date": "2026-10-02",
            "snapshot": {"snapshot_id": "test-s1", "source_filename": "Met2_Plan_Perfis.xlsm", "loaded_at": "2026-09-14T10:00:00Z"},
            "plan_rows": rows or [], "machines": ["Vanguard", "Serrote MEBA"],
            "issues": [] if status in ("Em Aberto", "Em Produção") else [cpis.issue("of_closed", "OF fechada", blocking=True)]}


def plan_row(ref="REF-A", *, quantity=6, completed=None, profile="114x3", length=1200):
    return {"source_line_id": "test-s1:7", "excel_row": 7, "component_ref": ref,
            "profile_type": profile, "length_mm": length, "quantity_planned": quantity, "closed_x": False,
            "row_data": {"Ser.": completed, "Aboc.": None, "Qual.": "S275JR"}}


class FakeVision:
    def __init__(self, *, pieces=None, fail_inventory=None, routes=None, warnings=None):
        self.calls = []
        self.pieces = pieces or [piece_values()]
        self.fail_inventory = fail_inventory
        self.routes = routes if routes is not None else [{"reference": "REF-A", "machine_group": "Serrote", "quantity": 6, "evidence": "REF-A · X Serrote"}]
        self.warnings = warnings or []

    def request(self, prompt, schema, images=()):
        numbers = [p for p, image in images]
        assert all(image.startswith(b"\x89PNG") for _, image in images)
        self.calls.append((schema.__name__, numbers))
        if schema is Inventory:
            if self.fail_inventory and self.fail_inventory in numbers:
                self.fail_inventory = None
                raise DossierError("Falha de ligação simulada", 502)
            pages = [{"page": p, "kind": "distribution" if p==1 else "drawing" if p==2 else "other",
                      "production_order": "OF265931", "sales_order": "OV2607672",
                      "references": ["REF-A"] if p==2 else [], "routes": self.routes if p==1 else [],
                      "warnings": self.warnings if p==1 else []} for p in numbers]
            return schema.model_validate({"pages": pages}).model_dump()
        if schema is Extraction:
            return schema.model_validate({"pieces": self.pieces}).model_dump()
        raise AssertionError("Pedido inesperado ao modelo")


class FlexibleVision:
    def __init__(self, inventory_pages, pieces, verification=None):
        self.inventory_pages = {page["page"]: page for page in inventory_pages}
        self.pieces = pieces
        self.verification = verification
        self.calls = []

    def request(self, prompt, schema, images=()):
        numbers = [number for number, image in images]
        assert all(image.startswith(b"\x89PNG") for _, image in images)
        self.calls.append((schema.__name__, numbers))
        if schema is Inventory:
            return schema.model_validate({"pages": [self.inventory_pages[n] for n in numbers]}).model_dump()
        if schema is Extraction:
            return schema.model_validate({"pieces": self.pieces}).model_dump()
        if schema.__name__ == 'WorkItemVerification':
            source=self.verification or self.pieces[0]
            return schema.model_validate({'quantity_required':source.get('quantity_required'),
                'length_mm':source.get('length_mm'),'evidence':{field:source.get('evidence',{}).get(field)
                for field in ('quantity_required','length_mm') if source.get('evidence',{}).get(field)},
                'warnings':[]}).model_dump()
        raise AssertionError("Pedido inesperado ao modelo")


def processed(monkeypatch, *, model=None, ctx=None, suffix=""):
    uid = store.ingest(pdf_bytes(suffix=suffix), "OF265931.pdf")["id"]
    monkeypatch.setattr(cpis, "read_context", lambda of: copy.deepcopy(ctx or context(of)))
    pipeline.process_document(uid, provider=model or FakeVision())
    return store.get_document(uid)


def test_upload_waits_for_model_and_deduplicates_entire_pdf(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unrelated-key-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "another-unrelated-key")
    with TestClient(app) as client:
        response = client.post("/planeamento/api/dossies", files={"file": ("../OF265931.pdf", pdf_bytes(), "application/pdf")})
        assert response.status_code == 200
        uid = response.json()["id"]
        assert not response.json()["duplicate"]
        repeated = client.post("/planeamento/api/dossies", files={"file": ("renamed.pdf", pdf_bytes(), "application/pdf")})
        assert repeated.json() == {"id": uid, "duplicate": True}
        doc = client.get(f"/planeamento/api/dossies/{uid}").json()
        assert doc["filename"] == "OF265931.pdf" and doc["page_count"] == 2
        assert doc["status"] == "waiting_api" and doc["pieces"] == []
        assert not client.get("/planeamento/api/modelo").json()["configured"]
        assert client.get(f"/planeamento/api/dossies/{uid}/pagina/2").content.startswith(b"\x89PNG")
        assert client.get(f"/planeamento/api/dossies/{uid}/pagina/3").status_code == 404
        assert client.get(f"/planeamento/api/dossies/{uid}/pdf").content == pdf_bytes()
        assert client.post("/planeamento/api/processar", json={}).status_code == 409


def test_invalid_upload_and_cross_site_posts_are_rejected():
    with TestClient(app) as client:
        for filename, data in [("malware.html", b"<script>"), ("broken.pdf", b"%PDF-1.7 broken")]:
            assert client.post("/planeamento/api/dossies", files={"file": (filename, data)}).status_code == 422
        assert client.post("/planeamento/api/dossies", files={"file": ("OF.pdf", pdf_bytes())},
                           headers={"Origin": "https://other.example"}).status_code == 403
        page=client.get("/planeamento/dossies")
        assert page.status_code == 200 and 'id="pdf-files"' in page.text
        assert "Conferido por" not in page.text and "Pedido por" not in page.text
        assert 'id="review-machine-group"' in page.text
        assert client.get("/planeamento/manual").status_code == 200
        assert store.list_documents() == []


def test_secret_is_never_returned_and_configuration_requires_local_or_admin():
    config = {"base_url": "https://model.example/v1", "model": "vision", "api_key": "very-private-key"}
    with TestClient(app, base_url="https://factory.example") as client:
        assert client.put("/planeamento/api/modelo", json=config).status_code == 403
        response = client.put("/planeamento/api/modelo", json=config, headers={"X-Planning-Admin": "test-administration"})
        assert response.status_code == 200
        assert "very-private-key" not in response.text and "api_key" not in response.json()
        status = client.get("/planeamento/api/modelo")
        assert status.json()["has_key"] and status.json()["configured"]
        assert "very-private-key" not in status.text
        assert "very-private-key" not in client.get("/planeamento/api/dossies").text
    assert stat.S_IMODE(provider.config_path().stat().st_mode) == 0o600
    with TestClient(app) as client:
        changed = client.put("/planeamento/api/modelo", json={**config, "model": "new-model", "api_key": ""})
        assert changed.status_code == 200 and provider.read_config()["api_key"] == "very-private-key"
        for url in ("https://key:secret@model.example/v1", "http://model.example/v1", "https://model.example/v1?key=x", "file:///etc/passwd"):
            assert client.put("/planeamento/api/modelo", json={**config, "base_url": url}).status_code == 422


def test_environment_configuration_is_read_only(monkeypatch):
    monkeypatch.setenv("MES_DOSSIER_MODEL", "in-environment")
    with TestClient(app) as client:
        assert client.get("/planeamento/api/modelo").json()["environment_managed"]
        assert client.put("/planeamento/api/modelo", json={"model": "another"}).status_code == 409


@pytest.mark.parametrize("api_format", ["chat_completions", "responses"])
def test_connector_sends_images_and_rejects_truncated_output(api_format):
    config = {"base_url": "https://model.example/v1", "model": "vision-model", "api_key": "private",
              "api_format": api_format, "timeout_s": 2, "max_tokens": 2000}
    result = {"pieces": [piece_values()]}
    requests = []
    truncated = False
    def transport(request):
        requests.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer private"
        if api_format == "responses":
            return httpx.Response(200, json={"status": "incomplete" if truncated else "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "length" if truncated else "stop",
            "message": {"content": json.dumps(result)}}]})
    engine = provider.VisionProvider(config, transport=httpx.MockTransport(transport))
    assert engine.request("Read this drawing", Extraction, [(2, b"test-image")])["pieces"][0]["quantity_required"] == 6
    raw = json.dumps(requests[0])
    assert "data:image/png;base64," in raw and "vision-model" in raw and "private" not in raw
    assert "response_format" not in requests[0] and "text" not in requests[0]
    truncated = True
    with pytest.raises(DossierError) as exc:
        engine.request("Read", Extraction)
    assert exc.value.kind == ("model_output_limit" if api_format == "chat_completions" else "model_output")


def test_connector_does_not_follow_redirects_or_expose_provider_error():
    config = {"base_url": "https://model.example/v1", "model": "vision", "api_key": "private",
              "api_format": "chat_completions", "timeout_s": 2, "max_tokens": 2000}
    calls = []
    def transport(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"Location": "https://another.example/steal"}, text="private diagnostic")
    with pytest.raises(DossierError) as exc:
        provider.VisionProvider(config, transport=httpx.MockTransport(transport)).request("Read", Extraction)
    assert len(calls) == 1 and "private" not in str(exc.value)


@pytest.mark.parametrize("api_format", ["responses", "chat_completions"])
def test_reasoning_effort_and_long_request_limits_reach_the_provider(api_format):
    saved = provider.save_config({"base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
        "model": "xai.grok-4.6", "api_key": "private", "api_format": api_format,
        "reasoning_effort": "xhigh", "timeout_s": 600, "max_tokens": 24000})
    assert saved["reasoning_effort"] == "xhigh" and "api_key" not in saved
    def transport(request):
        body = json.loads(request.content)
        assert request.extensions["timeout"]["read"] == 600
        if api_format == "responses":
            format_spec = body["text"]["format"]
            assert format_spec["strict"] is True and format_spec["name"] == "Extraction"
            assert format_spec["schema"]["$defs"]["Piece"]["properties"]["quantity_required"]["anyOf"][0]["minimum"] == 1
            assert format_spec["schema"]["$defs"]["Piece"]["properties"]["evidence"]["additionalProperties"] == {"$ref": "#/$defs/Evidence"}
            assert body["reasoning"] == {"effort": "xhigh"}
            assert body["max_output_tokens"] == 24000 and body["store"] is False
            return httpx.Response(200, json={"status": "completed", "output": [{"type": "message",
                "content": [{"type": "output_text", "text": '{"pieces": []}'}]}]})
        assert body["reasoning_effort"] == "xhigh" and body["max_completion_tokens"] == 24000
        assert "response_format" not in body
        assert body["parallel_tool_calls"] is False
        assert body["tool_choice"] == {"type": "function", "function": {"name": "record_result"}}
        assert body["tools"][0]["function"]["parameters"] == Extraction.model_json_schema()
        assert "Esquema JSON obrigatório" not in body["messages"][1]["content"][0]["text"]
        return httpx.Response(200, json=tool_response('{"pieces": []}'))
    assert provider.VisionProvider(transport=httpx.MockTransport(transport)).request("Read", Extraction)["pieces"] == []
    changed = provider.save_config({"model": "another-model"})
    assert changed["reasoning_effort"] == "" and provider.read_config()["api_key"] == "private"


@pytest.mark.parametrize("payload", [
    {"reasoning_effort": "unknown"}, {"reasoning_effort": None},
    {"reasoning_effort": "xhigh", "api_format": "bedrock_converse"},
    {"timeout_s": True}, {"timeout_s": 0}, {"timeout_s": 901},
    {"max_tokens": 0}, {"max_tokens": 128001},
])
def test_invalid_reasoning_settings_do_not_replace_saved_configuration(payload):
    provider.save_config({"base_url": "https://model.example/v1", "model": "vision", "api_key": "private"})
    before = provider.config_path().read_bytes()
    with pytest.raises(DossierError):
        provider.save_config(payload)
    assert provider.config_path().read_bytes() == before


def test_read_timeout_does_not_repeat_a_potentially_running_inference():
    config = {"base_url": "https://model.example/v1", "model": "vision", "api_key": "private",
              "api_format": "responses", "timeout_s": 2, "max_tokens": 2000}
    calls = []
    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout("private upstream details", request=request)
    with pytest.raises(DossierError, match="não foi repetido") as exc:
        provider.VisionProvider(config, transport=httpx.MockTransport(transport)).request("Read", Extraction)
    assert exc.value.status == 504 and len(calls) == 1 and "private" not in str(exc.value)


@pytest.mark.parametrize("failure", ["transport", "server"])
def test_transient_provider_failure_has_only_one_automatic_retry(failure):
    config = {"base_url": "https://model.example/v1", "model": "vision", "api_key": "private",
              "api_format": "responses", "timeout_s": 2, "max_tokens": 2000}
    calls = []
    def transport(request):
        calls.append(request)
        if failure == "transport":
            raise httpx.ConnectError("private upstream details", request=request)
        return httpx.Response(503, text="private upstream details")
    with pytest.raises(DossierError) as exc:
        provider.VisionProvider(config, transport=httpx.MockTransport(transport)).request("Read", Extraction)
    assert len(calls) == 2 and exc.value.kind == failure and "private" not in str(exc.value)


@pytest.mark.parametrize("api_format", ["responses", "chat_completions"])
def test_token_limited_native_output_is_rejected_even_when_its_json_looks_complete(api_format):
    config = {"base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
              "model": "xai.grok-4.6", "api_key": "private", "api_format": api_format,
              "timeout_s": 600, "max_tokens": 24000}
    calls = []
    def transport(request):
        calls.append(request)
        if api_format == "chat_completions":
            return httpx.Response(200, json={"choices": [{"finish_reason": "length",
                "message": {"content": '{"pieces": []}'}}]})
        return httpx.Response(200, json={"status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"pieces": []}'}]}]})
    with pytest.raises(DossierError, match="limite de tokens"):
        provider.VisionProvider(config, transport=httpx.MockTransport(transport)).request("Read", Extraction)
    assert len(calls) == 1


def test_structured_tool_mode_keeps_local_field_validation():
    config = {"base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
              "model": "xai.grok-4.6", "api_key": "private", "api_format": "chat_completions",
              "timeout_s": 600, "max_tokens": 24000}
    calls = []
    def transport(request):
        calls.append(request)
        assert json.loads(request.content)["tool_choice"]["function"]["name"] == "record_result"
        return httpx.Response(200, json=tool_response(json.dumps({"pieces": [{"quantity_required": -1}]})))
    with pytest.raises(DossierError, match="campos pedidos"):
        provider.VisionProvider(config, httpx.MockTransport(transport)).request("Read", Extraction)
    assert len(calls) == 2


@pytest.mark.parametrize("defect", ["wrong_name", "multiple_calls", "refusal", "incomplete"])
def test_structured_tool_accepts_only_one_complete_expected_result(defect):
    config = {"base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
              "model": "xai.grok-4.6", "api_key": "private", "api_format": "chat_completions",
              "timeout_s": 600, "max_tokens": 24000}
    response = tool_response('{"pieces": []}')
    choice = response["choices"][0]
    message = choice["message"]
    if defect == "wrong_name": message["tool_calls"][0]["function"]["name"] = "other_action"
    elif defect == "multiple_calls": message["tool_calls"] *= 2
    elif defect == "refusal": message["refusal"] = "Unable"
    elif defect == "incomplete": choice["finish_reason"] = "length"
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=response)
    with pytest.raises(DossierError):
        provider.VisionProvider(config, httpx.MockTransport(transport)).request("Read", Extraction)
    assert len(requests) == 1


def test_structured_tool_uses_arguments_and_ignores_accompanying_commentary():
    config = {"base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
              "model": "xai.grok-4.6", "api_key": "private", "api_format": "chat_completions",
              "timeout_s": 600, "max_tokens": 24000}
    response = tool_response('{"pieces": []}')
    response["choices"][0]["message"]["content"] = 'Explanation, not structured result: {"pieces": [{"quantity_required": -1}]}'
    engine = provider.VisionProvider(config, httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    assert engine.request("Read", Extraction)["pieces"] == []


@pytest.mark.parametrize('api_format', ['responses', 'chat_completions'])
@pytest.mark.parametrize('recovers', [True, False])
def test_conflicting_native_json_gets_only_one_new_reading_without_salvaging_data(api_format, recovers):
    config = {'base_url': 'https://bedrock-mantle.us-west-2.api.aws/openai/v1',
              'model': 'xai.grok-4.6', 'api_key': 'private', 'api_format': api_format,
              'timeout_s': 600, 'max_tokens': 24000}
    calls = []
    def transport(request):
        body = json.loads(request.content)
        content = body['input'][0]['content'] if api_format == 'responses' else body['messages'][1]['content']
        calls.append(content)
        assert all('Esquema JSON obrigatório' not in p.get('text', '') for p in content)
        text = ('{"pieces": []}' if recovers and len(calls) == 2
                else '{"pieces": []}{"pieces": [], "warnings": ["different"]}')
        if api_format == 'responses':
            return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message',
                'content': [{'type': 'output_text', 'text': text}]}]})
        return httpx.Response(200, json=tool_response(text))
    engine = provider.VisionProvider(config, transport=httpx.MockTransport(transport))
    if recovers:
        assert engine.request('Read', Extraction)['pieces'] == []
    else:
        with pytest.raises(DossierError, match='JSON completo'):
            engine.request('Read', Extraction)
    assert len(calls) == 2
    assert calls[1][:-1] == calls[0] and 'exatamente UM objeto' in calls[1][-1]['text']


@pytest.mark.parametrize(('written', 'canonical'), [
    ('Ø114 x 3', '114x3'), (' 60×3,5 ', '60x3.5'),
    ('80 X 40 X 2', '80x40x2'), ('UPN 100', 'UPN 100'),
    ('Tubo Ø114 x 3 x 1200', 'Tubo Ø114 x 3 x 1200'),
])
def test_profile_normalization_changes_only_unambiguous_typography(written, canonical):
    data = Piece.model_validate({'profile': written,
        'evidence': {'profile': {'page': 4, 'text': written}}})
    assert data.profile == canonical and data.evidence['profile'].text == written
    assert data.length_mm is None and data.outer_diameter_mm is None


@pytest.mark.parametrize("model", ["eu.anthropic.claude-sonnet-4-6", "arn:aws:bedrock:eu-central-1:123456789012:inference-profile/example"])
def test_bedrock_connector_uses_converse_and_image_bytes(model):
    import base64
    from urllib.parse import unquote
    config = {"base_url": "https://bedrock-runtime.eu-central-1.amazonaws.com", "model": model,
              "api_key": "private", "api_format": "bedrock_converse", "timeout_s": 2, "max_tokens": 2000}
    def transport(request):
        assert unquote(request.url.raw_path.decode()) == f"/model/{model}/converse"
        assert request.headers["authorization"] == "Bearer private"
        body = json.loads(request.content)
        assert "model" not in body and "private" not in request.content.decode()
        assert body["inferenceConfig"] == {"maxTokens": 2000, "temperature": 0}
        assert body["system"][0]["text"] == provider.SYSTEM
        blocks = body["messages"][0]["content"]
        assert blocks[1] == {"text": "Página física 2:"}
        assert base64.b64decode(blocks[2]["image"]["source"]["bytes"]) == b"test-image"
        assert blocks[2]["image"]["format"] == "png"
        return httpx.Response(200, json={"stopReason": "end_turn", "output": {"message": {
            "role": "assistant", "content": [{"text": json.dumps({"pieces": [piece_values()]})}]}}})
    engine = provider.VisionProvider(config, transport=httpx.MockTransport(transport))
    assert engine.request("Read", Extraction, [(2, b"test-image")])["pieces"][0]["quantity_required"] == 6


@pytest.mark.parametrize("reason", ["max_tokens", "guardrail_intervened", "content_filtered", "tool_use", None])
def test_bedrock_rejects_unfinished_or_blocked_output(reason):
    config = {"base_url": "https://bedrock-runtime.eu-central-1.amazonaws.com", "model": "vision",
              "api_key": "private", "api_format": "bedrock_converse", "timeout_s": 2, "max_tokens": 2000}
    response = {"stopReason": reason, "output": {"message": {"content": [{"text": '{"pieces": []}'}]}}}
    engine = provider.VisionProvider(config, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    with pytest.raises(DossierError) as exc:
        engine.request("Read", Extraction)
    expected = "model_output_limit" if reason == "max_tokens" else (
        "content_filter" if reason in ("guardrail_intervened", "content_filtered") else "model_output")
    assert exc.value.kind == expected


def test_bedrock_configuration_keeps_server_key_and_never_returns_it():
    provider.save_config({"base_url": "https://model.example/v1", "model": "old-model", "api_key": "private"})
    config = provider.save_config({"base_url": "https://bedrock-runtime.eu-central-1.amazonaws.com",
                                  "model": "eu.anthropic.claude-sonnet-4-6", "api_format": "bedrock_converse"})
    assert config["configured"] and config["has_key"] and "api_key" not in config
    assert provider.read_config()["api_key"] == "private"


def test_bedrock_daily_limit_does_not_repeat_calls_or_expose_diagnostics():
    config = {"base_url": "https://bedrock-runtime.eu-central-1.amazonaws.com", "model": "vision",
              "api_key": "private", "api_format": "bedrock_converse", "timeout_s": 2, "max_tokens": 2000}
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(429, json={"message": "Too many tokens per day, please wait before trying again. private"})
    engine = provider.VisionProvider(config, transport=httpx.MockTransport(transport))
    with pytest.raises(DossierError, match="limite diário") as exc:
        engine.request("Read", Extraction)
    assert len(calls) == 1 and exc.value.status == 429 and "private" not in str(exc.value)


def test_mantle_model_unavailable_is_distinct_from_invalid_key():
    config = {"base_url": "https://bedrock-mantle.us-east-1.api.aws/openai/v1", "model": "openai.gpt-5.6-sol",
              "api_key": "private", "api_format": "responses", "timeout_s": 2, "max_tokens": 2000}
    calls = []
    def transport(request):
        calls.append(request)
        assert str(request.url) == config["base_url"] + "/responses"
        return httpx.Response(401, json={"error": {"code": "access_denied", "type": "permission_denied_error",
            "message": "openai.gpt-5.6-sol is not available for this account. private"}})
    engine = provider.VisionProvider(config, transport=httpx.MockTransport(transport))
    with pytest.raises(DossierError, match="não está disponível para esta conta AWS") as exc:
        engine.request("Read", Extraction)
    assert len(calls) == 1 and "HTTP 401" in str(exc.value) and "private" not in str(exc.value)


@pytest.mark.parametrize("raw", ['{"pieces": [', '{"pieces": [], "value": NaN}', '[]', 'prefix {"pieces": []}'])
def test_json_is_not_salvaged_into_apparently_complete_data(raw):
    with pytest.raises(DossierError): provider.parse_json(raw)


def test_json_accepts_only_complete_identical_repetitions():
    value = {"pages": [{"page": 17, "references": ["1234.T.020"]}]}
    raw = json.dumps(value) + "\n" + json.dumps(value, indent=2)
    assert provider.parse_json(raw) == value

    different = {"pages": [{"page": 18, "references": ["1234.T.020"]}]}
    for invalid in (json.dumps(value) + json.dumps(different),
                    json.dumps(value) + '{"pages": [',
                    json.dumps(value) + " trailing text"):
        with pytest.raises(DossierError):
            provider.parse_json(invalid)


def test_new_cpis_order_without_manual_plan_line_becomes_ready(monkeypatch):
    doc = processed(monkeypatch)
    assert doc["status"] == "ready" and doc["production_order"] == "OF265931"
    piece = doc["pieces"][0]
    assert piece["match"]["kind"] == "new" and piece["match"]["quantity_completed"] is None
    assert piece["values"]["quantity_required"] == 6 and not piece["issues"]
    assert len(store.plan_rows()) == 1
    with TestClient(app) as client:
        public = client.get(f"/planeamento/api/dossies/{doc['id']}").json()
        assert "source" not in public["context"] and "plan_rows" not in public["context"]


def test_resume_uses_page_checkpoints_and_does_not_double_quantities(monkeypatch):
    uid = store.ingest(pdf_bytes(pages=4), "OF265931.pdf")["id"]
    monkeypatch.setattr(cpis, "read_context", lambda _: context())
    model = FakeVision(fail_inventory=3)
    with pytest.raises(DossierError): pipeline.process_document(uid, provider=model)
    assert set(store.checkpoints(uid, "inventory")) == {"1", "2"}
    pipeline.process_document(uid, provider=model)
    assert model.calls.count(("Inventory", [1,2])) == 1
    assert len(store.get_document(uid)["pieces"]) == 1
    assert sum(p["values"]["quantity_required"] for p in store.plan_rows()) == 6
    count = len(model.calls)
    pipeline.process_document(uid, provider=model)
    assert len(model.calls) == count
    assert len(store.plan_rows()) == 1


def test_inventory_retries_inconsistent_pair_as_individual_pages(monkeypatch):
    class InconsistentPair(FakeVision):
        def request(self, prompt, schema, images=()):
            numbers = [number for number, _image in images]
            if schema is Inventory and len(numbers) == 2:
                self.calls.append((schema.__name__, numbers))
                page = {"page": numbers[0], "kind": "distribution", "production_order": "OF265931",
                        "sales_order": "OV2607672", "references": [], "routes": self.routes,
                        "warnings": []}
                return schema.model_validate({"pages": [page, page]}).model_dump()
            return super().request(prompt, schema, images)

    uid = store.ingest(pdf_bytes(), "OF265931.pdf")["id"]
    monkeypatch.setattr(cpis, "read_context", lambda _: context())
    model = InconsistentPair()
    pipeline.process_document(uid, provider=model)

    assert model.calls[:3] == [("Inventory", [1, 2]), ("Inventory", [1]), ("Inventory", [2])]
    assert set(store.checkpoints(uid, "inventory")) == {"1", "2"}
    assert store.get_document(uid)["status"] == "ready"


def test_unique_drawing_wins_over_assembly_reference_but_assembly_is_kept_as_support():
    inventory = [
        {"page": 3, "kind": "drawing",
         "references": ["1234.T.J49", "1234.T.120", "1234.T.121", "1234.T.122"]},
        {"page": 33, "kind": "drawing", "references": ["1234.T.121", "1234T121.dwg"]},
    ]

    link = pipeline.resolve_pages("doc", "run", {"reference": "1234.T.121", "key": "route"},
                                  inventory, provider=object())

    assert link == {"pages": [33], "support_pages": [3], "uncertain": False,
                    "explanation": "Referência coincidente na página de desenho mais específica; listas de conjunto usadas apenas como apoio."}


def test_inventory_rejects_inconsistent_individual_retry(monkeypatch):
    class AlwaysWrongPage(FakeVision):
        def request(self, prompt, schema, images=()):
            numbers = [number for number, _image in images]
            if schema is Inventory:
                self.calls.append((schema.__name__, numbers))
                wrong = numbers[-1] + 1
                page = {"page": wrong, "kind": "other", "production_order": None,
                        "sales_order": None, "references": [], "routes": [], "warnings": []}
                return schema.model_validate({"pages": [page]}).model_dump()
            return super().request(prompt, schema, images)

    uid = store.ingest(pdf_bytes(), "OF265931.pdf")["id"]
    model = AlwaysWrongPage()
    with pytest.raises(DossierError, match="releitura isolada"):
        pipeline.process_document(uid, provider=model)

    assert model.calls == [("Inventory", [1, 2]), ("Inventory", [1]), ("Inventory", [2])]
    assert store.checkpoints(uid, "inventory") == {}


def test_inventory_keeps_processing_independent_pages_after_content_failure():
    class OneBadPage(FakeVision):
        config = {"base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
                  "model": "xai.grok-4.6", "api_format": "chat_completions"}

        def request(self, prompt, schema, images=()):
            numbers = [number for number, _image in images]
            if schema is Inventory and numbers == [2]:
                self.calls.append((schema.__name__, numbers))
                raise DossierError("limite simulado", 502, kind="model_output_limit")
            return super().request(prompt, schema, images)

    uid = store.ingest(pdf_bytes(pages=3), "OF265931.pdf")["id"]
    model = OneBadPage()
    with pytest.raises(DossierError, match="restantes páginas foram guardadas"):
        pipeline.process_document(uid, provider=model)

    assert model.calls == [("Inventory", [1]), ("Inventory", [2]),
                           ("Inventory", [2]), ("Inventory", [3])]
    assert set(store.checkpoints(uid, "inventory")) == {"1", "3"}


@pytest.mark.parametrize("failure_kind", ["model_output", "model_output_limit"])
def test_inventory_retries_completed_but_invalid_model_output_as_single_pages(monkeypatch, failure_kind):
    class InvalidStructuredPair(FakeVision):
        def request(self, prompt, schema, images=()):
            numbers = [number for number, _image in images]
            if schema is Inventory and len(numbers) == 2:
                self.calls.append((schema.__name__, numbers))
                raise DossierError("Saída estruturada inválida", 502, kind=failure_kind)
            return super().request(prompt, schema, images)

    uid = store.ingest(pdf_bytes(), "OF265931.pdf")["id"]
    monkeypatch.setattr(cpis, "read_context", lambda _: context())
    model = InvalidStructuredPair()
    pipeline.process_document(uid, provider=model)

    assert model.calls[:3] == [("Inventory", [1, 2]), ("Inventory", [1]), ("Inventory", [2])]
    assert set(store.checkpoints(uid, "inventory")) == {"1", "2"}
    assert store.get_document(uid)["status"] == "ready"


def test_inventory_does_not_repeat_transport_failure_page_by_page():
    class TransportFailure(FakeVision):
        def request(self, prompt, schema, images=()):
            numbers = [number for number, _image in images]
            self.calls.append((schema.__name__, numbers))
            raise DossierError("Falha de transporte", 502)

    uid = store.ingest(pdf_bytes(), "OF265931.pdf")["id"]
    model = TransportFailure()
    with pytest.raises(DossierError, match="transporte"):
        pipeline.process_document(uid, provider=model)

    assert model.calls == [("Inventory", [1, 2])]
    assert store.checkpoints(uid, "inventory") == {}


def test_mantle_structured_tool_inventory_reads_and_checkpoints_one_page_at_a_time(monkeypatch):
    model = FakeVision()
    model.config = {"base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
                    "model": "xai.grok-4.6", "api_format": "chat_completions"}
    doc = processed(monkeypatch, model=model)
    assert doc["status"] == "ready"
    assert [pages for schema, pages in model.calls if schema == "Inventory"] == [[1], [2]]
    assert set(store.checkpoints(doc["id"], "inventory")) == {"1", "2"}


def test_variant_rows_are_separate_and_totals_checked(monkeypatch):
    model = FakeVision(pieces=[piece_values("VAR-A",3), piece_values("VAR-B",3)])
    doc = processed(monkeypatch, model=model)
    assert doc["status"] == "ready" and len(store.plan_rows()) == 2
    assert sum(p["values"]["quantity_required"] for p in doc["pieces"]) == 6
    bad = processed(monkeypatch, suffix="bad-total", model=FakeVision(pieces=[piece_values(quantity=26)]))
    assert bad["status"] == "review"
    assert any("índice indica 6" in i["message"] for p in bad["pieces"] for i in p["issues"])


def test_missing_or_out_of_range_evidence_never_auto_publishes(monkeypatch):
    values = piece_values()
    values["evidence"].pop("quantity_required")
    values["evidence"]["length_mm"]["page"] = 99
    doc = processed(monkeypatch, model=FakeVision(pieces=[values]))
    assert doc["status"] == "review" and store.plan_rows() == []
    codes = {i["code"] for i in doc["pieces"][0]["issues"]}
    assert "evidence_quantity_required" in codes and "invalid_page_length_mm" in codes


def test_replacement_characters_in_model_text_block_export():
    values = piece_values()
    values["notes"] = "Designa��o ilegível"
    with pytest.raises(ValueError, match="substituição Unicode"):
        Piece.model_validate(values)
    issues, _match = cpis.assess(
        {"values": values, "raw": values, "reviewed": {}, "machine_group": "Serrote"},
        context(), 2)
    damaged = next(issue for issue in issues if issue["code"] == "damaged_text_encoding")
    assert damaged["blocking"] is True and damaged["damaged_fields"] == ["notes"]


def test_non_actionable_missing_index_quantity_and_catalogue_dimensions_are_not_reviews():
    values = piece_values(material_type="Perfil H", profile="HEB320", outer_diameter_mm=None,
        thickness_mm=None, warnings=[
            "QTD. A FABRICAR vazia no índice; quantidade 26 lida só do croqui.",
            "Largura/altura/espessura da secção HEB não cotadas; não se usaram valores de catálogo.",
            "A revisão do cartucho está ilegível.",
        ])
    ctx = context()
    ctx.update(material_catalog=[{"row": 62, "family": "Perfil H", "profile": "HEB320B",
                                  "area": 16100, "rule": "Padrão"}],
               material_catalog_version="catalogue-1")
    issues, _match = cpis.assess(
        {"values": values, "raw": values, "reviewed": {}, "machine_group": "Vanguard"},
        ctx, 2)
    reading = [issue["message"] for issue in issues if issue["code"].startswith("reading_")]
    assert reading == ["A revisão do cartucho está ilegível."]


def test_different_end_cut_angles_require_an_explicit_reading_confirmation():
    values = piece_values(notes="Cortes das extremidades a 68° e 98°. Chanfro 4 × 45°.")
    piece = {"values": values, "raw": values, "reviewed": {}, "machine_group": "Vanguard"}

    issues, _match = cpis.assess(piece, context(), 2)

    assert any(item["code"] == "conflicting_cut_angles" and item["field"] == "notes" for item in issues)
    piece["reviewed"] = {"decisions": {"notes": {
        "reading": cpis.reading_decision_fingerprint("notes", values, values)}}}
    issues, _match = cpis.assess(piece, context(), 2)
    assert not any(item["code"] == "conflicting_cut_angles" for item in issues)


def test_cpis_closed_and_geometry_after_production_block_export(monkeypatch):
    doc = processed(monkeypatch, ctx=context(status="Fechada"))
    assert doc["pieces"][0]["state"] == "blocked" and not store.plan_rows()
    with pytest.raises(DossierError): macro.export_rows([doc["id"]])
    doc = processed(monkeypatch, suffix="revision", ctx=context(rows=[plan_row(completed=2,length=1100)]))
    assert any(i["code"] == "changed_after_production" for i in doc["pieces"][0]["issues"])
    assert not store.plan_rows()


def test_closed_macro_row_blocks_an_otherwise_matching_need():
    row=plan_row();row['closed_x']=True
    values=piece_values()
    issues,match=cpis.assess({'values':values,'raw':values,'reviewed':{},'machine_group':'Serrote'},
                             context(rows=[row]),2)
    assert match['closed_x'] is True
    assert any(i['code']=='plan_row_closed' and i['blocking'] for i in issues)


def test_closure_is_rechecked_before_csv_export(monkeypatch):
    doc = processed(monkeypatch)
    assert store.plan_rows()
    monkeypatch.setattr(cpis, "read_context", lambda _: context(status="Fechada"))
    with TestClient(app) as client:
        response = client.get('/planeamento/api/saida/csv', params={"document":doc["id"]})
        assert response.status_code == 409


def test_source_freshness_distinguishes_checked_unchanged_changed_and_missing(tmp_path):
    source=tmp_path/'Met2_Plan_Perfis.xlsm';source.write_bytes(b'catalogue-a')
    imported={'source_path':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    first=cpis._source_freshness(imported)
    assert first['available'] and first['matches_import'] and first['checked_at']
    source.write_bytes(b'catalogue-b')
    changed=cpis._source_freshness(imported)
    assert changed['available'] and not changed['matches_import']
    source.unlink()
    missing=cpis._source_freshness(imported)
    assert not missing['available'] and not missing['matches_import']
    assert not store.plan_rows()


def test_correction_has_cas_keeps_raw_and_registers_without_full_form(monkeypatch):
    values = piece_values(quantity=None)
    doc = processed(monkeypatch, model=FakeVision(pieces=[values]))
    piece = doc["pieces"][0]
    payload = {"revision":1,"values":{"quantity_required":6},"confirm_reading":True,
               "actor":"Operador","reason":"6 no cartucho da página 2"}
    with TestClient(app) as client:
        url=f'/planeamento/api/dossies/{doc["id"]}/linhas/{piece["id"]}'
        updated=client.patch(url,json=payload)
        assert updated.status_code == 200 and updated.json()["status"] == "ready"
        assert client.patch(url,json=payload).status_code == 409
    after=store.get_document(doc["id"])
    assert after["pieces"][0]["raw"]["quantity_required"] is None
    assert after["pieces"][0]["values"]["quantity_required"] == 6
    assert after["events"][0]["action"] == "reviewed"


def test_duplicate_documents_share_need_but_revisions_need_explicit_choice(monkeypatch):
    first=processed(monkeypatch)
    second=processed(monkeypatch,suffix="identical-work")
    assert second["pieces"][0]["state"] == "duplicate" and len(store.plan_rows()) == 1
    revised=processed(monkeypatch,suffix="changed",model=FakeVision(pieces=[piece_values(length=1300)]))
    piece=revised["pieces"][0]
    assert any(i["code"]=="revision_conflict" for i in piece["issues"])
    result=pipeline.review_piece(revised["id"],piece["id"],{"revision":1,"values":{},"actor":"Operador",
        "reason":"Nova revisão do desenho confirmada", "replace_revision":True})
    assert result["status"] == "ready" and len(store.plan_rows()) == 1
    assert store.plan_rows()[0]["values"]["length_mm"] == 1300
    assert store.get_document(first["id"])["pieces"][0]["state"] == "superseded"


def test_old_duplicate_cannot_replace_later_revision_implicitly(monkeypatch):
    first=processed(monkeypatch)
    duplicate=processed(monkeypatch,suffix="same-again")
    revised=processed(monkeypatch,suffix="changed",model=FakeVision(pieces=[piece_values(length=1300)]))
    p=revised["pieces"][0]
    pipeline.review_piece(revised["id"],p["id"],{"revision":1,"values":{},"actor":"Op","reason":"Rev 2", "replace_revision":True})
    with pytest.raises(DossierError): macro.export_rows([duplicate["id"]])
    assert store.plan_rows()[0]["values"]["length_mm"] == 1300


def test_dual_distribution_does_not_double_piece_quantity(monkeypatch):
    routes=[{"reference":"REF-A","machine_group":group,"quantity":6,"evidence":"X"} for group in ("Vanguard","Serrote")]
    doc=processed(monkeypatch,model=FakeVision(routes=routes))
    assert doc["status"] == "review" and not store.plan_rows()
    assert all(any(i["code"]=="dual_distribution" for i in p["issues"]) for p in doc["pieces"])


def test_exclude_duplicate_retains_raw_and_releases_single_quantity(monkeypatch):
    doc=processed(monkeypatch,model=FakeVision(pieces=[piece_values(quantity=3),piece_values(quantity=3)]))
    assert not store.plan_rows()
    piece=doc["pieces"][0]
    result=pipeline.exclude_piece(doc["id"],piece["id"],{"revision":1,"actor":"Op","reason":"Duplicação de leitura"})
    assert sum(p["state"]=="excluded" for p in result["pieces"]) == 1
    assert not store.plan_rows()  # Excluir uma linha não pode perder metade do total do índice.
    remaining = next(p for p in result["pieces"] if p["state"] != "excluded")
    assert any(i["code"] == "route_total" for i in remaining["issues"])
    pipeline.review_piece(doc["id"], remaining["id"], {"revision":1, "values":{"quantity_required":6},
        "actor":"Op", "reason":"Total 6 no desenho", "confirm_reading":True})
    assert len(store.plan_rows()) == 1 and store.plan_rows()[0]["values"]["quantity_required"] == 6
    assert result["pieces"][0]["raw"]


def test_restart_archives_previous_reading_with_automatic_audit_text(monkeypatch):
    doc=processed(monkeypatch)
    store.restart(doc["id"],api_ready=False,actor="",reason="")
    result=store.get_document(doc["id"])
    assert result["status"]=="waiting_api" and not result["pieces"] and not store.plan_rows()
    archived=next(e for e in result["events"] if e["action"]=="reading_restarted")
    assert archived["data"]["previous_pieces"][0]["raw"]["quantity_required"] == 6
    assert archived["actor"]=="Interface de planeamento" and archived["data"]["reason"]


def test_document_lock_is_reentrant_and_rejects_concurrent_edit():
    uid=store.ingest(pdf_bytes(),"OF265931.pdf")["id"]
    result=[]
    def other():
        try:
            with store.document_lock(uid): result.append("unexpected")
        except DossierError as e: result.append(e.status)
    with store.document_lock(uid):
        with store.document_lock(uid):
            t=threading.Thread(target=other);t.start();t.join(2)
    assert result==[409]


def test_reference_normalization_preserves_distinct_physical_refs():
    assert ref_key('pr.4') == 'PR4' and ref_key('pr.5') != ref_key('pr.4')
    assert ref_key('CI23JJ01_REV.A.dwg') == ref_key('CI23JJ01')
    assert ref_key('CI25J001') != ref_key('CI25J003')


def test_dimensions_and_operation_flags_are_compared_with_existing_inputs():
    row=plan_row(completed=0);row['material_type']='Tubo redondo'
    row['row_data'].update({'Ø Externo [mm]':114,'Espessura (t) [mm]':3,'Aborc.':'-'})
    piece={'values':piece_values(outer_diameter_mm=114,thickness_mm=4,abocardar='X'),
           'machine_group':'Serrote'}
    issues,match=cpis.assess(piece,context(rows=[row]),2)
    assert {i['field'] for i in issues}=={'thickness_mm','abocardar'}
    assert match['kind']=='changed'
    row['row_data']['Ser.']=2
    issues,_=cpis.assess(piece,context(rows=[row]),2)
    assert any(i['code']=='changed_after_production' for i in issues)


def test_concrete_machine_is_preserved_only_when_compatible_with_the_pdf_route():
    row=plan_row();row['row_data']['Máquina Corte']='Serrote MEBA IS381 Pav 3'
    piece={'values':piece_values(),'raw':piece_values(),'reviewed':{},'machine_group':'Serrote'}
    issues,match=cpis.assess(piece,context(rows=[row]),2)
    assert not any(i['code']=='machine_conflict' for i in issues)
    assert match['assigned_machine']=='Serrote MEBA IS381 Pav 3' and match['machine_update'] is None
    row['row_data']['Máquina Corte']='Corte Tubo Laser'
    issues,_=cpis.assess(piece,context(rows=[row]),2)
    assert any(i['code']=='machine_conflict' and i['blocking'] for i in issues)


def test_reconciliation_uses_macro_inputs_instead_of_computed_profile_cache():
    row=plan_row(ref='pr.3',quantity=999,profile='80',length=999)
    row['material_type']='Varão redondo'
    row['row_data'].update({'Tipo de Material':'Varão redondo','Designação Perfil':None,
        'QTD [un,]':52,'Ø Externo [mm]':80,'Comp, [mm]':539,'Qual.':'S355J2'})
    values=piece_values(ref='pr.3',quantity=52,length=539,profile='R80',
        material_type='Varão redondo',grade='S355J2')
    issues,match=cpis.assess({'values':values,'raw':values,'reviewed':{},'machine_group':'Serrote'},
                             context(of='OF265941',rows=[row]),17)
    assert not any(i['code'].startswith('different_') for i in issues)
    assert match['differences']==[{'field':'profile','pdf':'R80','resolved':'R80',
        'plan':None,'kind':'fill'}]
    assert match['effective_values']['outer_diameter_mm']==80


def test_material_resolution_keeps_literal_and_uses_unique_catalogue_alias():
    values=piece_values(profile='UPN80',material_type='Perfil U')
    ctx=context();ctx.update(material_catalog=[
        {'family':'Perfil U','profile':'UPN80x45','area':1100,'rule':'Padrão'},
        {'family':'Perfil H','profile':'HEB320B','area':16100,'rule':'Padrão'}],
        material_catalog_version='catalogue-1')
    resolved=material.resolve(values,ctx)
    assert resolved['raw']['profile']=='UPN80'
    assert resolved['export']['profile']=='UPN80x45' and resolved['status']=='catalog_alias'
    assert values['profile']=='UPN80'

    generic={**values,'material_type':'Viga','profile':'HEB320'}
    h_context=context();h_context.update(material_catalog=[
        {'row':62,'family':'Perfil H','profile':'HEB320B','area':16100,'rule':'Padrão'}],
        material_catalog_version='catalogue-1')
    h_resolved=material.resolve(generic,h_context)
    assert h_resolved['raw']['material_type']=='Viga'
    assert h_resolved['export']=={'material_type':'Perfil H','profile':'HEB320B'}
    assert h_resolved['status']=='catalog_alias'


def test_family_geometry_is_derived_with_provenance_and_invalid_wall_is_blocked():
    piece={'values':piece_values(), 'raw':piece_values(), 'reviewed':{}}
    issues,match=cpis.assess(piece,context(),2)
    assert not any(i['code'].startswith('missing_') for i in issues)
    assert match['effective_values']['outer_diameter_mm']==114
    assert match['effective_values']['thickness_mm']==3
    bad=piece_values(profile='10x6');bad['evidence']['profile']={'page':2,'text':'Ø10 x 6'}
    issues,_=cpis.assess({'values':bad,'raw':bad,'reviewed':{}},context(),2)
    assert any(i['code']=='invalid_wall_thickness' and i['blocking'] for i in issues)


def test_difference_confirmation_is_invalidated_when_plan_baseline_changes():
    values=piece_values(quantity=10);row=plan_row(quantity=6)
    decision=difference_decision_fingerprint('quantity_required',values,6,row['source_line_id'])
    piece={'values':values,'raw':values,'reviewed':{'decisions':{'quantity_required':{'difference':decision}}}}
    issues,_=cpis.assess(piece,context(rows=[row]),2)
    assert not any(i['code']=='different_quantity_required' for i in issues)
    changed=plan_row(quantity=7)
    issues,_=cpis.assess(piece,context(rows=[changed]),2)
    assert any(i['code']=='different_quantity_required' for i in issues)


def test_physical_need_identity_ignores_route_but_supports_explicit_discriminator():
    values=piece_values()
    assert need_key('OF265931','Vanguard',values)==need_key('OF265931','Serrote',values)
    assert need_key('OF265931','Serrote',values)!=need_key('OF265931','Serrote',{
        **values,'identity_discriminator':'variante B'})


def test_work_items_are_used_without_a_matrix_and_cross_page_duplicates_are_coalesced():
    inventory=Inventory.model_validate({'pages':[
        {'page':1,'kind':'cut_list','work_items':[{'source_type':'cut_list','source_id':'linha 1',
            'reference':'5877T5102','quantity':42,'evidence':'linha preenchida: 42'}]},
        {'page':2,'kind':'drawing','references':['5877T5102'],'work_items':[{'source_type':'drawing',
            'source_id':'A FABRICAR','reference':'5877T5102','quantity':42,
            'evidence':'A FABRICAR 42'}]},
    ]}).model_dump()['pages']
    selections=pipeline.collect_selections(inventory)
    assert len(selections)==1 and selections[0]['machine_group']=='Por atribuir'
    assert selections[0]['quantity']==42 and selections[0]['related_item_pages']==[2]
    assert len(selections[0]['selection']['related'])==1


def test_variable_inventory_reference_shape_is_normalized_before_persistence():
    result=pipeline._normalize_inventory({'pages':[{'page':2,'kind':'drawing','orientation':'upright',
        'of':'OF266229/33','references':[{'reference':'5877T5102','aliases':['5877T5102.dwg']}],
        'work_items':[{'source_id':'5877T5102','reference':'5877T5102',
                       'aliases':['U50x200'],'quantity':42}]}]})
    page=result['pages'][0]
    assert page['production_order']=='OF266229/33'
    assert page['references']==['5877T5102','5877T5102.dwg']
    assert page['work_items'][0]['source_type']=='drawing'
    assert page['work_items'][0]['selection']=='explicit' and '42' in page['work_items'][0]['evidence']


def test_distribution_matrix_remains_authoritative_over_unrelated_work_items():
    inventory=Inventory.model_validate({'pages':[{'page':1,'kind':'distribution',
        'routes':[{'reference':'REF-A','machine_group':'Vanguard','quantity':6,'evidence':'X'}],
        'work_items':[{'source_type':'table','source_id':'linha B','reference':'REF-B',
                       'quantity':99,'evidence':'preenchida'}]}]}).model_dump()['pages']
    selections=pipeline.collect_selections(inventory)
    assert [(item['reference'],item['machine_group']) for item in selections]==[('REF-A','Vanguard')]


def test_cut_list_without_matrix_is_extracted_and_completed_from_same_of_plan():
    values=piece_values(ref='CI.77/12.A4.002',quantity=5,length=170,page=1,
        drawing_ref='CI.77/12.A4.002',material_type='Tubo redondo',profile='Ø 2″ S.L',grade='S235JR')
    row=plan_row(ref='CI7712A4002',quantity=5,profile='60.3x2.9',length=170)
    row.update(material_type='Tubo redondo',profile_type='60.3x2.9',closed_x=True,excel_row=1556,
               source_line_id='test-s1:30729')
    row['row_data'].update({'Tipo de Material':'Tubo redondo','Designação Perfil':None,
        'QTD [un,]':5,'Comp, [mm]':170,'Qual.':'S235JR','Ø Externo [mm]':60.3,
        'Espessura (t) [mm]':2.9,'Máquina Corte':'Serrote Fita Thomas IS639 Pav.1','Ser.':5})
    ctx=context(of='OF260221',rows=[row],status='Fechada')
    model=FlexibleVision([
        {'page':1,'kind':'cut_list','production_order':'OF260221/35','sales_orders':['OV2600186'],
         'work_items':[{'source_type':'cut_list','source_id':'primeira linha preenchida',
                        'reference':'CI.77/12.A4.002','aliases':['CI77H002_REV.A.dwg'],
                        'quantity':5,'evidence':'linha preenchida, qtd 5, 170 mm'}]},
        {'page':2,'kind':'drawing','orientation':'clockwise','production_order':'OF260221/35',
         'references':['CI.77/12.A4.002','CI77H002_REV.A.dwg']},
    ],[values])
    uid=store.ingest(pdf_bytes(),'OF260221.pdf')['id']
    pipeline.process_document(uid,provider=model,context_reader=lambda _of:copy.deepcopy(ctx))
    doc=store.get_document(uid);piece=doc['pieces'][0]
    assert doc['production_order']=='OF260221' and not any(i['code']=='of_qualifier' for i in doc['issues'])
    assert piece['selection']['source']=='cut_list' and piece['raw']['profile']=='Ø 2″ S.L'
    assert piece['match']['effective_values']['profile']=='60.3x2.9'
    assert piece['match']['effective_values']['outer_diameter_mm']==60.3
    assert piece['match']['effective_values']['thickness_mm']==2.9
    assert piece['match']['field_sources']['outer_diameter_mm']['excel_row']==1556
    assert piece['match']['machine_group']=='Serrote'
    assert any(i['code']=='of_closed' for i in piece['issues'])


def test_reconcile_removes_legacy_coherent_of_qualifier_and_keeps_literal_identifier(monkeypatch):
    doc=processed(monkeypatch,suffix='legacy-qualifier')
    inventory=store.checkpoints(doc['id'],'inventory')
    cover={**inventory['1'],'production_order':'OF265931/26'}
    store.checkpoint(doc['id'],'inventory','1',cover,
        input_fingerprint=doc['model']['processing_signature'])
    store.update_document(doc['id'],issues=[cpis.issue('of_qualifier',
        'Confirma o significado do sufixo.',blocking=True,
        raw_identifier='OF265931/26',candidate='OF265931')])

    pipeline.reconcile(doc['id'])

    current=store.get_document(doc['id'])
    assert not any(problem['code']=='of_qualifier' for problem in current['issues'])
    assert 'OF265931/26' in current['context']['document_identifiers']['production_orders']


def test_isolated_drawing_resolves_u_profile_by_section_and_keeps_machine_unresolved():
    values=piece_values(ref='5877T5102',quantity=42,length=200,page=2,
        drawing_ref='5877T5102',material_type='Perfil U',profile='U50x200',grade='S355J2',
        width_mm=38,height_mm=50,operations=['2 furos Ø14','recorte'])
    ctx=context(of='OF266229');ctx.update(material_catalog=[
        {'row':232,'family':'Perfil U','profile':'UPN50x25','area':1,'rule':'Padrão'},
        {'row':233,'family':'Perfil U','profile':'UPN50x38','area':2,'rule':'Padrão'}],
        material_catalog_version='catalog-2',sales_order='OV2607678',reference_history=[
        {'production_order_no':'OF264696','excel_row':5478,'component_ref':'5877T5102',
         'profile_type':'UPN50x25','length_mm':200,'row_data':{'Designação Perfil':'UPN50x25',
         'Máquina Corte':'Serrote Disco pav 1'}},
        {'production_order_no':'OF264887','excel_row':6956,'component_ref':'5877T5102',
         'profile_type':'UPN50x38','length_mm':200,'row_data':{'Designação Perfil':'UPN50x38'}},
    ])
    model=FlexibleVision([
        {'page':1,'kind':'other','production_order':'OF266229/33',
         'sales_orders':['OV2607678','OV2607675','OV2607587','OV2607578','OV2607544']},
        {'page':2,'kind':'drawing','production_order':'OF266229/33','references':['5877T5102'],
         'work_items':[{'source_type':'drawing','source_id':'A FABRICAR','reference':'5877T5102',
                        'quantity':42,'evidence':'A FABRICAR 42'}]},
    ],[values])
    uid=store.ingest(pdf_bytes(),'OF266229.pdf')['id']
    pipeline.process_document(uid,provider=model,context_reader=lambda _of:copy.deepcopy(ctx))
    doc=store.get_document(uid);piece=doc['pieces'][0]
    assert not any(i['code']=='ov_disagreement' for i in piece['issues'])
    assert piece['match']['effective_values']['profile']=='UPN50x38'
    assert piece['match']['field_sources']['profile']['source']=='catalog'
    assert piece['match']['machine_resolution']['suggestions']==[]
    assert any(i['code']=='machine_unresolved' and i['blocking'] for i in piece['issues'])
    assert piece['state']=='blocked' and piece['selection']['source']=='drawing'


def test_optional_actor_reason_and_machine_choice_are_audited_by_the_interface(monkeypatch):
    doc=processed(monkeypatch);piece=doc['pieces'][0]
    with TestClient(app) as client:
        response=client.patch(f'/planeamento/api/dossies/{doc["id"]}/linhas/{piece["id"]}',
            json={'revision':piece['revision'],'values':{},'machine_group':'Serrote','confirm_reading':True})
        assert response.status_code==200
    event=store.get_document(doc['id'])['events'][0]
    assert event['actor']=='Interface de planeamento' and event['data']['reason']


def test_reread_exclude_and_document_review_accept_no_actor_or_reason(monkeypatch):
    page_doc=processed(monkeypatch,suffix='page-reread')
    piece_doc=processed(monkeypatch,suffix='piece-reread')
    exclude_doc=processed(monkeypatch,suffix='exclude')
    review_doc=processed(monkeypatch,suffix='document-review')
    with TestClient(app) as client:
        assert client.post(f'/planeamento/api/dossies/{page_doc["id"]}/paginas/2/reler',json={}).status_code==200
        piece=piece_doc['pieces'][0]
        assert client.post(f'/planeamento/api/dossies/{piece_doc["id"]}/linhas/{piece["id"]}/reler',json={}).status_code==200
        piece=exclude_doc['pieces'][0]
        assert client.post(f'/planeamento/api/dossies/{exclude_doc["id"]}/linhas/{piece["id"]}/excluir',
                           json={'revision':piece['revision']}).status_code==200
        assert client.post(f'/planeamento/api/dossies/{review_doc["id"]}/conferir',json={
            'revision':review_doc['revision'],'production_order':'OF265931','confirmed_codes':[]}).status_code==200
        assert client.post(f'/planeamento/api/dossies/{review_doc["id"]}/reler',json={}).status_code==200
    for doc in (page_doc,piece_doc,exclude_doc,review_doc):
        assert store.get_document(doc['id'])['events'][0]['actor']=='Interface de planeamento'


def test_compound_order_identifier_is_kept_without_repeated_confirmation_when_coherent():
    document={'filename':'OF265941.pdf'}
    inventory=[{'production_order':'OF265941/33'}]
    order,issues=pipeline.resolve_order(document,inventory)
    assert order=='OF265941' and issues==[]


def test_single_page_output_limit_gets_one_compact_retry(monkeypatch):
    class OnceLimited(FakeVision):
        def __init__(self):super().__init__(routes=[]);self.limited=False
        def request(self,prompt,schema,images=()):
            if schema is Inventory and not self.limited:
                self.limited=True;self.calls.append((schema.__name__,[n for n,_ in images]))
                raise DossierError('limite',502,kind='model_output_limit')
            return super().request(prompt,schema,images)
    uid=store.ingest(pdf_bytes(pages=1),'OF265931.pdf')['id']
    monkeypatch.setattr(cpis,'read_context',lambda _:context())
    model=OnceLimited();pipeline.process_document(uid,provider=model)
    assert [call for call in model.calls if call[0]=='Inventory']==[('Inventory',[1]),('Inventory',[1])]


def test_single_page_output_limit_stops_after_the_bounded_retry(monkeypatch):
    class AlwaysLimited(FakeVision):
        def __init__(self):super().__init__(routes=[])
        def request(self,prompt,schema,images=()):
            self.calls.append((schema.__name__,[n for n,_ in images]))
            raise DossierError('limite',502,kind='model_output_limit')
    uid=store.ingest(pdf_bytes(pages=1),'OF265931.pdf')['id']
    model=AlwaysLimited()
    with pytest.raises(DossierError,match='Página 1'):
        pipeline.process_document(uid,provider=model,context_reader=lambda _:context())
    assert model.calls==[('Inventory',[1]),('Inventory',[1])]
    assert store.checkpoints(uid,'inventory')=={}
    with store.connect() as conn:
        assert conn.execute('SELECT status FROM processing_runs WHERE document_id=?',(uid,)).fetchone()[0]=='failed'


def test_provider_attempt_metadata_is_persisted_without_response_content(monkeypatch):
    uid=store.ingest(pdf_bytes(pages=1),'OF265931.pdf')['id']
    monkeypatch.setattr(cpis,'read_context',lambda _:context())
    config={'base_url':'https://model.example/v1','model':'vision','api_key':'private',
            'api_format':'responses','timeout_s':2,'max_tokens':2000}
    def transport(_request):
        return httpx.Response(200,headers={'x-request-id':'req-safe-1'},json={'id':'response-safe-1',
            'status':'completed','usage':{'input_tokens':100,'output_tokens':20,
                'output_tokens_details':{'reasoning_tokens':7}},'output':[{'type':'message','content':[
                {'type':'output_text','text':'{"pages":[{"page":1,"kind":"other","production_order":"OF265931","sales_order":"OV2607672"}]}'}]}]})
    engine=provider.VisionProvider(config,httpx.MockTransport(transport))
    pipeline.process_document(uid,provider=engine)
    attempts=store.get_document(uid)['attempts']
    assert attempts[0]['status']=='completed' and attempts[0]['metadata']['request_id']=='response-safe-1'
    assert attempts[0]['metadata']['usage']['output_tokens_details.reasoning_tokens']==7
    assert 'pages' not in json.dumps(attempts[0]) and 'private' not in json.dumps(attempts[0])


def test_selected_page_reread_keeps_other_inventory_and_archives_dependent_rows(monkeypatch):
    doc=processed(monkeypatch);uid=doc['id']
    store.reread_page(uid,2,api_ready=False,actor='Operador',reason='Número ilegível')
    after=store.get_document(uid)
    assert after['status']=='waiting_api' and after['pieces']==[]
    assert set(store.checkpoints(uid,'inventory'))=={'1'}
    assert store.checkpoints(uid,'links')=={} and store.checkpoints(uid,'extractions')=={}
    assert after['events'][0]['action']=='page_reread_requested'


def test_selected_piece_reread_preserves_unrelated_routes(monkeypatch):
    model=FakeVision(pieces=[piece_values('VAR-A',3),piece_values('VAR-B',3)])
    doc=processed(monkeypatch,model=model);target=doc['pieces'][0]
    store.reread_piece(doc['id'],target['id'],api_ready=False,actor='Operador',reason='Rever variantes')
    after=store.get_document(doc['id'])
    assert after['pieces']==[]  # ambas as variantes pertencem à mesma leitura do desenho
    assert store.checkpoints(doc['id'],'inventory') and store.checkpoints(doc['id'],'links')
    assert store.checkpoints(doc['id'],'extractions')=={}
    assert after['events'][0]['action']=='piece_reread_requested'


def test_changed_processing_contract_archives_old_extraction(monkeypatch):
    first=FakeVision();first.config={'base_url':'https://one.example','model':'first','api_format':'responses'}
    doc=processed(monkeypatch,model=first)
    second=FakeVision();second.config={'base_url':'https://two.example','model':'second','api_format':'responses'}
    pipeline.process_document(doc['id'],provider=second)
    after=store.get_document(doc['id'])
    assert after['model']['model']=='second' and len(after['pieces'])==1
    assert any(event['action']=='incompatible_processing_contract' for event in after['events'])


def test_changed_processing_contract_archives_checkpoints_from_a_failed_run():
    uid=store.ingest(pdf_bytes(pages=1),'OF265931.pdf')['id']
    store.checkpoint(uid,'inventory',1,{'page':1},run_id='old-run',input_fingerprint='old-signature')
    store.update_document(uid,model={'processing_signature':'old-signature'})
    store.prepare_run(uid,'new-signature')
    assert store.checkpoints(uid,'inventory')=={}
    with store.connect() as conn:
        history=conn.execute("SELECT input_fingerprint FROM checkpoint_history WHERE document_id=?",(uid,)).fetchall()
    assert [row[0] for row in history]==['old-signature']
    assert store.get_document(uid)['events'][0]['action']=='incompatible_processing_contract'


def test_export_preview_is_persisted_and_returns_bound_fingerprint(monkeypatch):
    monkeypatch.setattr(dossier_routes.planning_hub, 'require_operational_orders', lambda *_args, **_kwargs: 'cpis-test')
    uid=store.ingest(pdf_bytes(),'OF265931.pdf')['id']
    monkeypatch.setattr(macro,'export_rows',lambda _ids=None:[{'document_id':uid}])
    summary={'added':1,'updated':0,'unchanged':0,'cells':[], 'source_sha256':'abc', 'cpis_version':'cpis-test'}
    monkeypatch.setattr(macro,'preview_macro',lambda _rows:dict(summary))
    with TestClient(app) as client:
        response=client.get('/planeamento/api/saida-proposta',params={'document':uid})
    assert response.status_code==200 and response.json()['proposal_fingerprint']==macro.fingerprint(summary)
    assert store.get_document(uid)['latest_proposal']['summary']['proposal_fingerprint']==macro.fingerprint(summary)


def test_xlsm_download_rejects_a_proposal_that_changed_after_preview(monkeypatch):
    monkeypatch.setattr(dossier_routes.planning_hub, 'require_operational_orders', lambda *_args, **_kwargs: 'cpis-test')
    uid=store.ingest(pdf_bytes(),'OF265931.pdf')['id']
    rows=[{'document_id':uid}]
    preview={'added':1,'updated':0,'unchanged':0,'cells':[{'row':8,'column':'AH','after':6}],
             'source_sha256':'abc'}
    changed={**preview,'cells':[{'row':8,'column':'AH','after':7}]}
    monkeypatch.setattr(macro,'export_rows',lambda _ids=None:rows)
    monkeypatch.setattr(macro,'preview_macro',lambda _rows:dict(preview))
    monkeypatch.setattr(macro,'fill_macro',lambda _rows:(b'xlsm',dict(changed)))
    with TestClient(app) as client:
        assert client.get('/planeamento/api/saida/xlsm',params={'document':uid}).status_code==409
        proposal=client.get('/planeamento/api/saida-proposta',params={'document':uid}).json()['proposal_fingerprint']
        response=client.get('/planeamento/api/saida/xlsm',params={'document':uid,'proposal':proposal})
    assert response.status_code==409 and 'proposta mudou' in response.json()['error']
    assert store.get_document(uid)['latest_export'] is None


def test_xlsm_download_accepts_the_latest_unchanged_recorded_proposal(monkeypatch):
    monkeypatch.setattr(dossier_routes.planning_hub, 'require_operational_orders', lambda *_args, **_kwargs: 'cpis-test')
    uid=store.ingest(pdf_bytes(),'OF265931.pdf')['id']
    rows=[{'document_id':uid}]
    summary={'added':1,'updated':0,'unchanged':0,'cells':[], 'source_sha256':'abc', 'cpis_version':'cpis-test'}
    monkeypatch.setattr(macro,'export_rows',lambda _ids=None:rows)
    monkeypatch.setattr(macro,'preview_macro',lambda _rows:dict(summary))
    monkeypatch.setattr(macro,'fill_macro',lambda _rows:(b'xlsm',dict(summary)))
    with TestClient(app) as client:
        proposal=client.get('/planeamento/api/saida-proposta',params={'document':uid}).json()['proposal_fingerprint']
        response=client.get('/planeamento/api/saida/xlsm',params={'document':uid,'proposal':proposal})
    assert response.status_code==200 and response.content==b'xlsm'
    assert store.get_document(uid)['latest_export']['summary']==summary


@pytest.mark.parametrize('route', ['saida-proposta', 'saida/xlsm', 'saida/csv'])
def test_pdf_output_requires_confirmed_cpis(monkeypatch, route):
    uid = store.ingest(pdf_bytes(), 'OF265931.pdf')['id']
    monkeypatch.setattr(macro, 'export_rows', lambda _ids=None: [{'document_id': uid}])
    def unavailable(*_args, **_kwargs):
        raise dossier_routes.planning.PlanningError('CPIS sem confirmação recente', 409)
    monkeypatch.setattr(dossier_routes.planning_hub, 'require_operational_orders', unavailable)
    def forbidden(*_args):
        pytest.fail('A saída não pode ser gerada sem confirmação CPIS')
    monkeypatch.setattr(macro, 'preview_macro', forbidden)
    monkeypatch.setattr(macro, 'fill_macro', forbidden)
    with TestClient(app) as client:
        result = client.get('/planeamento/api/' + route, params={'document': uid})
    assert result.status_code == 409 and 'CPIS' in result.json()['error']
    assert store.get_document(uid)['latest_export'] is None


def test_pdf_download_rejects_changed_cpis_version(monkeypatch):
    uid = store.ingest(pdf_bytes(), 'OF265931.pdf')['id']
    monkeypatch.setattr(macro, 'export_rows', lambda _ids=None: [{'document_id': uid}])
    summary = {'added': 1, 'updated': 0, 'unchanged': 0, 'cells': [], 'source_sha256': 'abc'}
    monkeypatch.setattr(macro, 'preview_macro', lambda _rows: dict(summary))
    monkeypatch.setattr(macro, 'fill_macro', lambda _rows: (b'xlsm', dict(summary)))
    versions = iter(['cpis-v1', 'cpis-v2'])
    monkeypatch.setattr(dossier_routes.planning_hub, 'require_operational_orders', lambda *_args, **_kwargs: next(versions))
    with TestClient(app) as client:
        proposal = client.get('/planeamento/api/saida-proposta', params={'document': uid}).json()['proposal_fingerprint']
        result = client.get('/planeamento/api/saida/xlsm', params={'document': uid, 'proposal': proposal})
    assert result.status_code == 409
    assert store.get_document(uid)['latest_export'] is None


def test_connector_negotiates_legacy_token_parameter_once():
    config={'base_url':'https://model.example/v1','model':'vision','api_key':'private',
            'api_format':'chat_completions','timeout_s':2,'max_tokens':2000}
    calls=[]
    def transport(request):
        body=json.loads(request.content);calls.append(body)
        if 'max_completion_tokens' in body:
            return httpx.Response(400,json={'error':{'param':'max_completion_tokens','message':'Unsupported parameter'}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"pieces":[]}'}}]})
    result=provider.VisionProvider(config,transport=httpx.MockTransport(transport)).request('Read',Extraction)
    assert len(calls)==2 and calls[1]['max_tokens']==2000 and result['pieces']==[]


def test_inbox_ignores_unfinished_files_imports_stable_and_reports_invalid(tmp_path,monkeypatch):
    incoming=tmp_path/'incoming';incoming.mkdir();monkeypatch.setenv('MES_DOSSIER_INBOX',str(incoming))
    path=incoming/'OF265931.pdf';path.write_bytes(pdf_bytes())
    inbox.scan();assert not store.list_documents()
    os.utime(path,(time.time()-20,time.time()-20))
    inbox.scan();assert len(store.list_documents())==1 and store.list_documents()[0]['status']=='waiting_api'
    inbox.scan();assert len(store.list_documents())==1
    invalid=incoming/'broken.pdf';invalid.write_bytes(b'not a PDF');os.utime(invalid,(time.time()-20,time.time()-20))
    inbox.scan();assert inbox.status()['errors'][0]['filename']=='broken.pdf'
    invalid.write_bytes(pdf_bytes(suffix='fixed'));os.utime(invalid,(time.time()-20,time.time()-20))
    inbox.scan();assert not inbox.status()['errors'] and len(store.list_documents())==2


def test_identical_pdf_with_different_order_filename_is_not_silently_dropped():
    data=pdf_bytes();store.ingest(data,'OF265931.pdf')
    with pytest.raises(DossierError,match='outra OF'):store.ingest(data,'OF265941.pdf')
    assert len(store.list_documents())==1


def test_windows_file_lock_backend_uses_one_fixed_byte(tmp_path,monkeypatch):
    import types
    from app.dossiers import locking
    calls=[]
    monkeypatch.setattr(locking,'os',types.SimpleNamespace(name='nt',SEEK_END=2))
    monkeypatch.setattr(locking,'msvcrt',types.SimpleNamespace(LK_NBLCK=1,LK_UNLCK=2,
        locking=lambda fd,mode,length:calls.append((mode,length))),raising=False)
    with (tmp_path/'windows.lock').open('a') as file:
        locking.acquire(file);assert file.tell()==0
        locking.release(file)
    assert calls==[(1,1),(2,1)]
