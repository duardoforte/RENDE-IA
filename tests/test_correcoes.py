"""
Testes da robustez à falha do Gemini + qualidade do fallback determinístico.

Cobre:
  • 429 quota DIÁRIA  → fast-fail (1 tentativa, sem 4 retries), fallback completo.
  • 503 / timeout     → faz 1 tentativa e cai no fallback.
  • Nenhum erro bruto (429/quota/rate-limit/link) vaza para o JSON público.
  • Qualidade do fallback nível INTERMEDIÁRIO (termos financeiros, título vencedor,
    limitações da simulação).
  • Endpoint /api/analise responde HTTP 200 com a tela completa.

Roda sem servidor e sem chamar o Gemini de verdade — monkeypatch no client.
    venv/bin/python tests/test_correcoes.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import assistente_ia
from assistente_ia import gerar_relatorio_financeiro, _MSG_IA_INDISPONIVEL

CAMPOS_OBRIG = [
    "analise_macroeconomica", "estrategia_recomendada",
    "riscos_pontos_atencao", "ranking_oportunidades", "glossario",
]
CAMPOS_RANKING = [
    "posicao", "nome_ativo", "rentabilidade", "vencimento",
    "ano_vencimento_ativo", "alinhamento_prazo", "papel_carteira",
]
PROIBIDOS = [
    "429", "resource_exhausted", "quota", "rate-limit", "exceeded", "free_tier",
    "generativelanguage", "googleapis", "gemini api", "traceback", "stack", "api_key",
]

# Mensagens de erro realistas do Gemini (corpo bruto que NÃO pode vazar).
ERRO_QUOTA_DIARIA = ("429 RESOURCE_EXHAUSTED. You exceeded your current quota. "
                     "Quota exceeded for metric: generativelanguage.googleapis.com/"
                     "generate_content_free_tier_requests, "
                     "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier. "
                     "See https://ai.google.dev/gemini-api/docs/rate-limits")
ERRO_503 = "503 UNAVAILABLE: The model is overloaded. Please try again later."
ERRO_TIMEOUT = "504 DEADLINE_EXCEEDED: request timeout"

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

def _perfil(nivel):
    return {
        "tolerancia_risco": "moderado" if nivel == "intermediario" else "conservador",
        "objetivo": "bem", "objetivo_descricao": "comprar um bem (carro ou imóvel)",
        "valor": 20000, "aporteMensal": 800,
        "conhecimento_descricao": nivel,
        "tempo_investimento": 4, "unidade_tempo": "anos",
        "ano_atual": 2026, "ano_alvo_resgate": 2030,
        "ipca_focus_pct": 5.3, "selic_focus_pct": 13.75,
        "vencimento_max_disponivel": {"ano": 2084, "titulo": "Tesouro RendA+ 2065"},
    }

falhas = []


def check(cond, nome, detalhe=""):
    if not cond:
        falhas.append(f"{nome}: {detalhe}")
    print(f"   [{'OK  ' if cond else 'FALHA'}] {nome}" + (f" — {detalhe}" if (detalhe and not cond) else ""))


class _FakeErro(Exception):
    pass


def _patch_contando(msg):
    """Substitui generate_content por um que sempre lança `msg` e conta chamadas."""
    contador = {"n": 0}
    def _raise(*a, **k):
        contador["n"] += 1
        raise _FakeErro(msg)
    assistente_ia.client.models.generate_content = _raise
    return contador


def _patch_resposta_valida():
    """Substitui generate_content por uma resposta válida e conta chamadas simuladas."""
    contador = {"n": 0}
    def _ok(*a, **k):
        contador["n"] += 1
        r = type("Resp", (), {})()
        r.text = json.dumps({
            "analise_macroeconomica": "Cenário válido simulado.",
            "estrategia_recomendada": "Estratégia válida simulada.",
            "riscos_pontos_atencao": "- Risco válido simulado.",
            "ranking_oportunidades": [
                {"posicao": 1, "nome_ativo": "Tesouro Prefixado 2029", "rentabilidade": "14,86%",
                 "vencimento": "01/01/2029", "ano_vencimento_ativo": 2029,
                 "alinhamento_prazo": "Alinhamento simulado.", "papel_carteira": "trava de taxa"},
                {"posicao": 2, "nome_ativo": "Tesouro IPCA+ 2032", "rentabilidade": "IPCA + 8,46%",
                 "vencimento": "15/08/2032", "ano_vencimento_ativo": 2032,
                 "alinhamento_prazo": "Alinhamento simulado.", "papel_carteira": "proteção real"},
                {"posicao": 3, "nome_ativo": "Tesouro Prefixado 2032", "rentabilidade": "14,85%",
                 "vencimento": "01/01/2032", "ano_vencimento_ativo": 2032,
                 "alinhamento_prazo": "Alinhamento simulado.", "papel_carteira": "diversificação"},
            ],
            "glossario": [{"termo": "IPCA", "explicacao": "Inflação oficial."}],
        })
        return r
    assistente_ia.client.models.generate_content = _ok
    return contador


def _validar_contrato(nome, rel, nomes_validos):
    for c in CAMPOS_OBRIG:
        check(bool(rel.get(c)), f"{nome}.campo.{c}")
    rk = rel.get("ranking_oportunidades", [])
    check(len(rk) == 3, f"{nome}.ranking_len3", f"len={len(rk)}")
    for i, item in enumerate(rk):
        for c in CAMPOS_RANKING:
            check(c in item, f"{nome}.rk[{i}].{c}")
        check(item.get("nome_ativo") in nomes_validos, f"{nome}.rk[{i}].titulo_real",
              f"'{item.get('nome_ativo')}'")
    if rk:
        check(rk[0].get("posicao") == 1, f"{nome}.pos1")
    check(_MSG_IA_INDISPONIVEL.split(".")[0] in rel.get("analise_macroeconomica", ""),
          f"{nome}.mensagem_amigavel")
    publico = json.dumps(rel, ensure_ascii=False).lower()
    vazou = [p for p in PROIBIDOS if p in publico]
    check(not vazou, f"{nome}.sem_vazamento", f"vazou={vazou}")


def main():
    assistente_ia._ESPERAS_RETRY = [0, 0, 0]  # zera sleeps de retry transitório (teste rápido)
    assistente_ia.REQUIRE_GEMINI = False       # garante o caminho de fallback (não obrigatório)
    modo_original = assistente_ia.GEMINI_MODE
    original = assistente_ia.client.models.generate_content
    nomes_validos = {t["nome"] for t in TITULOS}
    try:
        # 0) Modos seguros: mock/fallback não chamam a API; real só chama explicitamente
        print("\n=== modos Gemini (mock/fallback/real) ===")
        assistente_ia.GEMINI_MODE = "mock"
        cont = _patch_contando(ERRO_503)
        rel_mock = gerar_relatorio_financeiro(_perfil("intermediario"), TITULOS)
        check(cont["n"] == 0, "modo.mock.zero_chamada_real", f"chamadas={cont['n']}")
        # Mock é dedicado: 5 seções, ranking com títulos reais, origem "mock",
        # e NÃO contém o texto de fallback determinístico.
        for c in CAMPOS_OBRIG:
            check(bool(rel_mock.get(c)), f"modo_mock.campo.{c}")
        check(len(rel_mock.get("ranking_oportunidades") or []) == 3, "modo_mock.ranking_len3")
        check(rel_mock.get("_origem") == "mock", "modo_mock.origem_mock")
        check("modo determinístico" not in rel_mock["analise_macroeconomica"].lower(),
              "modo_mock.nao_eh_deterministico")

        assistente_ia.GEMINI_MODE = "fallback"
        cont = _patch_contando(ERRO_503)
        rel_fallback = gerar_relatorio_financeiro(_perfil("intermediario"), TITULOS)
        check(cont["n"] == 0, "modo.fallback.zero_chamada_real", f"chamadas={cont['n']}")
        _validar_contrato("modo_fallback", rel_fallback, nomes_validos)

        assistente_ia.GEMINI_MODE = "real"
        cont = _patch_resposta_valida()
        rel_real = gerar_relatorio_financeiro(_perfil("intermediario"), TITULOS)
        check(cont["n"] == 1, "modo.real.uma_chamada_explicita", f"chamadas={cont['n']}")
        for c in CAMPOS_OBRIG:
            check(bool(rel_real.get(c)), f"modo_real.campo.{c}")

        # 1) 429 quota diária → 1 tentativa apenas (fast-fail)
        print("\n=== 429 quota diária (fast-fail, sem 4 retries) ===")
        cont = _patch_contando(ERRO_QUOTA_DIARIA)
        rel = gerar_relatorio_financeiro(_perfil("intermediario"), TITULOS)
        check(cont["n"] == 1, "quota.uma_tentativa", f"chamadas={cont['n']}")
        _validar_contrato("quota", rel, nomes_validos)

        # 2) 503 → re-tenta (1 inicial + N retries) e só então cai no fallback.
        #    503 é transitório ("model experiencing high demand") e costuma resolver
        #    na 2ª tentativa — por isso re-tentamos, ao contrário do 429/quota.
        tentativas_esperadas = len(assistente_ia._ESPERAS_RETRY) + 1
        print(f"\n=== 503 ({tentativas_esperadas} tentativas → fallback) ===")
        cont = _patch_contando(ERRO_503)
        rel503 = gerar_relatorio_financeiro(_perfil("iniciante"), TITULOS)
        check(cont["n"] == tentativas_esperadas, "503.retry_ate_fallback", f"chamadas={cont['n']}")
        _validar_contrato("503", rel503, nomes_validos)

        # 3) timeout → também transitório: re-tenta e cai no fallback após esgotar.
        print(f"\n=== timeout ({tentativas_esperadas} tentativas → fallback) ===")
        cont = _patch_contando(ERRO_TIMEOUT)
        rel_to = gerar_relatorio_financeiro(_perfil("avancado"), TITULOS)
        check(cont["n"] == tentativas_esperadas, "timeout.retry_ate_fallback", f"chamadas={cont['n']}")
        _validar_contrato("timeout", rel_to, nomes_validos)

        # 4) QUALIDADE do fallback nível INTERMEDIÁRIO
        print("\n=== qualidade do fallback (intermediário) ===")
        _patch_contando(ERRO_QUOTA_DIARIA)
        relm = gerar_relatorio_financeiro(_perfil("intermediario"), TITULOS)
        analise = relm["analise_macroeconomica"].lower()
        termos = ["ipca", "selic", "inflação", "vencimento", "liquidez", "horizonte", "moderado", "retorno"]
        achados = [t for t in termos if t in analise]
        check(len(achados) >= 4, "intermediario.analise_robusta",
              f"termos_achados={achados}")
        check("5,30%" in relm["analise_macroeconomica"] and "13,75%" in relm["analise_macroeconomica"],
              "intermediario.cita_ipca_e_selic_focus")
        estr = relm["estrategia_recomendada"]
        check(TITULOS[0]["nome"] in estr, "intermediario.estrategia_cita_vencedor",
              f"estrategia[:120]={estr[:120]}")
        riscos = relm["riscos_pontos_atencao"].lower()
        check("marcação a mercado" in riscos and "imposto de renda" in riscos and "constante" in riscos,
              "intermediario.riscos_mencionam_limitacoes")
        termos_gloss = {g["termo"].lower() for g in relm["glossario"]}
        check({"ipca", "selic", "retorno real", "vencimento", "marcação a mercado"} <= termos_gloss,
              "intermediario.glossario_termos_uteis", f"termos={termos_gloss}")
    finally:
        assistente_ia.client.models.generate_content = original
        assistente_ia.GEMINI_MODE = modo_original

    # 5) endpoint /api/analise com Gemini em quota → HTTP 200 + tela completa
    print("\n=== endpoint /api/analise (Gemini em quota) ===")
    from fastapi.testclient import TestClient
    import app as app_module
    assistente_ia.GEMINI_MODE = "real"
    cont_endpoint = _patch_contando(ERRO_QUOTA_DIARIA)
    client = TestClient(app_module.app)

    page = client.get("/principal.html")
    check(page.status_code == 200, "pagina.principal_http200", f"status={page.status_code}")
    check(cont_endpoint["n"] == 0, "pagina.zero_chamada_gemini", f"chamadas={cont_endpoint['n']}")

    resp = client.post("/api/analise", json={
        "valorInicial": 20000, "aporteMensal": 800, "objetivo": "bem",
        "tempo_investimento": 4, "unidade_tempo": "anos", "conhecimento": "intermediario",
    })
    check(resp.status_code == 200, "endpoint.http200", f"status={resp.status_code}")
    body = resp.json()
    est = body.get("relatorio_estruturado", {})
    for c in CAMPOS_OBRIG:
        check(bool(est.get(c)), f"endpoint.estruturado.{c}")
    md = body.get("relatorio_markdown", "")
    for secao in ("ANÁLISE MACROECONÔMICA", "ESTRATÉGIA", "RISCOS", "RANKING", "GLOSSÁRIO"):
        check(secao in md.upper(), f"endpoint.markdown.{secao.split()[0]}")
    proj = body.get("dados_projecao", {})
    check(bool(proj.get("montante_total")) and bool(proj.get("nome_ativo_vencedor")),
          "endpoint.projecao_e_vencedor")
    rk = est.get("ranking_oportunidades", [])
    if rk:
        n1 = rk[0]["nome_ativo"].lower(); venc = proj.get("nome_ativo_vencedor", "").lower()
        check(n1 in venc or venc in n1, "endpoint.pos1_casa_projecao", f"pos1='{n1}' proj='{venc}'")
    # vazamento só na superfície textual (números da projeção contêm '429' por acaso)
    superficie = (md + " " + json.dumps(est, ensure_ascii=False)).lower()
    vazou = [p for p in PROIBIDOS if p in superficie]
    check(not vazou, "endpoint.sem_vazamento_textual", f"vazou={vazou}")

    # 6) Projeção não usa título alucinado quando o nome da IA não casa com o pipeline
    print("\n=== ranking consistente: projeção usa título real do pipeline ===")
    import app as appmod
    titulo_vencedor = {"nome": "Tesouro Prefixado 2029", "indexador": "Prefixado",
                       "taxa_juros": 14.86, "vencimento": "01/01/2029", "anos_vencimento": 2.5}
    ranking_alucinado = [
        {"posicao": 1, "nome_ativo": "Tesouro Selic 2027", "rentabilidade": "Selic + 0,10%",
         "vencimento": "01/03/2027", "ano_vencimento_ativo": 2027,
         "alinhamento_prazo": "x", "papel_carteira": "y"},
        {"posicao": 2, "nome_ativo": "Tesouro IPCA+ 2032", "rentabilidade": "IPCA + 8,46%",
         "vencimento": "15/08/2032", "ano_vencimento_ativo": 2032, "alinhamento_prazo": "a", "papel_carteira": "b"},
    ]
    titulo_resolvido, nome_resolvido = appmod._identificar_vencedor(ranking_alucinado, [titulo_vencedor])
    check(titulo_resolvido["nome"] == "Tesouro Prefixado 2029", "ranking.projecao_usa_pipeline",
          f"titulo={titulo_resolvido['nome']}")
    check(nome_resolvido == "Tesouro Prefixado 2029", "ranking.nome_real_exibido", f"nome={nome_resolvido}")

    # 7) Projeção LIMITADA ao vencimento (70 anos) via endpoint
    print("\n=== projeção limitada ao vencimento (70 anos) ===")
    from fastapi.testclient import TestClient as _TC
    assistente_ia.client.models.generate_content = lambda *a, **k: (_ for _ in ()).throw(
        _FakeErro(ERRO_QUOTA_DIARIA)
    )
    c2 = _TC(appmod.app)
    r70 = c2.post("/api/analise", json={
        "valorInicial": 30000, "aporteMensal": 1000, "objetivo": "render",
        "tempo_investimento": 70, "unidade_tempo": "anos", "conhecimento": "avancado",
    })
    check(r70.status_code == 200, "p70.http200")
    b70 = r70.json()
    proj = b70["dados_projecao"]
    check(b70["alerta_limite"]["excedido"] is True, "p70.alerta_excedido")
    check("meses_anos" in proj and "montante_total" in proj, "p70.series_presentes")
    check(len(proj["meses_anos"]) == len(proj["montante_total"]), "p70.series_alinhadas")
    check(len(proj["meses_anos"]) == proj["total_meses"] + 1, "p70.pontos_total_meses")
    check(proj["montante_final"] >= proj["capital_final"] - 0.01, "p70.montante_coerente")

    # 7b) Modelo Gemini: default do CÓDIGO = gemini-3.1-flash-lite, configurável por GEMINI_MODEL.
    #     Validamos o DEFAULT em subprocesso limpo (sem .env, sem env), e não o valor
    #     carregado em runtime — que legitimamente reflete o override do .env (ex.: o
    #     operador pode trocar via GEMINI_MODEL quando precisar migrar de modelo).
    print("\n=== modelo Gemini configurável ===")
    import subprocess
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Rodamos a partir de um cwd NEUTRO (tempfile) com PYTHONPATH=raiz para que
    # load_dotenv() NÃO encontre o .env do projeto — só assim medimos o default
    # embutido no código, independentemente do override de .env.
    import tempfile
    env_modelo_default = {**os.environ, "PYTHONPATH": raiz, "RENDE_IA_GEMINI_MODE": "mock"}
    env_modelo_default.pop("GEMINI_MODEL", None)
    out_default = subprocess.run(
        [sys.executable, "-c", "import assistente_ia as a; print(a.MODELO)"],
        env=env_modelo_default, cwd=tempfile.gettempdir(), capture_output=True, text=True,
    )
    check(out_default.stdout.strip().endswith("gemini-3.1-flash-lite"), "modelo.default_3_1_flash_lite",
          f"stdout={out_default.stdout.strip()!r}")
    check("gemini-2.0-flash" not in out_default.stdout, "modelo.default_nao_eh_2_0_flash")
    out = subprocess.run(
        [sys.executable, "-c", "import assistente_ia as a; print(a.MODELO)"],
        env={**os.environ, "GEMINI_MODEL": "gemini-1.5-flash", "RENDE_IA_GEMINI_MODE": "mock"},
        cwd=raiz, capture_output=True, text=True,
    )
    check("gemini-1.5-flash" in out.stdout, "modelo.respeita_env_GEMINI_MODEL",
          f"stdout={out.stdout.strip()!r}")

    env_default = {**os.environ, "PYTHON_DOTENV_DISABLED": "1"}
    env_default.pop("RENDE_IA_GEMINI_MODE", None)
    out_modo = subprocess.run(
        [sys.executable, "-c", "import assistente_ia as a; print(a.GEMINI_MODE)"],
        env=env_default, cwd=raiz, capture_output=True, text=True,
    )
    check(out_modo.stdout.strip().endswith("real"), "modo.default_real_sem_env_sem_dotenv",
          f"stdout={out_modo.stdout.strip()!r}")

    src = open(os.path.join(raiz, "assistente_ia.py"), encoding="utf-8").read()
    check("model=modelo" in src and "modelo_gemini_configurado()" in src, "modelo.call_site_usa_modelo_configurado")
    check("DEFAULT_GEMINI_MODEL = \"gemini-3.1-flash-lite\"" in src and "MODELO = os.getenv(\"GEMINI_MODEL\", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL" in src,
          "modelo.fonte_unica_env")
    check("gemini-2.0-flash" not in src and "gemini-2.5-flash" not in src, "modelo.antigos_nao_hardcoded_no_assistente")

    # 8) Página principal é servida sem tocar Gemini
    print("\n=== página principal estática ===")
    before = cont_endpoint["n"]
    rr = c2.get("/principal.html")
    check(rr.status_code == 200, "principal.status_200", f"status={rr.status_code}")
    check(cont_endpoint["n"] == before, "principal.sem_chamada_gemini", f"antes={before} depois={cont_endpoint['n']}")

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — 429 não re-tenta, fallback é rico e nada técnico vaza.")


if __name__ == "__main__":
    main()
