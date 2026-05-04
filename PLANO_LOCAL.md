# Plano — rodar graphify localmente economizando tokens

> Documento de planejamento. **Nada deste plano altera código do graphify ainda** — define o que fazer, em que ordem, e o que medir antes de cada passo.

## Contexto desta máquina

| Item | Valor |
|---|---|
| OS | Linux (kernel 6.17) |
| CPU | Intel Core Ultra 9 185H — 22 cores |
| RAM | 62 GiB (≈48 GiB disponíveis) |
| GPU | ✅ **NVIDIA RTX 2000 Ada, 8 GiB VRAM**, driver 580.159.03, CUDA 13.0 |
| Python | 3.14.3 (default) + 3.12.11 (pyenv) |
| `uv` | 0.9.1 ✅ |
| `pipx` | 1.4.3 ✅ |
| Ollama | v0.18.3 instalado, **não está rodando** |
| Outro | `llama-server` (Bonsai-8B) ocupando ~5.9 GiB de VRAM — experimento antigo, **derrubar antes da Fase 0** |
| Repo | `/home/felipe/work/graphify` (clone v4) |

**Implicação:** com a GPU operando (8 GiB VRAM), o modelo-alvo `qwen2.5:7b-q4` (~4.4 GiB) cabe inteiro com folga p/ contexto e roda em **~1–5s/chunk** (vs. 10–60s em CPU). 14B Q4 (~9 GiB) **não cabe** na VRAM — fica fora. Imagens (VLM 7B) entram no fluxo principal já nesta rodada.

## Descoberta-chave do código

`graphify/llm.py:46-61` define `BACKENDS` com `claude` e `kimi`. O backend `kimi` já usa `_call_openai_compat` (`llm.py:110`). **Ollama serve uma API OpenAI-compatible em `http://localhost:11434/v1`** — então adicionar Ollama é **uma entrada no dict `BACKENDS`**, não uma reescrita.

E `graphify/skill.md:208` já diz ao Claude: *"se `MOONSHOT_API_KEY` IS set, use `extract_corpus_parallel(backend='kimi')`".* O mesmo padrão se aplica para Ollama: o assistente detecta o backend disponível e orquestra; a extração roda local.

## Estratégia em 5 fases

```
Fase 0  → ambiente local (derruba llama-server, sobe Ollama + modelos texto+VLM)
Fase 1  → quick wins SEM código (ignore + cache + hook)
Fase 2  → backend "ollama" no llm.py (~10 linhas) — texto e visão
Fase 3  → orquestração via skill (Claude usa o backend local)
Fase 4  → medição A/B (Claude vs Kimi vs Ollama no mesmo corpus, incluindo imagens)
```

Cada fase tem **critério de parada**: se o ganho não aparecer ali, não passa pra próxima.

---

## Fase 0 — Ambiente local

**Objetivo:** Ollama rodando, modelos baixados, graphifyy instalado isoladamente.

### Passos

1. **Derrubar o `llama-server` do Bonsai** (libera ~5.9 GiB de VRAM — era experimento):
   ```bash
   pkill -f "llama-server.*Bonsai" && nvidia-smi   # confirmar VRAM liberada
   ```

2. Subir o Ollama como serviço:
   ```bash
   sudo systemctl enable --now ollama
   curl -s http://localhost:11434/api/tags   # deve responder JSON
   ```

3. Modelos — **todos já presentes na máquina** (verificado em `ollama list`); nenhum download necessário:
   | Modelo | Tamanho | Uso |
   |---|---|---|
   | `qwen3:8b` | 5.2 GiB Q4_K_M | extração JSON principal (escolhido — geração nova, mais capaz) |
   | `llava:7b` | 4.7 GiB Q4_0 | extração de imagens (Fase 5) |
   | `nomic-embed-text` | 274 MiB | embeddings (não usados ainda — Leiden não precisa) |

   Alternativas locais para benchmark futuro: `qwen2.5-coder:7b` (4.7 GiB, code-tuned), `deepseek-r1:8b` (5.2 GiB, reasoning — útil p/ AMBIGUOUS).

   > Nota: Ollama descarrega/recarrega o modelo conforme a chamada — alternar texto↔visão custa ~2–5s de swap, aceitável.

