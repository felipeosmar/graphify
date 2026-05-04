#!/usr/bin/env python3
"""Smoke test: o modelo local devolve JSON válido no schema do graphify?

Roda isolado. NÃO importa graphify — só usa a API HTTP do Ollama.
Se este teste passar, a Fase 2 (patch no llm.py) tem alta chance de funcionar.

Uso:
    python local-extras/test_ollama_extraction.py
    python local-extras/test_ollama_extraction.py --model qwen2.5:14b-instruct-q4_K_M
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib import request

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"

SYSTEM_PROMPT = """\
You are a graphify semantic extraction agent. Extract a knowledge graph fragment from the files provided.
Output ONLY valid JSON — no explanation, no markdown fences, no preamble.

Rules:
- EXTRACTED: relationship explicit in source (import, call, citation, reference)
- INFERRED: reasonable inference (shared data structure, implied dependency)
- AMBIGUOUS: uncertain — flag for review, do not omit

Node ID format: lowercase, only [a-z0-9_], no dots or slashes.
Format: {stem}_{entity} where stem = filename without extension, entity = symbol name (both normalised).

Output exactly this schema:
{"nodes":[{"id":"stem_entity","label":"Human Readable Name","file_type":"code|document|paper|image|concept","source_file":"relative/path","source_location":null}],"edges":[{"source":"node_id","target":"node_id","relation":"calls|implements|references|cites|conceptually_related_to|shares_data_with|semantically_similar_to","confidence":"EXTRACTED|INFERRED|AMBIGUOUS","confidence_score":1.0,"source_file":"relative/path"}],"hyperedges":[]}
"""

SAMPLE_DOC = """\
=== docs/intro.md ===
# Auth flow

The `LoginService` validates credentials against `UserRepository` and emits a
`SessionCreated` event consumed by `AuditLogger`. Rate limiting is enforced by
`RateLimiter`, which shares the Redis pool with `SessionStore`.
"""


def call_ollama(model: str, system: str, user: str, timeout: int = 180) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "stream": False,
    }
    req = request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer ollama",
        },
    )
    t0 = time.time()
    with request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    elapsed = time.time() - t0
    return {
        "elapsed": elapsed,
        "content": payload["choices"][0]["message"]["content"],
        "usage": payload.get("usage", {}),
    }


def parse_extraction(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]
    return json.loads(s.strip())


def validate_shape(d: dict) -> list[str]:
    """Verifica o schema mínimo que graphify/validate.py espera."""
    errors = []
    for k in ("nodes", "edges"):
        if k not in d:
            errors.append(f"falta chave '{k}'")
        elif not isinstance(d[k], list):
            errors.append(f"'{k}' não é lista")
    for i, n in enumerate(d.get("nodes", [])):
        for k in ("id", "label"):
            if k not in n:
                errors.append(f"node[{i}] sem '{k}'")
    for i, e in enumerate(d.get("edges", [])):
        for k in ("source", "target", "relation", "confidence"):
            if k not in e:
                errors.append(f"edge[{i}] sem '{k}'")
        if e.get("confidence") not in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}:
            errors.append(f"edge[{i}].confidence inválido: {e.get('confidence')!r}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:7b-instruct-q4_K_M")
    args = ap.parse_args()

    print(f"[test] modelo: {args.model}")
    print(f"[test] enviando documento de ~{len(SAMPLE_DOC)} bytes")

    try:
        result = call_ollama(args.model, SYSTEM_PROMPT, SAMPLE_DOC)
    except Exception as e:
        print(f"[FAIL] erro chamando Ollama: {e}", file=sys.stderr)
        print("       cheque se 'ollama serve' está rodando.", file=sys.stderr)
        return 2

    print(f"[test] latência: {result['elapsed']:.1f}s")
    if result["usage"]:
        print(f"[test] tokens: {result['usage']}")

    raw = result["content"]
    print("\n--- output bruto ---\n" + raw[:1500] + ("\n..." if len(raw) > 1500 else ""))

    try:
        data = parse_extraction(raw)
    except json.JSONDecodeError as e:
        print(f"\n[FAIL] JSON inválido: {e}", file=sys.stderr)
        return 1

    errors = validate_shape(data)
    print(f"\n[test] nós: {len(data.get('nodes', []))}, edges: {len(data.get('edges', []))}")
    if errors:
        print("[FAIL] schema inválido:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("[OK] schema válido — modelo é candidato viável para a Fase 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
