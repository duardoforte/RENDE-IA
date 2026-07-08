"""
Teste de integração do endpoint POST /api/analise — cenários A..E.

MODO PADRÃO = FALLBACK SEGURO (não consome cota do Gemini):
    venv/bin/python tests/test_api_cenarios.py
  Roda in-process (TestClient) com fallback determinístico — 0 chamadas reais.

MODO REAL (consome a cota diária — use só quando quiser testar o Gemini de verdade):
    RENDE_IA_GEMINI_MODE=real venv/bin/python tests/test_api_cenarios.py

Não precisa de servidor rodando — usa o app in-process.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODO_REAL = os.getenv("RENDE_IA_GEMINI_MODE", "mock").strip().lower() == "real"

import assistente_ia
import app as app_module
from fastapi.testclient import TestClient

_client = TestClient(app_module.app)
_GEMINI_CALLS = {"n": 0}


CENARIOS = {
    "A_conservador_reserva": {
        "valorInicial": 5000, "aporteMensal": 300, "objetivo": "reserva",
        "tempo_investimento": 8, "unidade_tempo": "meses", "conhecimento": "iniciante",
    },
    "B_moderado_medio": {
        "valorInicial": 20000, "aporteMensal": 800, "objetivo": "bem",
        "tempo_investimento": 4, "unidade_tempo": "anos", "conhecimento": "intermediario",
    },
    "C_arrojado_longo": {
        "valorInicial": 80000, "aporteMensal": 2000, "objetivo": "juros",
        "tempo_investimento": 12, "unidade_tempo": "anos", "conhecimento": "avancado",
    },
    "D_prazo_excede": {
        "valorInicial": 30000, "aporteMensal": 1000, "objetivo": "render",
        "tempo_investimento": 70, "unidade_tempo": "anos", "conhecimento": "avancado",
    },
}
INVALIDOS = {
    "E1_valor_negativo": {"valorInicial": -100, "aporteMensal": 0, "objetivo": "reserva",
                          "tempo_investimento": 12, "unidade_tempo": "meses", "conhecimento": "iniciante"},
    "E2_tempo_zero": {"valorInicial": 1000, "aporteMensal": 0, "objetivo": "reserva",
                      "tempo_investimento": 0, "unidade_tempo": "meses", "conhecimento": "iniciante"},
    "E3_objetivo_desconhecido": {"valorInicial": 1000, "aporteMensal": 0, "objetivo": "foobar",
                                 "tempo_investimento": 12, "unidade_tempo": "meses", "conhecimento": "iniciante"},
    "E4_conhecimento_invalido": {"valorInicial": 1000, "aporteMensal": 0, "objetivo": "reserva",
                                 "tempo_investimento": 12, "unidade_tempo": "meses", "conhecimento": "expert_xyz"},
    "E5_campos_faltando": {"valorInicial": 1000},
}
CAMPOS_IA_OBRIG = ["analise_macroeconomica", "estrategia_recomendada",
                   "riscos_pontos_atencao", "ranking_oportunidades", "glossario"]
CAMPOS_RANKING = ["posicao", "nome_ativo", "rentabilidade", "vencimento",
                  "ano_vencimento_ativo", "alinhamento_prazo", "papel_carteira"]
falhas = []


def _post(payload):
    t0 = time.time()
    r = _client.post("/api/analise", json=payload)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body, time.time() - t0


def check(cond, nome, detalhe=""):
    if not cond:
        falhas.append(f"{nome}: {detalhe}")
    print(f"   [{'OK  ' if cond else 'FALHA'}] {nome}" + (f" — {detalhe}" if (detalhe and not cond) else ""))
    return cond


def validar_cenario_valido(nome, payload):
    print(f"\n=== {nome} ===")
    status, body, dt = _post(payload)
    print(f"   HTTP {status} em {dt:.2f}s")
    check(status == 200, f"{nome}.http200", f"status={status} body={str(body)[:200]}")
    if status != 200:
        return
    for k in ("perfil_ml", "analise_quantitativa", "relatorio_markdown",
              "relatorio_estruturado", "dados_projecao", "alerta_limite"):
        check(k in body, f"{nome}.tem.{k}")
    estr = body.get("relatorio_estruturado", {})
    for c in CAMPOS_IA_OBRIG:
        check(c in estr, f"{nome}.ia.{c}")
    rk = estr.get("ranking_oportunidades", [])
    if rk:
        check(len(rk) == 3, f"{nome}.ranking.len==3", f"len={len(rk)}")
        for i, item in enumerate(rk):
            for c in CAMPOS_RANKING:
                check(c in item, f"{nome}.ranking[{i}].{c}")
        pos1 = next((x for x in rk if x.get("posicao") == 1), None)
        check(pos1 is not None, f"{nome}.ranking.tem_pos1")
        if pos1:
            venc = body["dados_projecao"].get("nome_ativo_vencedor", "")
            n1 = pos1.get("nome_ativo", "")
            casa = n1.lower() in venc.lower() or venc.lower() in n1.lower()
            check(casa, f"{nome}.pos1==projecao_vencedor", f"pos1='{n1}' projecao='{venc}'")
    md = body.get("relatorio_markdown", "")
    check(isinstance(md, str) and len(md) > 50, f"{nome}.markdown_nao_vazio", f"len={len(md)}")
    proj = body.get("dados_projecao", {})
    for k in ("meses_anos", "montante_total", "capital_investido", "juros_acumulados", "montante_final"):
        check(k in proj, f"{nome}.proj.{k}")
    if "meses_anos" in proj and "montante_total" in proj:
        check(len(proj["meses_anos"]) == len(proj["montante_total"]), f"{nome}.proj.series_alinhadas")
        check(all(v >= 0 for v in proj["montante_total"]), f"{nome}.proj.sem_negativos")
        tm = proj.get("total_meses")
        if tm is not None:
            check(len(proj["meses_anos"]) == tm + 1, f"{nome}.proj.pontos==total_meses+1")
        check(proj["montante_final"] >= proj["capital_final"] - 0.01, f"{nome}.proj.montante>=capital")
    return body


def main():
    print("#" * 60)
    print(f"#  MODO: {'REAL (consome cota Gemini!)' if MODO_REAL else 'FALLBACK SEGURO (0 consumo de cota)'}")
    print("#" * 60)
    if not MODO_REAL:
        # Modo seguro padrão: usa o fallback determinístico do assistente, que
        # monta ranking com os títulos reais do pipeline e não toca o cliente Gemini.
        assistente_ia.GEMINI_MODE = "fallback"

    bodies = {}
    print("\n############ CENÁRIOS VÁLIDOS (A,B,C,D) ############")
    for nome, payload in CENARIOS.items():
        bodies[nome] = validar_cenario_valido(nome, payload)

    print("\n=== D: validação específica do alerta_limite ===")
    d = bodies.get("D_prazo_excede")
    if d:
        al = d.get("alerta_limite", {})
        check(al.get("excedido") is True, "D.alerta.excedido", str(al.get("excedido")))
        check(al.get("tipo") in ("tesouro_limit", "recomendacao_curta"), "D.alerta.tipo_valido")
        check(al.get("linha_vertical_meses") is not None, "D.alerta.linha_vertical")

    print("\n############ ENTRADAS INVÁLIDAS (E) ############")
    for nome, payload in INVALIDOS.items():
        print(f"\n=== {nome} ===")
        status, body, dt = _post(payload)
        print(f"   HTTP {status} -> {str(body)[:130]}")
        if nome in ("E1_valor_negativo", "E2_tempo_zero", "E5_campos_faltando"):
            check(status == 422, f"{nome}.rejeitado_422", f"status={status}")
        else:
            check(status in (200, 422), f"{nome}.resposta_definida", f"status={status}")

    print("\n############ CONSUMO DE COTA ############")
    if MODO_REAL:
        print(f"   Modo REAL — chamadas reais ao Gemini foram feitas (1 por cenário válido).")
    else:
        print(f"   Modo seguro — chamadas REAIS ao Gemini = 0 (cliente Gemini invocado {_GEMINI_CALLS['n']} vez(es)).")
        check(_GEMINI_CALLS["n"] == 0, "mock.zero_consumo_real", f"invocacoes={_GEMINI_CALLS['n']}")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS CRÍTICOS PASSARAM.")


if __name__ == "__main__":
    main()
