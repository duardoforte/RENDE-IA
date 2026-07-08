# Testes — RENDE-IA

Estrutura mínima de QA. Não altera lógica de negócio: apenas exercita o sistema.

## Consumo de cota do Gemini (IMPORTANTE)

O modelo é `gemini-3.1-flash-lite` por padrão (configurável via `GEMINI_MODEL` no `.env`).
O free tier tem limite diário de requisições; uma análise normal em modo `real` consome **1 chamada**
(page load e preenchimento do formulário = 0). O default do backend sem `.env` é `real`;
as suítes de teste forçam mock/fallback ou monkeypatch para não consumir Gemini. Para não
gastar cota em desenvolvimento manual, rode explicitamente com `RENDE_IA_GEMINI_MODE=mock`:

| Suíte | Chamadas REAIS ao Gemini (modo padrão) |
|---|---|
| `test_api_cenarios.py` | **0** (mock in-process; opt-in real via env) |
| `test_correcoes.py` | **0** (sempre mockado) |
| Playwright (`e2e/`) | **0** (intercepta `/api/analise` no browser) |

Interruptor global do backend (vale para `app.py`/uvicorn também):

```bash
# Execução local usa o modo definido no .env. Se estiver real, consome Gemini:
venv/bin/python app.py

# MOCK explícito — resposta canônica determinística, 0 cota:
RENDE_IA_GEMINI_MODE=mock venv/bin/python app.py

# FALLBACK explícito — fallback determinístico enriquecido, 0 cota:
RENDE_IA_GEMINI_MODE=fallback venv/bin/python app.py

# DEMO REAL — chama o Gemini de verdade; requer GEMINI_API_KEY e consome 1 chamada normal por análise:
RENDE_IA_GEMINI_MODE=real venv/bin/python app.py
```

## 1. Integração da API (`test_api_cenarios.py`)

Cenários A–E in-process (TestClient) validando status HTTP, contrato JSON,
consistência `ranking[0]` ↔ título projetado, projeção e alerta de limite.

```bash
# MOCK seguro (0 cota):
RENDE_IA_GEMINI_MODE=mock venv/bin/python tests/test_api_cenarios.py

# REAL (consome cota — só quando quiser testar o Gemini de verdade):
RENDE_IA_GEMINI_MODE=real venv/bin/python tests/test_api_cenarios.py
```

## 2. Robustez/erro da IA (`test_correcoes.py`)

Sempre mockado (0 cota). Cobre: fast-fail 429 (1 tentativa), retry 503/timeout,
fallback determinístico rico por nível, ranking-consistency, projeção limitada ao
vencimento (70 anos), rota `/`, não-vazamento de erro técnico.

```bash
RENDE_IA_GEMINI_MODE=mock venv/bin/python tests/test_correcoes.py
```

## 3. E2E do frontend (`e2e/`)

Playwright. O `/api/analise` é **interceptado no browser** — não toca o backend
nem o Gemini. Cobre landing, formulário multi-step, render do relatório, gráfico,
toast de alerta, fallback da IA renderizando todas as seções, caminho de erro,
ausência de erro no console e não-vazamento de `confianca_pct`.

```bash
cd /home/eduardo-forte/IA_INVESTE/tests/e2e
npm install && npx playwright install chromium
npx playwright test            # 10 testes (5 specs × desktop+mobile)
npx playwright show-report
```

> A raiz `/` agora redireciona (307) para `/principal.html`.
