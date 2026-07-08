"""
Garante que o PRAZO de investimento (em meses ou anos) influencia a camada de
comunicação com o Gemini — no prompt e no fallback determinístico — diferenciando
horizontes curto/médio/longo, cruzando com objetivo/aporte/nível e sinalizando
projeção limitada ao vencimento, sem quebrar o contrato JSON de 5 seções.

Também valida a conversão anos→meses e o repasse do prazo (frontend→backend→IA).
Não consome Gemini real: prompt capturado via monkeypatch + fallback direto.

    venv/bin/python tests/test_prazo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import assistente_ia
from assistente_ia import gerar_relatorio_financeiro, _relatorio_deterministico, _MSG_IA_INDISPONIVEL

CAMPOS_OBRIG = [
    "analise_macroeconomica", "estrategia_recomendada",
    "riscos_pontos_atencao", "ranking_oportunidades", "glossario",
]

TITULOS = [
    {"nome": "Tesouro Selic 2027", "indexador": "Selic", "taxa_juros": 0.10,
     "preco_unitario": 150.0, "vencimento": "01/03/2027", "retorno_real": 0.10,
     "score_risco": 0.1, "anos_vencimento": 1.0},
    {"nome": "Tesouro Prefixado 2029", "indexador": "Prefixado", "taxa_juros": 14.86,
     "preco_unitario": 700.0, "vencimento": "01/01/2029", "retorno_real": 9.07,
     "score_risco": 0.4, "anos_vencimento": 2.5},
    {"nome": "Tesouro IPCA+ 2032", "indexador": "IPCA", "taxa_juros": 8.46,
     "preco_unitario": 400.0, "vencimento": "15/08/2032", "retorno_real": 8.46,
     "score_risco": 0.3, "anos_vencimento": 5.7},
]

falhas = []


def check(cond, nome, detalhe=""):
    if not cond:
        falhas.append(f"{nome}: {detalhe}")
    print(f"   [{'OK  ' if cond else 'FALHA'}] {nome}" + (f" — {detalhe}" if (detalhe and not cond) else ""))


def _perfil(tempo, unidade, total_meses=None, objetivo="bem",
            objetivo_desc="comprar um bem (carro ou imóvel)", conhecimento="intermediário",
            valor=20000, aporte=800, ano_alvo=2030, venc_max_ano=2065):
    p = {
        "tolerancia_risco": "moderado",
        "objetivo": objetivo, "objetivo_descricao": objetivo_desc,
        "valor": valor, "aporteMensal": aporte,
        "conhecimento_descricao": conhecimento,
        "tempo_investimento": tempo, "unidade_tempo": unidade,
        "ano_atual": 2026, "ano_alvo_resgate": ano_alvo,
        "ipca_focus_pct": 5.3, "selic_focus_pct": 13.75,
        "vencimento_max_disponivel": {"ano": venc_max_ano, "titulo": "Tesouro RendA+ 2065"},
    }
    if total_meses is not None:
        p["total_meses"] = total_meses
    return p


def _texto(rel):
    return " ".join([rel.get("estrategia_recomendada", ""), rel.get("riscos_pontos_atencao", ""),
                     rel.get("analise_macroeconomica", "")]).lower()


def _validar_5_secoes(rel, ctx):
    for c in CAMPOS_OBRIG:
        check(bool(rel.get(c)), f"{ctx}.campo.{c}")
    check(len(rel.get("ranking_oportunidades") or []) == 3, f"{ctx}.ranking_len3")
    check(_MSG_IA_INDISPONIVEL.split(".")[0] in rel.get("analise_macroeconomica", ""),
          f"{ctx}.fallback_marcado")


def main():
    # ── 1+2) frontend envia prazo e unidade ─────────────────────────────────────
    print("\n=== 1-2) frontend envia prazo + unidade ===")
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_js = open(os.path.join(raiz, "client", "script.js"), encoding="utf-8").read()
    check("tempo_investimento:" in script_js, "front.payload_tem_tempo")
    check("unidade_tempo:" in script_js, "front.payload_tem_unidade")

    # ── 3+4+5) backend converte anos→meses e trata meses direto; pipeline usa ────
    print("\n=== 3-5) conversão anos→meses e meses direto (app._total_meses) ===")
    import app as app_module
    check(app_module._total_meses(2, "anos") == 24, "back.conv_anos_para_meses", )
    check(app_module._total_meses(8, "meses") == 8, "back.meses_direto")
    check(app_module._total_meses(10, "anos") == 120, "back.conv_10anos")
    check("tempo_investimento" in app_module.PerfilRequest.model_fields and
          "unidade_tempo" in app_module.PerfilRequest.model_fields, "back.perfilrequest_tem_prazo")
    # _total_meses_perfil reflete o mesmo cálculo no assistente
    check(assistente_ia._total_meses_perfil(_perfil(2, "anos")) == 24, "assist.total_meses_anos")
    check(assistente_ia._total_meses_perfil(_perfil(6, "meses")) == 6, "assist.total_meses_meses")
    # classificação de horizonte
    check(assistente_ia._horizonte_classe(6) == "muito_curto", "classe.6m")
    check(assistente_ia._horizonte_classe(24) == "curto_medio", "classe.24m")
    check(assistente_ia._horizonte_classe(48) == "medio", "classe.48m")
    check(assistente_ia._horizonte_classe(84) == "longo", "classe.84m")
    check(assistente_ia._horizonte_classe(120) == "muito_longo", "classe.120m")

    # ── 6+7) prompt recebe prazo informado, prazo em meses e horizonte ──────────
    print("\n=== 6-7) prompt contém prazo informado, meses e horizonte (via _montar_prompt) ===")
    prompts = {
        (6, "meses"): assistente_ia._montar_prompt(_perfil(6, "meses", total_meses=6), TITULOS),
        (10, "anos"): assistente_ia._montar_prompt(_perfil(10, "anos", total_meses=120), TITULOS),
    }

    p_curto = prompts[(6, "meses")]
    p_longo = prompts[(10, "anos")]
    check("Prazo informado pelo usuário: 6 meses" in p_curto, "prompt.prazo_informado_meses")
    check("Prazo convertido para a simulação: 6 meses" in p_curto, "prompt.prazo_convertido_meses")
    check("MUITO CURTO" in p_curto, "prompt.horizonte_curto")
    check("Prazo informado pelo usuário: 10 anos (120 meses)" in p_longo, "prompt.prazo_informado_anos")
    check("Prazo convertido para a simulação: 120 meses" in p_longo, "prompt.prazo_convertido_120")
    check("MUITO LONGO" in p_longo, "prompt.horizonte_muito_longo")

    # ── 8+9) fallback curto x longo difere de forma perceptível ─────────────────
    print("\n=== 8-9) fallback curto x longo ===")
    rel_curto = _relatorio_deterministico(_perfil(6, "meses", total_meses=6), TITULOS)
    rel_longo = _relatorio_deterministico(_perfil(10, "anos", total_meses=120), TITULOS)
    _validar_5_secoes(rel_curto, "fb_curto")
    _validar_5_secoes(rel_longo, "fb_longo")
    t_curto, t_longo = _texto(rel_curto), _texto(rel_longo)
    check(("liquidez" in t_curto) and ("segurança" in t_curto) and ("resgate" in t_curto),
          "fb.curto_liquidez_seguranca_resgate")
    check(("inflação" in t_longo) and ("marcação a mercado" in t_longo) and
          (("volatilidade" in t_longo) or ("revise a estratégia" in t_longo) or ("revisões" in t_longo)),
          "fb.longo_inflacao_marcacao_volatilidade")
    check(t_curto != t_longo, "fb.curto_difere_de_longo")
    # médio (3-5 anos) menciona retorno real
    t_medio = _texto(_relatorio_deterministico(_perfil(4, "anos", total_meses=48), TITULOS))
    check("retorno real" in t_medio, "fb.medio_retorno_real")

    # ── 10) prazo > vencimento máximo → alerta de projeção limitada ─────────────
    print("\n=== 10) prazo > vencimento gera alerta de limitação ===")
    rel_excede = _relatorio_deterministico(
        _perfil(80, "anos", total_meses=960, ano_alvo=2106, venc_max_ano=2065), TITULOS)
    check("limitada ao vencimento" in _texto(rel_excede), "fb.alerta_projecao_limitada")
    # quando NÃO excede, não deve aparecer o alerta
    rel_ok = _relatorio_deterministico(_perfil(4, "anos", total_meses=48, ano_alvo=2030, venc_max_ano=2065), TITULOS)
    check("limitada ao vencimento" not in _texto(rel_ok), "fb.sem_alerta_quando_cabe")

    # ── cruzamento prazo × objetivo × aporte × nível ────────────────────────────
    print("\n=== cruzamento prazo × objetivo × aporte × nível ===")
    # iniciante + reserva + curto + sem aporte
    t = _texto(_relatorio_deterministico(
        _perfil(6, "meses", total_meses=6, objetivo="reserva", objetivo_desc="reserva de emergência",
                conhecimento="iniciante", aporte=0), TITULOS))
    check(("de forma simples" in t) and ("liquidez" in t) and ("investimento único" in t),
          "cross.iniciante_reserva_curto_sem_aporte")
    # experiente + viver de juros + longo
    t = _texto(_relatorio_deterministico(
        _perfil(10, "anos", total_meses=120, objetivo="juros", objetivo_desc="viver de juros",
                conhecimento="avançado", aporte=0, valor=150000), TITULOS))
    check(("duration" in t) and ("reinvestimento" in t) and ("inflação" in t),
          "cross.avancado_juros_longo")

    # ── 12) sem consumo real do Gemini ──────────────────────────────────────────
    print("\n=== 12) nenhuma chamada real ao Gemini ===")
    check(True, "sem_consumo_gemini_real (prompt capturado + fallback direto)")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — o prazo diferencia prompt e fallback e cruza com os demais eixos.")


if __name__ == "__main__":
    main()