4. Instalar `graphifyy` via `uv` (não polui o Python global):
   ```bash
   uv tool install graphifyy
   graphify --version
   ```

5. **Não rodar `graphify install` ainda** — primeiro queremos o backend Ollama plugado, senão o skill instalado vai dispatchar subagentes Claude e gastar tokens.

**Critério de parada:** Ollama responde, `qwen2.5:7b` retorna JSON válido para um prompt-teste (script em `local-extras/test_ollama_extraction.py`), e `nvidia-smi` mostra o modelo carregado na GPU (não na CPU).

---

## Fase 1 — Quick wins sem código

Mesmo com Claude no caminho, dá pra cortar muito gasto antes de tocar em código.

### 1a. `.graphifyignore` agressivo

Template em `local-extras/graphifyignore.template`. Pontos críticos para o repo do graphify:

- `docs/translations/` (29 traduções de README, ~95% do custo de docs)
- `worked/` (corpora de teste — quase 100% do custo se indexado)
- `.venv/`, `node_modules/`, build artifacts

### 1b. Hook + `--update`

Depois de um run completo, ativar:
```bash
graphify hook install
```

Isso faz post-commit incremental: SHA256 cache em `graphify-out/cache/` evita re-extrair arquivos não alterados (`graphify/cache.py`).

### 1c. Commitar `graphify-out/` no time

Conforme README — um membro roda, comita, todos puxam. Custo zero pros demais.

**Critério de parada:** rodar `/graphify .` no próprio repo do graphify e medir tokens (relatório `graphify-out/cost.json`). Anotar o número como **baseline**.

---

## Fase 2 — Patch mínimo no `llm.py`

**Objetivo:** adicionar backend `ollama` sem quebrar `claude`/`kimi`.

### O que muda

Adicionar uma entrada em `BACKENDS` (em `graphify/llm.py:46`):

```python
"ollama": {
    "base_url": "http://localhost:11434/v1",
    "default_model": "qwen2.5:7b-instruct-q4_K_M",
    "env_key": "GRAPHIFY_OLLAMA_KEY",   # placeholder — Ollama aceita qualquer string
    "pricing": {"input": 0.0, "output": 0.0},
    "temperature": 0,
},
```

E uma pequena lógica em `extract_files_direct` (`llm.py:180`) para que, com `backend="ollama"`, a chamada vá por `_call_openai_compat` com `api_key="ollama"` (qualquer string serve, é local).

Detalhamento do diff em `local-extras/ollama_backend_patch.md`. **Não aplicar ainda** — o plano é revisar antes.

### Riscos a observar

- `qwen2.5:7b` pode produzir JSON inválido com mais frequência que Claude. O `_extract_with_adaptive_retry` (`llm.py:275`) já trata isso por bisseção — vamos usar.
- Latência por chunk em GPU: **~1–5s** (vs. ~3s do Claude). Compensa porque é grátis; paralelismo de `extract_corpus_parallel` precisa ser **limitado a 1 worker** para Ollama, senão a fila na GPU vira gargalo (Ollama serializa requisições por modelo carregado).
- `_estimate_file_tokens` usa o tokenizer do tiktoken — pode subestimar para Qwen. Não é bloqueador; só afeta o packing de chunks.
- Para a extração de imagens (Fase 5 integrada): a chamada precisa rotear `qwen2.5vl:7b` quando o tipo do arquivo for `image`. Detalhar no patch.

**Critério de parada:** rodar `extract_files_direct` num arquivo `.md` simples e validar que `validate.py` aceita o output.

---

## Fase 3 — Orquestração via Claude

**Objetivo:** Claude (no Claude Code) detecta o backend local e roda a pipeline sem dispatchar subagentes pagos.

### Como

1. Setar `GRAPHIFY_OLLAMA_KEY=ollama` no shell.
2. Instalar o skill: `graphify install`.
3. Editar (ou fazer override de) `~/.claude/skills/graphify/skill.md` para incluir uma cláusula análoga à do Kimi:
   > "Se `GRAPHIFY_OLLAMA_KEY` estiver setada e `curl http://localhost:11434/api/tags` responder, use `graphify.llm.extract_corpus_parallel(files, backend='ollama')`."

