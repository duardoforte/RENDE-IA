"""
Modo IA OBRIGATÓRIA (RENDE_IA_REQUIRE_GEMINI=true): a camada real NÃO cai em
fallback determinístico — qualquer falha vira erro controlado (GeminiObrigatorioError)
e o endpoint devolve HTTP 503 com mensagem amigável. Com a flag false/ausente, o
comportamento robusto atual (fallback) é preservado.

Não consome Gemini real: monkeypatch em client.models.generate_content.

    venv/bin/python tests/test_ia_obrigatoria.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import assistente_ia
from assistente_ia import gerar_relatorio_financeiro, GeminiObrigatorioError

CAMPOS_OBRIG = [
    "analise_macroeconomica", "estrategia_recomendada",
    "riscos_pontos_atencao", "ranking_oportunidades", "glossario",
]
ERRO_429 = ("429 RESOURCE_EXHAUSTED. quotaId: "
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier")

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


def _resp_ok():
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


def _set(fn):
    assistente_ia.client.models.generate_content = fn


def main():
    assistente_ia._ESPERAS_RETRY = [0, 0, 0]
    assistente_ia.GEMINI_MODE = "real"
    original = assistente_ia.client.models.generate_content
    require_orig = assistente_ia.REQUIRE_GEMINI
    try:
        # ── 1) flag false → fallback preservado (NÃO levanta) ───────────────────
        print("\n=== 1) REQUIRE_GEMINI=false → fallback preservado ===")
        assistente_ia.REQUIRE_GEMINI = False
        _set(lambda *a, **k: (_ for _ in ()).throw(RuntimeError(ERRO_429)))
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(isinstance(rel, dict) and rel.get("_origem") == "fallback_cota", "false.cai_em_fallback")
        for c in CAMPOS_OBRIG:
            check(bool(rel.get(c)), f"false.fallback_tem.{c}")

        # ── 2) flag true + sucesso → IA real ────────────────────────────────────
        print("\n=== 2) REQUIRE_GEMINI=true + sucesso → ia_real ===")
        assistente_ia.REQUIRE_GEMINI = True
        _set(lambda *a, **k: _resp_ok())
        rel = gerar_relatorio_financeiro(PERFIL, TITULOS)
        check(rel.get("_origem") == "ia_real", "true.sucesso_ia_real")

        # ── 3) flag true + 429 → erro controlado (sem fallback) ─────────────────
        print("\n=== 3) REQUIRE_GEMINI=true + 429 → GeminiObrigatorioError ===")
        _set(lambda *a, **k: (_ for _ in ()).throw(RuntimeError(ERRO_429)))
        levantou = False
        try:
            gerar_relatorio_financeiro(PERFIL, TITULOS)
        except GeminiObrigatorioError as e:
            levantou = True
            check(e.motivo == "quota/429", "true.429_motivo", f"motivo={e.motivo}")
        check(levantou, "true.429_nao_retorna_fallback")

        # ── 4) flag true + schema inválido → erro controlado (sem fallback) ─────
        print("\n=== 4) REQUIRE_GEMINI=true + schema inválido → erro ===")
        def _resp_invalida(*a, **k):
            r = type("Resp", (), {})(); r.text = "não é json"
            return r
        _set(_resp_invalida)
        levantou = False
        try:
            gerar_relatorio_financeiro(PERFIL, TITULOS)
        except GeminiObrigatorioError:
            levantou = True
        check(levantou, "true.schema_nao_retorna_fallback")
    finally:
        assistente_ia.client.models.generate_content = original
        assistente_ia.REQUIRE_GEMINI = require_orig

    # ── 5) Endpoint: flag true + falha → HTTP 503 + JSON amigável ───────────────
    print("\n=== 5) endpoint: IA obrigatória falha → HTTP 503 amigável ===")
    from fastapi.testclient import TestClient
    import app as app_module
    assistente_ia.GEMINI_MODE = "real"
    assistente_ia.REQUIRE_GEMINI = True
    assistente_ia.client.models.generate_content = lambda *a, **k: (_ for _ in ()).throw(RuntimeError(ERRO_429))
    cli = TestClient(app_module.app)
    resp = cli.post("/api/analise", json={
        "valorInicial": 20000, "aporteMensal": 800, "objetivo": "bem",
        "tempo_investimento": 4, "unidade_tempo": "anos", "conhecimento": "intermediario",
    })
    check(resp.status_code == 503, "endpoint.http503", f"status={resp.status_code}")
    body = resp.json()
    check(body.get("erro") is True, "endpoint.erro_true")
    check(body.get("tipo") == "ia_indisponivel", "endpoint.tipo_ia_indisponivel")
    check(body.get("origem_relatorio") == "erro_ia_obrigatoria", "endpoint.origem_erro")
    check("não foi possível" in (body.get("mensagem", "")).lower(), "endpoint.mensagem_amigavel")
    # não vaza detalhe técnico nem relatório determinístico
    bruto = json.dumps(body, ensure_ascii=False).lower()
    check("traceback" not in bruto and "api_key" not in bruto and "modo determinístico" not in bruto,
          "endpoint.sem_vazamento_nem_fallback")

    # ── 6) Endpoint: flag false + falha → 200 com fallback (regressão) ──────────
    print("\n=== 6) endpoint: flag false → 200 com fallback ===")
    assistente_ia.REQUIRE_GEMINI = False
    resp2 = cli.post("/api/analise", json={
        "valorInicial": 20000, "aporteMensal": 800, "objetivo": "bem",
        "tempo_investimento": 4, "unidade_tempo": "anos", "conhecimento": "intermediario",
    })
    check(resp2.status_code == 200, "endpoint.false_http200", f"status={resp2.status_code}")
    check(resp2.json().get("origem_relatorio") == "fallback_cota", "endpoint.false_fallback")

    # ── 7) Frontend: mensagem amigável + guard de duplo clique ──────────────────
    print("\n=== 7) frontend trata erro amigável e mantém guard ===")
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(raiz, "client", "script.js"), encoding="utf-8").read()
    check("err.mensagem" in js, "front.usa_mensagem_amigavel")
    check("mostrarToast" in js and "IA indisponível" in js, "front.exibe_toast_amigavel")
    check("_analiseEmAndamento" in js and "btn.disabled = true" in js, "front.mantem_guard_duplo_clique")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — IA obrigatória bloqueia fallback; flag false preserva o atual.")


if __name__ == "__main__":
    main()
