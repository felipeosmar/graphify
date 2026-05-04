#!/usr/bin/env bash
# Fase 0 do PLANO_LOCAL.md — sobe Ollama, baixa modelos, instala graphifyy.
# Idempotente: pode rodar várias vezes sem efeito colateral.
set -euo pipefail

PRIMARY_MODEL="qwen2.5:7b-instruct-q4_K_M"
FALLBACK_MODEL="qwen2.5:14b-instruct-q4_K_M"
EMBED_MODEL="nomic-embed-text"

log() { printf "\033[1;34m[setup]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[setup]\033[0m %s\n" "$*" >&2; }
fail() { printf "\033[1;31m[setup]\033[0m %s\n" "$*" >&2; exit 1; }

# 1. Ollama up
if ! command -v ollama >/dev/null 2>&1; then
  fail "ollama não está instalado. Instale a partir de https://ollama.com/download e rode de novo."
fi

if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  log "Ollama não respondeu. Tentando subir via systemd..."
  if systemctl list-unit-files | grep -q '^ollama\.service'; then
    sudo systemctl enable --now ollama
  else
    warn "Sem unit do systemd. Suba manualmente em outro terminal: 'ollama serve'"
    fail "Ollama precisa estar rodando antes de continuar."
  fi
fi

log "Ollama respondendo em http://localhost:11434"

# 2. Modelos
pull_if_missing() {
  local model="$1"
  if ollama list | awk 'NR>1 {print $1}' | grep -qx "$model"; then
    log "modelo já presente: $model"
  else
    log "puxando modelo: $model (pode demorar)"
    ollama pull "$model"
  fi
}

pull_if_missing "$PRIMARY_MODEL"
pull_if_missing "$FALLBACK_MODEL"
pull_if_missing "$EMBED_MODEL"

# 3. graphifyy
if ! command -v graphify >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    log "instalando graphifyy via uv tool"
    uv tool install graphifyy
  elif command -v pipx >/dev/null 2>&1; then
    log "instalando graphifyy via pipx"
    pipx install graphifyy
  else
    fail "nem uv nem pipx disponíveis. Instale um dos dois."
  fi
else
  log "graphify já está no PATH: $(graphify --version 2>&1 | head -1)"
fi

# 4. Sanity check final
log "checagem final:"
echo "  ollama: $(ollama --version 2>&1 | head -1)"
echo "  graphify: $(graphify --version 2>&1 | head -1)"
echo "  modelos:"
ollama list | sed 's/^/    /'

log "Fase 0 concluída. Próximo passo: rodar test_ollama_extraction.py"
