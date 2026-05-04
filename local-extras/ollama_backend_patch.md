# Patch da Fase 2 — adicionar backend `ollama` em `graphify/llm.py`

> **Não aplicar ainda.** Este documento descreve o diff exato. Revisar com o usuário antes de editar.

## Mudança 1 — entrada em `BACKENDS`

**Arquivo:** `graphify/llm.py`
**Local:** logo após o bloco `"kimi": {...}` (linha ~60)

```python
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5:7b-instruct-q4_K_M",
        # Ollama aceita qualquer string como Authorization Bearer.
        # Mantemos uma env var só para encaixar no fluxo existente
        # (extract_files_direct exige env_key configurado).
        "env_key": "GRAPHIFY_OLLAMA_KEY",
        "pricing": {"input": 0.0, "output": 0.0},
        "temperature": 0,
    },
```

E setar antes de rodar:
```bash
export GRAPHIFY_OLLAMA_KEY=ollama   # qualquer string serve
```

## Mudança 2 — dispatch em `extract_files_direct`

**Arquivo:** `graphify/llm.py:180-208`
**Local atual:**

```python
    if backend == "claude":
        return _call_claude(key, mdl, user_msg)
    return _call_openai_compat(
        cfg["base_url"], key, mdl, user_msg, cfg["temperature"]
    )
```

**Alteração:** nenhuma. O `else` já cai no `_call_openai_compat`, que serve qualquer API OpenAI-compat — Ollama incluído. Ou seja, a Mudança 1 sozinha já habilita o backend.

## Mudança 3 (opcional) — `detect_backend` priorizar Ollama local

**Arquivo:** `graphify/llm.py:468`

A função atual provavelmente retorna o primeiro backend com `env_key` setado. Para que ferramentas que chamam `detect_backend()` peguem Ollama por padrão quando ele estiver disponível, considerar:

```python
def detect_backend() -> str | None:
    # Prioridade: local grátis > pago.
    # Ollama: detecta pela porta, não pela env var.
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=0.5)
        if os.environ.get("GRAPHIFY_OLLAMA_KEY"):
            return "ollama"
    except Exception:
        pass
    # ... resto da lógica original (claude, kimi)
```

**Cuidado:** mexer em `detect_backend` afeta o fluxo do skill quando ele consulta qual backend usar. Se preferir conservador, **pular a Mudança 3** e exigir `--backend ollama` explícito na CLI.

## Validação pós-patch

1. Smoke test: `python local-extras/test_ollama_extraction.py` — já valida o schema.
2. Teste integrado mínimo:
   ```bash
   cd /tmp && mkdir -p mini && cd mini
   echo "# Hello\n\nThis doc references the LoginService class." > intro.md
   GRAPHIFY_OLLAMA_KEY=ollama python -m graphify . --backend ollama --no-viz
   cat graphify-out/graph.json | jq '.nodes | length'
   ```
3. Rodar a suíte: `pytest tests/ -q` no repo (não deve quebrar — só adicionamos uma entrada no dict).

## Reversão

Tirar a entrada `"ollama"` do dict desfaz tudo. Backends `claude` e `kimi` não são afetados.

## Decisões em aberto (perguntar ao usuário)

- [ ] Aplicar a Mudança 3 (auto-detect) ou exigir `--backend ollama` sempre?
- [ ] Default model: `qwen2.5:7b` (rápido, OK) ou `qwen2.5:14b` (mais lento, melhor qualidade)?
- [ ] Modificar o `skill.md` para o Claude detectar Ollama automaticamente, ou manter manual?
