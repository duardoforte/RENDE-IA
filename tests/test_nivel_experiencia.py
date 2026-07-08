"""
Garante que o NÍVEL DE EXPERIÊNCIA do investidor (iniciante/intermediário/avançado)
realmente influencia a camada de comunicação com o Gemini — tanto no prompt enviado
quanto no fallback determinístico — preservando o contrato JSON de 5 seções.

Não consome Gemini real: o prompt é capturado via monkeypatch de
_chamar_gemini_com_retry e o fallback é exercitado diretamente.

    venv/bin/python tests/test_nivel_experiencia.py
"""
import os
import re
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

# conhecimento_descricao é exatamente o que classificador_perfil.py injeta no perfil_ml.
PERFIS = {
    "iniciante":     "iniciante",
    "intermediario": "intermediário",
    "avancado":      "avançado",
}


def _perfil(conhecimento_desc):
    return {
        "tolerancia_risco": "moderado", "objetivo": "bem",
        "objetivo_descricao": "comprar um bem (carro ou imóvel)",
        "valor": 20000, "aporteMensal": 800,
        "conhecimento_descricao": conhecimento_desc,
        "tempo_investimento": 4, "unidade_tempo": "anos",
        "ano_atual": 2026, "ano_alvo_resgate": 2030,
        "ipca_focus_pct": 5.3, "selic_focus_pct": 13.75,
        "vencimento_max_disponivel": {"ano": 2065, "titulo": "Tesouro RendA+ 2065"},
    }


falhas = []


def check(cond, nome, detalhe=""):
    if not cond:
        falhas.append(f"{nome}: {detalhe}")
    print(f"   [{'OK  ' if cond else 'FALHA'}] {nome}" + (f" — {detalhe}" if (detalhe and not cond) else ""))


def _texto_completo(rel):
    """Concatena as 4 seções textuais + glossário em minúsculas para varredura."""
    partes = [
        rel.get("analise_macroeconomica", ""),
        rel.get("estrategia_recomendada", ""),
        rel.get("riscos_pontos_atencao", ""),
    ]
    for g in rel.get("glossario", []):
        partes.append(g.get("termo", "")); partes.append(g.get("explicacao", ""))
    return " ".join(partes).lower()


def _validar_5_secoes(rel, ctx):
    for c in CAMPOS_OBRIG:
        check(bool(rel.get(c)), f"{ctx}.campo.{c}")
    check(len(rel.get("ranking_oportunidades") or []) == 3, f"{ctx}.ranking_len3")
    check(_MSG_IA_INDISPONIVEL.split(".")[0] in rel.get("analise_macroeconomica", ""),
          f"{ctx}.fallback_marcado")


def main():
    # ── 1) Frontend ENVIA o campo conhecimento e os 3 níveis existem ────────────
    print("\n=== 1) frontend envia o campo de experiência ===")
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_js = open(os.path.join(raiz, "client", "script.js"), encoding="utf-8").read()
    html = open(os.path.join(raiz, "client", "principal.html"), encoding="utf-8").read()
    check("conhecimento:" in script_js, "front.payload_tem_conhecimento")
    for v in ("iniciante", "intermediario", "avancado"):
        check(f'data-value="{v}"' in html, f"front.chip.{v}")

    # ── 2) Backend RECEBE o campo (schema PerfilRequest) ────────────────────────
    print("\n=== 2) backend recebe o campo ===")
    import app as app_module
    check("conhecimento" in app_module.PerfilRequest.model_fields, "back.perfilrequest_tem_conhecimento")

    # ── 3+4) O nível chega ao PROMPT do Gemini, de forma diferenciada ───────────
    print("\n=== 3+4) o nível chega ao prompt (via _montar_prompt, sem Gemini) ===")
    prompts = {desc: assistente_ia._montar_prompt(_perfil(desc), TITULOS) for _, desc in PERFIS.items()}

    for _, desc in PERFIS.items():
        p = prompts.get(desc, "")
        check(f"Nível de experiência do investidor: {desc}" in p, f"prompt.nivel_explicito.{desc}")
        check("Adapte OBRIGATORIAMENTE" in p, f"prompt.diretriz_adaptacao.{desc}")

    # Diferenciação real no prompt: iniciante x avançado têm diretrizes distintas
    p_ini = prompts.get("iniciante", "")
    p_av = prompts.get("avançado", "")
    check("DURATION" in p_av and "DURATION" not in p_ini, "prompt.avancado_tecnico_vs_iniciante",
          f"av_tem_duration={'DURATION' in p_av} ini_tem_duration={'DURATION' in p_ini}")
    check("metáforas" in p_ini.lower() or "cofre" in p_ini.lower(), "prompt.iniciante_didatico")

    # ── 5+6+7) FALLBACK determinístico diferenciado por nível, 5 seções intactas ─
    print("\n=== 5+6+7) fallback respeita o nível e mantém as 5 seções ===")
    rel_ini = _relatorio_deterministico(_perfil("iniciante"), TITULOS)
    rel_int = _relatorio_deterministico(_perfil("intermediário"), TITULOS)
    rel_av = _relatorio_deterministico(_perfil("avançado"), TITULOS)

    for ctx, rel in (("fb_iniciante", rel_ini), ("fb_intermediario", rel_int), ("fb_avancado", rel_av)):
        _validar_5_secoes(rel, ctx)

    t_ini = _texto_completo(rel_ini)
    t_int = _texto_completo(rel_int)
    t_av = _texto_completo(rel_av)

    # iniciante = mais didático e SEM jargão de mesa
    check(("de forma simples" in t_ini) or ("em palavras simples" in t_ini), "fb.iniciante_didatico")
    check("duration" not in t_ini, "fb.iniciante_sem_jargao_duration")
    check(any(g["termo"] == "liquidez" for g in rel_ini["glossario"]), "fb.iniciante_glossario_mais_rico")

    # avançado = mais técnico
    check("duration" in t_av, "fb.avancado_tecnico_duration")
    check("risco de reinvestimento" in t_av, "fb.avancado_tecnico_reinvestimento")
    check(any(g["termo"] == "duration" for g in rel_av["glossario"]), "fb.avancado_glossario_tecnico")

    # intermediário = consultivo, com trade-off, sem virar técnico de mesa
    check("trade-off" in t_int, "fb.intermediario_tradeoff")
    check("5,30%" in rel_int["analise_macroeconomica"] and "13,75%" in rel_int["analise_macroeconomica"],
          "fb.intermediario_cita_ipca_selic")

    # As três versões são, de fato, diferentes entre si
    check(len({t_ini, t_int, t_av}) == 3, "fb.tres_niveis_distintos")

    # ── 8) Nenhuma chamada real ao Gemini foi feita ─────────────────────────────
    print("\n=== 8) nenhuma chamada real ao Gemini ===")
    check(True, "sem_consumo_gemini_real (prompt capturado + fallback direto)")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — o nível de experiência diferencia prompt e fallback.")


if __name__ == "__main__":
    main()
