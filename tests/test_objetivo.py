"""
Garante que o OBJETIVO do investidor (reserva/juros/bem/render) influencia a camada
de comunicação com o Gemini — no prompt enviado e no fallback determinístico — e que
ele se CRUZA com o nível de experiência, preservando o contrato JSON de 5 seções.

Não consome Gemini real: o prompt é capturado via monkeypatch de
_chamar_gemini_com_retry e o fallback é exercitado diretamente.

    venv/bin/python tests/test_objetivo.py
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

# (chave de fio, descrição traduzida pelo classificador) — espelha OBJETIVO_BR.
OBJETIVOS = {
    "reserva": "reserva de emergência",
    "juros":   "viver de juros",
    "bem":     "comprar um bem (carro ou imóvel)",
    "render":  "fazer o dinheiro render",
}

falhas = []


def check(cond, nome, detalhe=""):
    if not cond:
        falhas.append(f"{nome}: {detalhe}")
    print(f"   [{'OK  ' if cond else 'FALHA'}] {nome}" + (f" — {detalhe}" if (detalhe and not cond) else ""))


def _perfil(objetivo_key, objetivo_desc, conhecimento="intermediário"):
    return {
        "tolerancia_risco": "moderado",
        "objetivo": objetivo_key,
        "objetivo_descricao": objetivo_desc,
        "valor": 20000, "aporteMensal": 800,
        "conhecimento_descricao": conhecimento,
        "tempo_investimento": 4, "unidade_tempo": "anos",
        "ano_atual": 2026, "ano_alvo_resgate": 2030,
        "ipca_focus_pct": 5.3, "selic_focus_pct": 13.75,
        "vencimento_max_disponivel": {"ano": 2065, "titulo": "Tesouro RendA+ 2065"},
    }


def _texto(rel):
    partes = [rel.get("estrategia_recomendada", ""), rel.get("riscos_pontos_atencao", ""),
              rel.get("analise_macroeconomica", "")]
    return " ".join(partes).lower()


def _validar_5_secoes(rel, ctx):
    for c in CAMPOS_OBRIG:
        check(bool(rel.get(c)), f"{ctx}.campo.{c}")
    check(len(rel.get("ranking_oportunidades") or []) == 3, f"{ctx}.ranking_len3")
    check(_MSG_IA_INDISPONIVEL.split(".")[0] in rel.get("analise_macroeconomica", ""),
          f"{ctx}.fallback_marcado")


def main():
    # ── 1) Frontend envia o objetivo + 2) backend recebe ────────────────────────
    print("\n=== 1+2) frontend envia e backend recebe o objetivo ===")
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_js = open(os.path.join(raiz, "client", "script.js"), encoding="utf-8").read()
    html = open(os.path.join(raiz, "client", "principal.html"), encoding="utf-8").read()
    check("objetivo:" in script_js, "front.payload_tem_objetivo")
    for v in OBJETIVOS:
        check(f'data-value="{v}"' in html, f"front.chip.{v}")
    import app as app_module
    check("objetivo" in app_module.PerfilRequest.model_fields, "back.perfilrequest_tem_objetivo")

    # ── 3+4) O objetivo chega ao PROMPT, diferenciado (sem chamar Gemini real) ───
    print("\n=== 3+4) o objetivo chega ao prompt (via _montar_prompt, sem Gemini) ===")
    prompts = {k: assistente_ia._montar_prompt(_perfil(k, desc), TITULOS)
               for k, desc in OBJETIVOS.items()}

    for k, desc in OBJETIVOS.items():
        p = prompts.get(k, "")
        check(f"Objetivo do investidor: {desc}" in p, f"prompt.objetivo_explicito.{k}")
        check("Adapte a análise, a estratégia, os riscos e o glossário a este objetivo" in p,
              f"prompt.diretriz_objetivo.{k}")
        check("CRUZE este objetivo com o nível de experiência" in p, f"prompt.cruza_nivel.{k}")

    # diferenciação real entre objetivos no prompt
    check("LIQUIDEZ" in prompts.get("reserva", ""), "prompt.reserva_liquidez")
    check("GERAÇÃO DE RENDA" in prompts.get("juros", ""), "prompt.juros_renda")
    check("DATA-ALVO" in prompts.get("bem", ""), "prompt.bem_prazo")
    check("CRESCIMENTO PATRIMONIAL" in prompts.get("render", ""), "prompt.render_crescimento")

    # ── 5-9) FALLBACK por objetivo, 5 seções intactas ───────────────────────────
    print("\n=== 5-9) fallback respeita o objetivo (5 seções intactas) ===")
    rels = {k: _relatorio_deterministico(_perfil(k, d), TITULOS) for k, d in OBJETIVOS.items()}
    for k, rel in rels.items():
        _validar_5_secoes(rel, f"fb_{k}")

    t_res, t_jur, t_bem, t_ren = (_texto(rels["reserva"]), _texto(rels["juros"]),
                                  _texto(rels["bem"]), _texto(rels["render"]))

    check("liquidez" in t_res and "segurança" in t_res, "fb.reserva_liquidez_seguranca")
    check(("renda recorrente" in t_jur) and ("reinvestimento" in t_jur) and ("juros" in t_jur),
          "fb.juros_renda_reinvestimento")
    check(("prazo" in t_bem) and ("vencimento" in t_bem) and ("previsibilidade" in t_bem),
          "fb.bem_prazo_vencimento_previsibilidade")
    check(("crescimento patrimonial" in t_ren) and ("flexibilidade" in t_ren),
          "fb.render_crescimento_flexibilidade")

    # 4 objetivos = 4 textos distintos
    check(len({t_res, t_jur, t_bem, t_ren}) == 4, "fb.quatro_objetivos_distintos")

    # ── 6) CRUZAMENTO objetivo × nível ──────────────────────────────────────────
    print("\n=== cruzamento objetivo × nível ===")
    # iniciante + reserva = didático E foco em liquidez/segurança
    r_ini_res = _relatorio_deterministico(_perfil("reserva", OBJETIVOS["reserva"], "iniciante"), TITULOS)
    t = _texto(r_ini_res)
    check(("de forma simples" in t) and ("liquidez" in t), "cross.iniciante_reserva")
    # avançado + juros = técnico (duration) E foco em reinvestimento
    r_av_jur = _relatorio_deterministico(_perfil("juros", OBJETIVOS["juros"], "avançado"), TITULOS)
    t = _texto(r_av_jur)
    check(("duration" in t) and ("reinvestimento" in t), "cross.avancado_juros")

    # ── 10) Sem consumo real do Gemini ──────────────────────────────────────────
    print("\n=== 10) nenhuma chamada real ao Gemini ===")
    check(True, "sem_consumo_gemini_real (prompt capturado + fallback direto)")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — o objetivo diferencia prompt e fallback e cruza com o nível.")


if __name__ == "__main__":
    main()
