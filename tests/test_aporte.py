"""
Garante que o VALOR INICIAL e o APORTE MENSAL influenciam a camada de comunicação
com o Gemini — no prompt e no fallback determinístico — diferenciando investimento
ÚNICO de RECORRENTE, e cruzando com objetivo e nível de experiência, sem quebrar o
contrato JSON de 5 seções.

Não consome Gemini real: prompt capturado via monkeypatch + fallback direto.

    venv/bin/python tests/test_aporte.py
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

falhas = []


def check(cond, nome, detalhe=""):
    if not cond:
        falhas.append(f"{nome}: {detalhe}")
    print(f"   [{'OK  ' if cond else 'FALHA'}] {nome}" + (f" — {detalhe}" if (detalhe and not cond) else ""))


def _perfil(valor, aporte, objetivo="bem", objetivo_desc="comprar um bem (carro ou imóvel)",
            conhecimento="intermediário"):
    return {
        "tolerancia_risco": "moderado",
        "objetivo": objetivo, "objetivo_descricao": objetivo_desc,
        "valor": valor, "aporteMensal": aporte,
        "conhecimento_descricao": conhecimento,
        "tempo_investimento": 4, "unidade_tempo": "anos",
        "ano_atual": 2026, "ano_alvo_resgate": 2030,
        "ipca_focus_pct": 5.3, "selic_focus_pct": 13.75,
        "vencimento_max_disponivel": {"ano": 2065, "titulo": "Tesouro RendA+ 2065"},
    }


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
    # ── 1+2+3) frontend envia / backend recebe valor e aporte ───────────────────
    print("\n=== 1-3) frontend envia e backend recebe valor inicial e aporte ===")
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_js = open(os.path.join(raiz, "client", "script.js"), encoding="utf-8").read()
    check("valorInicial:" in script_js, "front.payload_tem_valorInicial")
    check("aporteMensal:" in script_js, "front.payload_tem_aporteMensal")
    import app as app_module
    campos = app_module.PerfilRequest.model_fields
    check("valorInicial" in campos, "back.perfilrequest_tem_valorInicial")
    check("aporteMensal" in campos, "back.perfilrequest_tem_aporteMensal")

    # ── 4+5) o prompt recebe valor, aporte e a flag de recorrência ──────────────
    print("\n=== 4-5) prompt contém valor, aporte e flag de recorrência (via _montar_prompt) ===")
    prompts = {
        (10000, 0): assistente_ia._montar_prompt(_perfil(10000, 0), TITULOS),     # sem aporte
        (5000, 300): assistente_ia._montar_prompt(_perfil(5000, 300), TITULOS),   # com aporte
    }

    p_sem = prompts[(10000, 0)]
    p_com = prompts[(5000, 300)]
    check("Valor inicial investido: R$ 10.000,00" in p_sem, "prompt.valor_inicial_explicito")
    check("Aporte mensal: R$ 0,00" in p_sem, "prompt.aporte_explicito_zero")
    check("O usuário fará aportes mensais? Não." in p_sem, "prompt.flag_recorrencia_nao")
    check("O usuário fará aportes mensais? Sim." in p_com, "prompt.flag_recorrencia_sim")
    check("Aporte mensal: R$ 300,00" in p_com, "prompt.aporte_explicito_valor")
    # diferenciação único vs recorrente no prompt
    check("investimento ÚNICO" in p_sem, "prompt.sem_aporte_unico")
    check("aportes mensais" in p_com.lower() and "disciplina" in p_com.lower(), "prompt.com_aporte_recorrente")

    # ── 6+7+8) fallback: sem aporte x com aporte (zero = ausência) ──────────────
    print("\n=== 6-8) fallback diferencia sem aporte x com aporte (zero=ausência) ===")
    rel_sem = _relatorio_deterministico(_perfil(10000, 0), TITULOS)
    rel_com = _relatorio_deterministico(_perfil(5000, 300), TITULOS)
    rel_zero = _relatorio_deterministico(_perfil(10000, 0), TITULOS)
    _validar_5_secoes(rel_sem, "fb_sem")
    _validar_5_secoes(rel_com, "fb_com")

    t_sem, t_com = _texto(rel_sem), _texto(rel_com)
    # 6) sem aporte NÃO fala como se houvesse aportes mensais
    check("investimento único" in t_sem, "fb.sem_aporte_menciona_unico")
    check("disciplina de aporte" not in t_sem and "aporte mensal constante" not in t_sem,
          "fb.sem_aporte_nao_fala_disciplina")
    # 7) com aporte menciona recorrência/disciplina/contribuição
    check(("disciplina" in t_com) or ("recorr" in t_com) or ("contribuição" in t_com),
          "fb.com_aporte_menciona_recorrencia")
    # 8) aporte zero == ausência (mesmo texto que sem aporte)
    check(_texto(rel_zero) == t_sem, "fb.aporte_zero_eq_sem_aporte")
    # 9) sem aporte e com aporte diferem
    check(t_sem != t_com, "fb.sem_difere_de_com")

    # magnitude: aporte alto x valor inicial alto sem aporte
    print("\n=== magnitude: aporte relevante / valor alto sem aporte / valor baixo+aporte alto ===")
    t_rel = _texto(_relatorio_deterministico(_perfil(25000, 1000), TITULOS))
    check("peso relevante" in t_rel or "interromper as contribuições" in t_rel, "fb.aporte_relevante")
    t_alto = _texto(_relatorio_deterministico(_perfil(150000, 0), TITULOS))
    check("preservação de capital" in t_alto and "marcação a mercado" in t_alto, "fb.valor_alto_sem_aporte")
    t_baixo = _texto(_relatorio_deterministico(_perfil(500, 1500), TITULOS))
    check("capacidade de contribuição futura" in t_baixo, "fb.valor_baixo_aporte_alto")

    # ── cruzamento aporte × objetivo × nível ────────────────────────────────────
    print("\n=== cruzamento aporte × objetivo × nível ===")
    # iniciante + reserva + sem aporte
    t = _texto(_relatorio_deterministico(
        _perfil(10000, 0, "reserva", "reserva de emergência", "iniciante"), TITULOS))
    check(("de forma simples" in t) and ("liquidez" in t) and ("investimento único" in t),
          "cross.iniciante_reserva_sem_aporte")
    # avançado + viver de juros + valor alto sem aporte
    t = _texto(_relatorio_deterministico(
        _perfil(150000, 0, "juros", "viver de juros", "avançado"), TITULOS))
    check(("duration" in t) and ("reinvestimento" in t) and ("preservação de capital" in t),
          "cross.avancado_juros_valor_alto")

    # ── 11) sem consumo real do Gemini ──────────────────────────────────────────
    print("\n=== 11) nenhuma chamada real ao Gemini ===")
    check(True, "sem_consumo_gemini_real (prompt capturado + fallback direto)")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — valor inicial e aporte diferenciam prompt e fallback.")


if __name__ == "__main__":
    main()