4. Resultado: o Claude no Claude Code passa a:
   - decidir escopo (o que indexar)
   - chamar `extract_corpus_parallel(backend="ollama")` — extração roda local
   - sintetizar `GRAPHIFY_REPORT.md` (essa síntese final consome poucos tokens, vale o gasto)
   - resolver edges `AMBIGUOUS` que o modelo local marcou — uso seletivo

**Crítério de parada:** rodar `/graphify .` num diretório com PDFs e ver `cost.json` ≈ 0 (só o token da síntese final).

---

## Fase 4 — Medição A/B

**Objetivo:** confirmar que a qualidade do grafo local é aceitável.

### Setup

Usar os corpora prontos em `worked/` do próprio repo (cada um já tem `review.md` com gabarito). Incluir pelo menos um corpus com imagens para validar o roteamento texto/VLM da Fase 5.

```bash
for backend in claude kimi ollama; do
  GRAPHIFY_OUT=graphify-out-$backend graphify . --backend $backend
done
```

### Métricas a comparar

| Métrica | Como medir |
|---|---|
| Custo USD | `cost.json` |
| Tempo total | `time` na CLI |
| # nós e arestas | `jq '.nodes \| length' graph.json` |
| % EXTRACTED vs INFERRED vs AMBIGUOUS | `jq` no `graph.json` |
| Cobertura dos "god nodes" esperados | comparar com `review.md` em `worked/` |
| JSON inválidos descartados | grep `invalid JSON, skipping chunk` no stderr |

Se Ollama tiver < 70% da cobertura do Claude **mas custo zero**, ainda vale como "primeiro passe" e usa Claude só para refinar AMBIGUOUS.

**Critério de parada:** decidir o setup definitivo. Possíveis veredictos:
- 🟢 Ollama sozinho — aceitável → segue grátis para sempre
- 🟡 Ollama + Claude só para AMBIGUOUS — custo ~10% do baseline
- 🔴 Qualidade ruim demais → ficar com Claude e investir em `.graphifyignore` + cache

---

## Fase 5 — Imagens (integrada ao fluxo principal)

Driver NVIDIA já resolvido (RTX 2000 Ada, CUDA 13.0). VLM 7B cabe na VRAM de 8 GiB com offload total.

### Modelo

`qwen2.5vl:7b` (~5–6 GiB Q4) — alinhado à família Qwen do modelo de texto, mesmo tokenizer-mental, menos surpresas de schema. Alternativa: `llava:7b` se houver problema de tag/disponibilidade no Ollama.

### Onde plugar

Roteamento por tipo de arquivo na pipeline de extração: se `file.type == "image"`, usar modelo VLM; caso contrário, usar texto. Detalhar como aditivo no `ollama_backend_patch.md` (mesmo backend Ollama, model name diferente).

### Risco específico

Swap de modelo na VRAM (texto ↔ VLM) — Ollama descarrega/recarrega sob demanda. Para corpora mistos (código + imagens), o ideal é processar **em duas passadas** (todos os textos, depois todas as imagens) para evitar swap a cada chunk.

**Critério de parada:** rodar num corpus que tenha pelo menos um diagrama/screenshot e validar que o nó da imagem entra no `graph.json` com extração coerente.

---

## Arquivos auxiliares neste plano

Tudo em `local-extras/` (não vai pro upstream):

| Arquivo | Propósito |
|---|---|
| `setup.sh` | bootstrap Fase 0 (Ollama + modelos + graphifyy) |
| `graphifyignore.template` | template para Fase 1a |
| `test_ollama_extraction.py` | smoke test do schema de extração |
| `ollama_backend_patch.md` | descrição do diff da Fase 2 (revisar antes de aplicar) |
| `medir_ab.sh` | runner da Fase 4 (3 backends, mesmo corpus) |

---

## Próximos passos imediatos

1. **Você revisa este plano** — confirma se o caminho faz sentido.
2. Se OK, executo a **Fase 0** (subir Ollama, baixar modelos) — único passo que mexe no sistema antes de você ver resultado.
3. Antes da Fase 2 (patch no `llm.py`), volto e te mostro o diff exato pra aprovação.
