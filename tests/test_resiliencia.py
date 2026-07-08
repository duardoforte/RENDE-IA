"""
Resiliência da integração Gemini (pós-refatoração, SEM cooldown/circuit-breaker):
  • retry de erro recuperável (503/timeout E 429/rate-limit);
  • 429 transitório → retry → sucesso; 429 persistente → esgota retries → fallback (REQUIRE=false);
  • schema inválido → fallback_schema;
  • origem rastreável (ia_real / fallback_* / mock / modo_fallback);
  • guard de duplo clique no frontend;
  • dedupe de requisições idênticas concorrentes (app.py).

Não consome Gemini real (monkeypatch em client.models.generate_content + _executar_analise).

    venv/bin/python tests/test_resiliencia.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import assistente_ia
from assistente_ia import gerar_relatorio_financeiro

CAMPOS_OBRIG = [
    "analise_macroeconomica", "estrategia_recomendada",
    "riscos_pontos_atencao", "ranking_oportunidades", "glossario",
]
ERRO_429 = "429 RESOURCE_EXHAUSTED. Rate limit exceeded."
ERRO_429_DIARIO = ("429 RESOURCE_EXHAUSTED. quotaId: "
                   "GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20")
ERRO_503 = "503 UNAVAILABLE: The model is overloaded."

TITULOS = [
    {"nome": "Tesouro Prefixado 2029", "indexador": "Prefixado", "taxa_juros": 14.86,
     "preco_unitario": 700.0, "vencimento": "01/01/2029", "retorno_real": 9.07,
     "score_risco": 0.4, "anos_vencimento": 2.5},
    {"nome": "Tesouro IPCA+ 2032", "indexador": "IPCA", "taxa_juros": 8.46,
     "preco_unitario": 400.0, "vencimento": "15/08/2032", "retorno_real": 8.46,
     "score_risco": 0.3, "anos_vencimento": 5.7},
    {"nome": "Tesouro Prefixado 2032", "indexador": "Prefixado", "taxa_juros": 14.85,
     "preco_unitario": 500.0, "vencimento": "01/01/2032", "retorno_real": 9.06,
     "score_risco": 0.43, "anos_vencimento": 5.5},
]
PERFIL = {
    "tolerancia_risco": "moderado", "objetivo": "bem", "objetivo_descricao": "comprar um bem",
    "valor": 20000, "aporteMensal": 800, "conhecimento_descricao": "intermediário",
    "tempo_investimento": 4, "unidade_tempo": "anos", "total_meses": 48,
    "ano_atual": 2026, "ano_alvo_resgate": 2030, "ipca_focus_pct": 5.3, "selic_focus_pct": 13.75,
    "vencimento_max_disponivel": {"ano": 2065, "titulo": "Tesouro RendA+ 2065"},
}

falhas = []


def check(cond, nome, detalhe=""):
    if not cond:
        falhas.append(f"{nome}: {detalhe}")
    print(f"   [{'OK  ' if cond else 'FALHA'}] {nome}" + (f" — {detalhe}" if (detalhe and not cond) else ""))


def _resp_valida():
    r = type("Resp", (), {})()
    r.text = json.dumps({
        "analise_macroeconomica": "ok", "estrategia_recomendada": "ok",
        "riscos_pontos_atencao": "- ok",
        "ranking_oportunidades": [
            {"posicao": i + 1, "nome_ativo": t["nome"], "rentabilidade": "x", "vencimento": t["vencimento"],
             "ano_vencimento_ativo": 2030, "alinhamento_prazo": "x", "papel_carteira": "x"}
            for i, t in enumerate(TITULOS)],
        "glossario": [{"termo": "IPCA", "explicacao": "y"}],
    })
    return r


def _patch(seq):
    """generate_content consumindo uma sequência de comportamentos ('ok' ou Exception)
    e contando as chamadas reais."""
    estado = {"i": 0, "n": 0}
    def _fn(*a, **k):
        estado["n"] += 1
        comportamento = seq[min(estado["i"], len(seq) - 1)]
        estado["i"] += 1
        if isinstance(comportamento, Exception):
            raise comportamento
        return _resp_valida()
    assistente_ia.client.models.generate_content = _fn
    return estado


def main():
    assistente_ia._ESPERAS_RETRY = [0, 0, 0]   # zera sleeps de retry transitório
    assistente_ia.GEMINI_MODE = "real"
    assistente_ia.REQUIRE_GEMINI = False        # caminho de fallback (não obrigatório)
    original = assistente_ia.client.models.generate_content
    try:
        # ── 1) frontend: guard de duplo clique ──────────────────────────────────
        print("\n=== 1) frontend bloqueia duplo envio ===")
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js = open(os.path.join(raiz, "client", "script.js"), encoding="utf-8").read()
        check("_analiseEmAndamento" in js, "front.flag_em_andamento")
        check("if (_analiseEmAndamento) return" in js, "front.early_return")
        check("btn.disabled = true" in js, "front.botao_desabilitado")
        check("_analiseEmAndamento = false" in js and "btn.disabled = false" in js, "front.reabilita_no_finally")

        # ── 2) 503 transitório intermitente → retry → SUCESSO (ia_real) ─────────
        print("\n=== 2) 503 → retry → sucesso ===")
        est = _patch([RuntimeError(ERRO_503), RuntimeError(ERRO_503), "ok"])
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(est["n"] == 3, "retry503.tres_tentativas", f"n={est['n']}")
        check(rel.get("_origem") == "ia_real", "retry503.origem_ia_real")

        # ── 3) 503 persistente → esgota retries → fallback (não obrigatório) ────
        print("\n=== 3) 503 persistente → fallback ===")
        est = _patch([RuntimeError(ERRO_503)])
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(est["n"] == len(assistente_ia._ESPERAS_RETRY) + 1, "persist503.esgota_retries", f"n={est['n']}")
        check(rel.get("_origem") == "fallback_erro", "persist503.origem_fallback_erro")

        # ── 4a) 429 transitório (rate-limit por minuto) → retry → SUCESSO ───────
        print("\n=== 4a) 429 transitório → retry → sucesso ===")
        est = _patch([RuntimeError(ERRO_429), RuntimeError(ERRO_429), "ok"])
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(est["n"] == 3, "429.retry_tres_tentativas", f"n={est['n']}")
        check(rel.get("_origem") == "ia_real", "429.origem_ia_real")

        # ── 4b) 429 por-minuto persistente → esgota retries → fallback_cota ─────
        print("\n=== 4b) 429 por-minuto persistente → fallback_cota ===")
        est = _patch([RuntimeError(ERRO_429)])
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(est["n"] == len(assistente_ia._ESPERAS_RETRY) + 1, "429.esgota_retries", f"n={est['n']}")
        check(rel.get("_origem") == "fallback_cota", "429.origem_fallback_cota")

        # ── 4c) 429 cota DIÁRIA → SEM retry (falha rápida) → fallback_cota ──────
        print("\n=== 4c) 429 diário → falha rápida (1 tentativa) → fallback_cota ===")
        est = _patch([RuntimeError(ERRO_429_DIARIO)])
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(est["n"] == 1, "429diario.uma_tentativa", f"n={est['n']}")
        check(rel.get("_origem") == "fallback_cota", "429diario.origem_fallback_cota")

        # ── 5) resposta inválida (schema) → fallback_schema ─────────────────────
        print("\n=== 5) schema inválido → fallback_schema ===")
        def _fn_invalido(*a, **k):
            r = type("Resp", (), {})(); r.text = "isto não é json"
            return r
        assistente_ia.client.models.generate_content = _fn_invalido
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(rel.get("_origem") == "fallback_schema", "schema.origem_fallback_schema")
        for c in CAMPOS_OBRIG:
            check(bool(rel.get(c)), f"schema.fallback_tem.{c}")

        # ── 6) origem por modo (mock/fallback), sem chamada real ────────────────
        print("\n=== 6) origem por modo ===")
        est = _patch(["ok"])
        assistente_ia.GEMINI_MODE = "mock"
        rel_mock = gerar_relatorio_financeiro(PERFIL, TITULOS)
        assistente_ia.GEMINI_MODE = "fallback"
        rel_fb = gerar_relatorio_financeiro(PERFIL, TITULOS)
        assistente_ia.GEMINI_MODE = "real"
        check(est["n"] == 0, "modos.zero_chamada_real", f"n={est['n']}")
        check(rel_mock.get("_origem") == "mock", "modos.origem_mock")
        check(rel_fb.get("_origem") == "modo_fallback", "modos.origem_modo_fallback")
    finally:
        assistente_ia.client.models.generate_content = original

    # ── 7) dedupe de requisições idênticas concorrentes (backend) ───────────────
    print("\n=== 7) dedupe: 3 POSTs idênticos concorrentes = 1 execução ===")
    import app as app_module
    req = app_module.PerfilRequest(
        valorInicial=20000, aporteMensal=800, objetivo="bem",
        tempo_investimento=4, unidade_tempo="anos", conhecimento="intermediario",
    )
    exec_count = {"n": 0}
    original_exec = app_module._executar_analise

    async def _fake_exec(r):
        exec_count["n"] += 1
        await asyncio.sleep(0.15)
        return {"ok": True, "execucao": exec_count["n"]}

    async def _run():
        app_module._executar_analise = _fake_exec
        try:
            return await asyncio.gather(*[app_module.analisar(req) for _ in range(3)])
        finally:
            app_module._executar_analise = original_exec

    resultados = asyncio.run(_run())
    check(exec_count["n"] == 1, "dedupe.uma_execucao_para_3", f"execucoes={exec_count['n']}")
    check(all(r == resultados[0] for r in resultados), "dedupe.mesmo_resultado")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — retry de transitório E 429, dedupe e origem (sem cooldown).")


if __name__ == "__main__":
    main()
