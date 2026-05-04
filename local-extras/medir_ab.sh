#!/usr/bin/env bash
# Fase 4 do PLANO_LOCAL.md — roda graphify com 3 backends no mesmo corpus
# e compara custo, tempo e tamanho do grafo.
#
# Uso:
#   ./local-extras/medir_ab.sh worked/karpathy   # corpus específico
#   ./local-extras/medir_ab.sh                   # default: ./
set -euo pipefail

CORPUS="${1:-.}"
BACKENDS=(claude kimi ollama)
RESULTS=()

mkdir -p local-extras/runs

for backend in "${BACKENDS[@]}"; do
  out="graphify-out-$backend"
  log="local-extras/runs/$backend.log"

  # pula se a chave/serviço não está disponível
  case "$backend" in
    claude)  [[ -z "${ANTHROPIC_API_KEY:-}" ]] && { echo "[skip] claude (sem ANTHROPIC_API_KEY)"; continue; } ;;
    kimi)    [[ -z "${MOONSHOT_API_KEY:-}" ]]  && { echo "[skip] kimi (sem MOONSHOT_API_KEY)"; continue; } ;;
    ollama)
      curl -sf http://localhost:11434/api/tags >/dev/null || { echo "[skip] ollama (não está rodando)"; continue; }
      export GRAPHIFY_OLLAMA_KEY=ollama
      ;;
  esac

  echo "===== rodando: $backend ====="
  t0=$SECONDS
  GRAPHIFY_OUT="$out" graphify "$CORPUS" --backend "$backend" --no-viz 2>&1 | tee "$log" || true
  elapsed=$((SECONDS - t0))

  if [[ -f "$out/graph.json" ]]; then
    nodes=$(jq '.nodes | length' "$out/graph.json")
    edges=$(jq '.links | length // .edges | length' "$out/graph.json")
    cost=$(jq -r '.total_usd // 0' "$out/cost.json" 2>/dev/null || echo "n/a")
  else
    nodes=ERR; edges=ERR; cost=ERR
  fi

  RESULTS+=("$backend|${elapsed}s|$nodes|$edges|$cost")
done

echo
echo "===== resumo ====="
printf "%-10s %-8s %-8s %-8s %-10s\n" backend tempo nós edges custo_USD
printf "%-10s %-8s %-8s %-8s %-10s\n" --------- ------- ------ ------ ---------
for r in "${RESULTS[@]}"; do
  IFS='|' read -r b t n e c <<<"$r"
  printf "%-10s %-8s %-8s %-8s %-10s\n" "$b" "$t" "$n" "$e" "$c"
done
