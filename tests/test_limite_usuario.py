"""
Limite de tentativas REAIS ao Gemini POR USUÁRIO/SESSÃO (modo IA obrigatória).

Valida: cota por session_id (não global), reset por janela, bloqueio na 6ª, usuário B
independente do A, sucesso=ia_real, falha sem fallback, e flag false sem limite.

Usa SQLite temporário e monkeypatch — não consome Gemini real.

    venv/bin/python tests/test_limite_usuario.py
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usage_limits

# Redireciona o banco de uso para um arquivo temporário ANTES de tocar no app.
_TMP_DB = os.path.join(tempfile.gettempdir(), f"rende_ia_usage_test_{os.getpid()}.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
usage_limits.DB_PATH = _TMP_DB

import assistente_ia
import app as app_module
from fastapi.testclient import TestClient

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
            {"posicao": 1, "nome_ativo": "Tesouro Prefixado 2029", "rentabilidade": "x",
             "vencimento": "01/01/2029", "ano_vencimento_ativo": 2029,
             "alinhamento_prazo": "x", "papel_carteira": "x"}],
        "glossario": [{"termo": "IPCA", "explicacao": "y"}],
    })
    return r


PAYLOAD = {"valorInicial": 20000, "aporteMensal": 800, "objetivo": "bem",
           "tempo_investimento": 4, "unidade_tempo": "anos", "conhecimento": "intermediario"}


def main():
    # ── A) Unidade: módulo usage_limits ─────────────────────────────────────────
    print("\n=== A) módulo: consome 5, bloqueia 6ª, reset por janela ===")
    sid = "sessaoA"
    usage_limits.resetar(sid)
    permitidos = [usage_limits.consumir(sid, 5, 86400)["permitido"] for _ in range(5)]
    check(all(permitidos), "mod.cinco_permitidos", f"{permitidos}")
    sexta = usage_limits.consumir(sid, 5, 86400)
    check(sexta["permitido"] is False and sexta["restante"] == 0, "mod.sexta_bloqueada")
    # usuário B independente
    usage_limits.resetar("sessaoB")
    check(usage_limits.consumir("sessaoB", 5, 86400)["permitido"] is True, "mod.usuarioB_independente")
    # janela expirada (window=0) reseta
    check(usage_limits.consumir(sid, 5, 0)["permitido"] is True, "mod.janela_expirada_reseta")

    # ── Configura modo IA obrigatória + real, mock de sucesso ───────────────────
    assistente_ia.GEMINI_MODE = "real"
    assistente_ia.REQUIRE_GEMINI = True
    app_module._MAX_REAL = 5
    app_module._WINDOW = 86400
    chamadas = {"n": 0}

    def _gen_ok(*a, **k):
        chamadas["n"] += 1
        return _resp_ok()
    assistente_ia.client.models.generate_content = _gen_ok

    # ── B) Endpoint: usuário A faz 5 reais e é bloqueado na 6ª ───────────────────
    print("\n=== B) endpoint: A faz 5, bloqueado na 6ª (sem Gemini na 6ª) ===")
    cliA = TestClient(app_module.app)
    sidA = None
    for i in range(1, 6):
        r = cliA.post("/api/analise", json=PAYLOAD)
        if sidA is None:
            sidA = r.cookies.get("rende_ia_session_id")
        check(r.status_code == 200, f"A.req{i}_http200", f"status={r.status_code}")
        check(r.json().get("origem_relatorio") == "ia_real", f"A.req{i}_ia_real")
    check(chamadas["n"] == 5, "A.cinco_chamadas_reais", f"n={chamadas['n']}")
    check(sidA is not None, "A.recebeu_cookie_sessao")

    r6 = cliA.post("/api/analise", json=PAYLOAD)
    check(r6.status_code == 429, "A.sexta_http429", f"status={r6.status_code}")
    b6 = r6.json()
    check(b6.get("tipo") == "limite_usuario", "A.sexta_tipo_limite")
    check(b6.get("origem_relatorio") == "limite_usuario", "A.sexta_origem_limite")
    check("limite" in (b6.get("mensagem", "")).lower(), "A.sexta_mensagem_amigavel")
    check(chamadas["n"] == 5, "A.sexta_nao_chama_gemini", f"n={chamadas['n']}")
    # nada de fallback determinístico
    check("modo determinístico" not in json.dumps(b6, ensure_ascii=False).lower(), "A.sexta_sem_fallback")

    # ── C) Usuário B (sessão diferente) ainda tem suas 5 — limite NÃO é global ──
    print("\n=== C) usuário B independente (limite não é global) ===")
    cliB = TestClient(app_module.app)  # jar de cookies separado
    rB = cliB.post("/api/analise", json=PAYLOAD)
    check(rB.status_code == 200, "B.primeira_http200", f"status={rB.status_code}")
    check(rB.json().get("origem_relatorio") == "ia_real", "B.primeira_ia_real")
    sidB = rB.cookies.get("rende_ia_session_id")
    check(sidB and sidB != sidA, "B.sessao_diferente_de_A", f"A={sidA and sidA[:6]} B={sidB and sidB[:6]}")

    # ── D) Falha 429 de A não afeta B ───────────────────────────────────────────
    print("\n=== D) 429 do A não bloqueia B ===")
    usage_limits.resetar(sidA); usage_limits.resetar(sidB)
    chamadas["n"] = 0
    def _gen_429(*a, **k):
        chamadas["n"] += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED PerDay FreeTier")
    assistente_ia.client.models.generate_content = _gen_429
    # A consome 2 tentativas que falham (erro IA obrigatória, 503) — contam como tentativas
    rA1 = cliA.post("/api/analise", json=PAYLOAD)
    rA2 = cliA.post("/api/analise", json=PAYLOAD)
    check(rA1.status_code == 503 and rA2.status_code == 503, "D.A_falha_503_sem_fallback")
    # B continua com sua cota (volta a sucesso)
    assistente_ia.client.models.generate_content = _gen_ok
    chamadas["n"] = 0
    rB2 = cliB.post("/api/analise", json=PAYLOAD)
    check(rB2.status_code == 200 and rB2.json().get("origem_relatorio") == "ia_real", "D.B_continua_funcionando")

    # ── E) flag false → SEM limite, fallback normal ─────────────────────────────
    print("\n=== E) RENDE_IA_REQUIRE_GEMINI=false → sem limite, com fallback ===")
    assistente_ia.REQUIRE_GEMINI = False
    assistente_ia.client.models.generate_content = _gen_429  # 429 diária
    cliC = TestClient(app_module.app)
    # mesmo após várias, nunca bloqueia por limite; cai em fallback
    ultimo = None
    for _ in range(7):
        ultimo = cliC.post("/api/analise", json=PAYLOAD)
    check(ultimo.status_code == 200, "false.sem_http429", f"status={ultimo.status_code}")
    check(ultimo.json().get("origem_relatorio") == "fallback_cota", "false.cai_em_fallback")

    # ── F) frontend: trata limite + IA indisponível + mantém guard ──────────────
    print("\n=== F) frontend trata limite/indisponível ===")
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(raiz, "client", "script.js"), encoding="utf-8").read()
    check('err.tipo === "limite_usuario"' in js, "front.trata_tipo_limite")
    check("Limite de análises" in js, "front.titulo_limite")
    check("_analiseEmAndamento" in js and "btn.disabled = true" in js, "front.mantem_guard")

    try:
        os.remove(_TMP_DB)
    except OSError:
        pass

    print("\n############ RESUMO ############")
    if falhas:
        print(f"{len(falhas)} CHECK(S) FALHARAM:")
        for f in falhas:
            print("  - " + f)
        raise SystemExit(1)
    print("TODOS OS CHECKS PASSARAM — limite por usuário (não global), reset por janela e sem fallback no modo obrigatório.")


if __name__ == "__main__":
    main()
