import os
import json
import asyncio

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from apscheduler.schedulers.background import BackgroundScheduler

from classificador_perfil import classificar_perfil
from pipeline_quantitativo import (
    analisar_portfolio,
    projecao_juros_compostos,
    _compor_taxa_nominal_anual,
    _IPCA_PROJETADO_FALLBACK,
    _SELIC_PROJETADA_DEFAULT,
)
import assistente_ia
from assistente_ia import gerar_relatorio_financeiro, montar_relatorio_markdown, GeminiObrigatorioError
from banco_dados import atualizar_banco_tesouro, contar_titulos_no_banco
import usage_limits
from gerador_graficos import grafico_alocacao

app = FastAPI(
    title="RENDE AI",
    description="API de recomendação de renda fixa com ML + Gemini",
    version="1.0.0",
)

# Origens permitidas: em produção o frontend é servido pela MESMA origem
# (StaticFiles em "/"), então CORS praticamente não é exercitado pelo browser.
# Ainda assim mantemos uma allowlist restritiva como hardening — sobrescrevível
# por RENDE_IA_CORS_ORIGINS (CSV) para dev/staging sem editar código.
_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "RENDE_IA_CORS_ORIGINS",
        "https://rende-ia.com.br,https://www.rende-ia.com.br",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def desativar_cache_assets_estaticos(request: Request, call_next):
    response = await call_next(request)
    caminho = request.url.path

    if caminho in {"/", "/principal.html", "/script.js", "/styles.css"} or caminho.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# ── Agendamento da atualização diária do banco ────────────────────────────────

def _env_bool(nome: str, padrao: str = "false") -> bool:
    return str(os.getenv(nome, padrao)).strip().lower() in {"1", "true", "yes", "sim", "on"}


_DB_SCHEDULER_ENABLED = not _env_bool("RENDE_IA_DISABLE_DB_SCHEDULER")
_DB_BOOTSTRAP_ON_EMPTY = not _env_bool("RENDE_IA_DISABLE_DB_BOOTSTRAP")
_DB_UPDATE_HOUR = int(os.getenv("RENDE_IA_DB_UPDATE_HOUR", "2") or "2")
_DB_UPDATE_MINUTE = int(os.getenv("RENDE_IA_DB_UPDATE_MINUTE", "0") or "0")
_DB_UPDATE_TZ = os.getenv("TZ", "America/Belem")
_DB_UPDATE_JOB_ID = "atualizar_tesouro_direto_diario"
_DB_BOOTSTRAP_JOB_ID = "atualizar_tesouro_direto_bootstrap"
_db_scheduler = BackgroundScheduler(timezone=_DB_UPDATE_TZ)


def _executar_atualizacao_banco_agendada() -> None:
    print("[Scheduler] Atualização diária do Tesouro Direto iniciada.")
    try:
        total = atualizar_banco_tesouro()
        print(f"[Scheduler] Atualização diária do Tesouro Direto concluída | titulos={total}")
    except Exception as exc:
        print(f"[Scheduler] Falha ao atualizar banco do Tesouro Direto: {type(exc).__name__}: {exc}")


@app.on_event("startup")
def iniciar_agendador_banco() -> None:
    if not _DB_SCHEDULER_ENABLED:
        print("[Scheduler] Atualização diária do banco desativada por RENDE_IA_DISABLE_DB_SCHEDULER.")
        return

    if _db_scheduler.get_job(_DB_UPDATE_JOB_ID) is None:
        _db_scheduler.add_job(
            _executar_atualizacao_banco_agendada,
            trigger="cron",
            hour=_DB_UPDATE_HOUR,
            minute=_DB_UPDATE_MINUTE,
            id=_DB_UPDATE_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if not _db_scheduler.running:
        _db_scheduler.start()

    print(
        "[Scheduler] Atualização diária do banco configurada | "
        f"horario={_DB_UPDATE_HOUR:02d}:{_DB_UPDATE_MINUTE:02d} | timezone={_DB_UPDATE_TZ}"
    )

    if _DB_BOOTSTRAP_ON_EMPTY:
        total_titulos = contar_titulos_no_banco()
        if total_titulos == 0:
            _db_scheduler.add_job(
                _executar_atualizacao_banco_agendada,
                trigger="date",
                id=_DB_BOOTSTRAP_JOB_ID,
                replace_existing=True,
                max_instances=1,
            )
            print("[Scheduler] Banco vazio detectado; atualização inicial disparada em background.")
        else:
            print(f"[Scheduler] Banco já possui títulos | titulos={total_titulos}")


@app.on_event("shutdown")
def encerrar_agendador_banco() -> None:
    if _db_scheduler.running:
        _db_scheduler.shutdown(wait=False)
        print("[Scheduler] Agendador do banco encerrado.")


# ── Schema de entrada ──────────────────────────────────────────────────────────

class PerfilRequest(BaseModel):
    valorInicial: float = Field(..., ge=0, description="Capital inicial em R$")
    aporteMensal: float = Field(0.0, ge=0, description="Aporte mensal em R$ (0 se não houver)")
    objetivo: str = Field(..., description="'reserva' | 'render' | 'bem' | 'juros'")
    # Horizonte de investimento — captura EXATA (substituiu o bucket discreto
    # 'less1'/'1to3'/'3to5'/'more5'). O backend converte para meses e usa esse
    # valor diretamente no eixo X do gráfico (sem cap de 10 anos).
    tempo_investimento: int = Field(..., ge=1, description="Quantidade do horizonte de investimento")
    unidade_tempo: str = Field(..., description="'meses' | 'anos'")
    conhecimento: str = Field(..., description="'iniciante' | 'intermediario' | 'avancado'")


def _total_meses(tempo: int, unidade: str) -> int:
    """Conversão única do horizonte do usuário para meses."""
    return int(tempo) * 12 if unidade == "anos" else int(tempo)


def _derivar_prazo_bucket(total_meses: int) -> str:
    """
    Mapeia o tempo exato (em meses) para o bucket categórico que o
    classificador ML (RandomForest) usa como feature. Preserva o modelo
    treinado sem precisar de retreinamento.
    """
    if total_meses < 12:   return "less1"
    if total_meses < 36:   return "1to3"
    if total_meses < 60:   return "3to5"
    return "more5"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "online", "versao": "1.0.0"}


# ── Dedupe de análises idênticas concorrentes ─────────────────────────────────
# Se o mesmo payload chega 2x simultaneamente (ex.: duplo clique que escapou do
# guard do frontend, ou reload do Uvicorn), só UMA executa o pipeline+Gemini; a(s)
# outra(s) aguardam e reaproveitam o mesmo resultado — zero chamadas Gemini extras.
import hashlib
import uuid

_analises_em_andamento: dict[str, "asyncio.Future"] = {}
_dedupe_lock = asyncio.Lock()

# ── Limite de tentativas REAIS ao Gemini POR USUÁRIO/SESSÃO ────────────────────
# Só vale quando RENDE_IA_REQUIRE_GEMINI=true (IA obrigatória). Identificação por
# cookie de sessão; persistência em SQLite próprio (usage_limits). Não é global:
# cada session_id tem sua própria cota dentro da janela.
_COOKIE_SESSAO = "rende_ia_session_id"
_MAX_REAL = int(os.getenv("RENDE_IA_REQUIRE_GEMINI_MAX_REAL_ATTEMPTS_PER_USER", "5") or "5")
_WINDOW = int(os.getenv("RENDE_IA_REQUIRE_GEMINI_ATTEMPT_WINDOW", "86400") or "86400")


def _chave_payload(req: "PerfilRequest") -> str:
    bruto = json.dumps(req.model_dump(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _resolver_session(request: Request | None) -> tuple[str, bool]:
    """Devolve (session_id, novo). Usa o cookie existente ou gera um UUID novo."""
    sid = request.cookies.get(_COOKIE_SESSAO) if request is not None else None
    if sid:
        return sid, False
    return uuid.uuid4().hex, True


def _hash_curto(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8]


def _set_cookie(alvo, session_id: str) -> None:
    """Aplica o cookie de sessão num Response/JSONResponse (httponly, same-site)."""
    if alvo is not None:
        alvo.set_cookie(_COOKIE_SESSAO, session_id, max_age=_WINDOW,
                        httponly=True, samesite="lax")


def _limite_ativo() -> bool:
    return assistente_ia._require_gemini_atual() and assistente_ia._modo_gemini_atual() == "real"


def _resposta_limite(session_id: str, hsh: str, uso: dict):
    print(f"[Gemini] Limite por usuário atingido | session={hsh} | tentativa={uso['tentativa']}/{uso['max']}")
    resp = JSONResponse(
        status_code=429,
        content={
            "erro": True,
            "tipo": "limite_usuario",
            "mensagem": ("Você atingiu o limite temporário de análises com IA. "
                         "Tente novamente mais tarde."),
            "origem_relatorio": "limite_usuario",
        },
    )
    _set_cookie(resp, session_id)
    return resp


@app.post("/api/analise")
async def analisar(req: PerfilRequest, request: Request = None, response: Response = None):
    """Endpoint público: sessão por cookie + limite por usuário (quando IA obrigatória)
    + dedupe de requisições idênticas em voo."""
    session_id, _ = _resolver_session(request)
    hsh = _hash_curto(session_id)
    _set_cookie(response, session_id)  # garante o cookie em respostas dict (sucesso)

    chave = _chave_payload(req)
    async with _dedupe_lock:
        fut = _analises_em_andamento.get(chave)
        sou_dono = fut is None
        if sou_dono:
            fut = asyncio.get_event_loop().create_future()
            _analises_em_andamento[chave] = fut

    if not sou_dono:
        print("[API] Análise idêntica já em andamento — reaproveitando resultado (sem nova chamada Gemini).")
        return await fut

    try:
        # Limite por usuário — só no modo IA obrigatória + real, só para o dono do
        # dedupe (duplicatas concorrentes não consomem tentativa extra).
        if _limite_ativo():
            uso = usage_limits.consumir(session_id, _MAX_REAL, _WINDOW)
            if not uso["permitido"]:
                resultado = _resposta_limite(session_id, hsh, uso)
                if not fut.done():
                    fut.set_result(resultado)
                return resultado
            print(f"[Gemini] IA obrigatória ativa | session={hsh} | tentativa={uso['tentativa']}/{uso['max']}")

        resultado = await _executar_analise(req)
        _set_cookie(resultado if isinstance(resultado, JSONResponse) else response, session_id)
        if not fut.done():
            fut.set_result(resultado)
        return resultado
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        async with _dedupe_lock:
            _analises_em_andamento.pop(chave, None)


async def _executar_analise(req: PerfilRequest):
    """
    Pipeline completo de análise:
      1. Classificação de perfil     → Scikit-learn (RandomForest)
      2. Análise quantitativa        → Pandas + NumPy
      3. Relatório IA                → Google Gemini Flash Lite
      4. Gráficos                    → Matplotlib (base64 PNG)
    """

    # 1 ── Classificação de perfil (ML)
    #      Derivamos o bucket de prazo a partir do tempo exato — o classificador
    #      continua recebendo o feature categórico que foi usado no treino, mas
    #      a fonte da verdade do horizonte (tempo_investimento + unidade) flui
    #      pelo perfil_ml até a projeção do gráfico e o prompt da IA.
    total_meses_user = _total_meses(req.tempo_investimento, req.unidade_tempo)
    prazo_bucket = _derivar_prazo_bucket(total_meses_user)

    payload_ml = {**req.model_dump(), "prazo": prazo_bucket}
    perfil_ml = classificar_perfil(payload_ml)
    perfil_ml["tempo_investimento"] = req.tempo_investimento
    perfil_ml["unidade_tempo"] = req.unidade_tempo
    perfil_ml["total_meses"] = total_meses_user

    # 2 ── Pipeline quantitativo
    resultado_pipeline = analisar_portfolio(perfil_ml)
    if "erro" in resultado_pipeline:
        raise HTTPException(
            status_code=503,
            detail=resultado_pipeline["erro"],
        )

    # Metadados temporais (ano atual, ano alvo do cliente, maior vencimento
    # disponível na base) — injetados no perfil para que o prompt do Gemini
    # tenha ground-truth determinístico e aplique as regras de correspondência
    # temporal + fallback do limite do Tesouro.
    perfil_ml["ano_atual"] = resultado_pipeline.get("ano_atual")
    perfil_ml["ano_alvo_resgate"] = resultado_pipeline.get("ano_alvo_resgate")
    perfil_ml["vencimento_max_disponivel"] = resultado_pipeline.get("vencimento_max_disponivel")

    # 3 ── Relatório Gemini estruturado (executa em thread para não bloquear o
    #       event loop durante os sleeps do exponential backoff em caso de 503).
    #       Agora retorna dict com analise_macroeconomica, estrategia_recomendada
    #       e ranking_oportunidades — graças ao response_schema do Gemini Flash.
    modelo_ia = assistente_ia.modelo_gemini_configurado()
    print(f"[Gemini] /api/analise iniciando relatório IA | modelo={modelo_ia}")
    try:
        relatorio_ia = await asyncio.to_thread(
            gerar_relatorio_financeiro,
            perfil_investidor=perfil_ml,
            titulos_rankeados=resultado_pipeline["titulos_recomendados"],
        )
        origem_relatorio = relatorio_ia.get("_origem") if isinstance(relatorio_ia, dict) else "desconhecida"
        print(f"[Gemini] /api/analise relatório IA recebido | modelo={modelo_ia} | origem={origem_relatorio}")
    except GeminiObrigatorioError as e:
        # IA obrigatória (RENDE_IA_REQUIRE_GEMINI=true) e a IA real falhou:
        # NÃO servir fallback — devolver erro controlado e amigável (HTTP 503).
        # O motivo técnico já foi logado de forma sanitizada em assistente_ia.
        return JSONResponse(
            status_code=503,
            content={
                "erro": True,
                "tipo": "ia_indisponivel",
                "mensagem": ("Não foi possível gerar a análise com IA neste momento. "
                             "Tente novamente em alguns instantes."),
                "origem_relatorio": "erro_ia_obrigatoria",
            },
        )

    # 4 ── Vencedor da IA → projeção do gráfico
    #      A IA decide o ranking; o backend localiza posicao=1, casa o nome com
    #      o pipeline (que tem taxa_juros + anos_vencimento) e recalcula a
    #      projeção em cima do título VENCEDOR (não do top1 quantitativo).
    titulo_vencedor, nome_vencedor = _identificar_vencedor(
        relatorio_ia.get("ranking_oportunidades") or [],
        resultado_pipeline["titulos_recomendados"],
    )

    # ── Composição Fisher antes do loop de juros compostos ────────────────────
    # A taxa_juros do DB é a taxa CONTRATADA do título:
    #   • IPCA+   → cupom REAL  (precisa compor com IPCA projetado)
    #   • Selic+  → SPREAD      (precisa compor com Selic projetada)
    #   • Prefix. → NOMINAL     (usa direto)
    # _compor_taxa_nominal_anual aplica Fisher por tipo. O IPCA vem do BCB
    # Focus (cacheado em pipeline_quantitativo) — fallback offline garantido.
    ipca_focus = float(resultado_pipeline.get("ipca_focus_pct") or _IPCA_PROJETADO_FALLBACK)
    taxa_nominal_vencedor = _compor_taxa_nominal_anual(
        nome=str(titulo_vencedor["nome"]),
        indexador=str(titulo_vencedor["indexador"]),
        taxa_titulo=float(titulo_vencedor["taxa_juros"]),
        ipca_pct=ipca_focus,
        selic_projetada_pct=_SELIC_PROJETADA_DEFAULT,
    )

    # Projeção do gráfico vai EXATAMENTE até o horizonte digitado pelo usuário.
    # Sem cap de 10 anos: se ele pediu 240 meses (20 anos), o eixo X termina lá.
    projecao_vencedor = projecao_juros_compostos(
        principal=req.valorInicial,
        taxa_anual_pct=taxa_nominal_vencedor,
        tempo_investimento=req.tempo_investimento,
        unidade_tempo=req.unidade_tempo,
        aporte_mensal=req.aporteMensal,
    )

    dados_projecao = {
        **projecao_vencedor,
        "nome_ativo_vencedor": nome_vencedor,
    }

    # ── Trava de usabilidade: 2 gradações de descasamento de prazo ────────────
    # Compara o horizonte EXATO do usuário (em meses) contra DUAS referências:
    #
    #   tipo "tesouro_limit"      → horizonte > maior vencimento DO BANCO INTEIRO
    #                               (teto institucional do Tesouro Direto, hoje
    #                               ~58.5 anos = Renda+ 2065). Cenário "absurdo":
    #                               nenhum título do mundo cobre o prazo pedido.
    #
    #   tipo "recomendacao_curta" → horizonte > vencimento do título QUE A IA
    #                               ESCOLHEU para este perfil específico, mesmo
    #                               estando dentro do teto institucional. Cobre o
    #                               caso onde o filtro de perfil + ranking da IA
    #                               restringe o cliente a títulos mais curtos que
    #                               o horizonte digitado (ex.: conservador + 20
    #                               anos recebendo Educa+ 2033 = 7 anos).
    #
    # A linha vertical do gráfico vai EM CIMA do vencimento do título efetivamente
    # recomendado (titulo_vencedor) em AMBOS os casos — esse é o ponto onde o
    # investimento REAL do cliente se encerra, independente do motivo.
    venc_max               = resultado_pipeline.get("vencimento_max_disponivel") or {}
    prazo_max_meses_banco  = int(venc_max.get("meses_ate_hoje") or 0)
    anos_winner            = float(titulo_vencedor.get("anos_vencimento") or 0)
    meses_winner           = max(int(round(anos_winner * 12)), 1)

    TOLERANCIA_MESES = 12  # < 1 ano de gap não dispara alerta (alinhamento aceitável)
    prazo_excede_tesouro     = total_meses_user > prazo_max_meses_banco > 0
    prazo_excede_recomendado = total_meses_user - meses_winner > TOLERANCIA_MESES

    if prazo_excede_tesouro:
        tipo_alerta = "tesouro_limit"
    elif prazo_excede_recomendado:
        tipo_alerta = "recomendacao_curta"
    else:
        tipo_alerta = None

    alerta_limite = {
        "excedido":                    tipo_alerta is not None,
        "tipo":                        tipo_alerta,
        # Posição EXATA da linha vermelha no eixo X (em meses).
        # Sempre o vencimento do título recomendado — não do teto do Tesouro.
        "linha_vertical_meses":        meses_winner,
        "prazo_usuario_meses":         total_meses_user,
        "anos_a_descoberto":           round(max(0, total_meses_user - meses_winner) / 12, 1),
        # Detalhes do título RECOMENDADO (alimenta a mensagem do toast em recomendacao_curta)
        "titulo_recomendado":          nome_vencedor,
        "vencimento_recomendado_anos": round(meses_winner / 12, 1),
        "vencimento_recomendado_data": titulo_vencedor.get("vencimento"),
        # Detalhes do teto INSTITUCIONAL (alimenta a mensagem do toast em tesouro_limit)
        "prazo_max_anos":              venc_max.get("anos_ate_hoje"),
        "data_vencimento_max":         venc_max.get("data"),
        "titulo_mais_longo":           venc_max.get("titulo"),
    }

    # 5 ── Gráfico de alocação (PNG Matplotlib) + Markdown final montado a
    #      partir do JSON estruturado (posições dinâmicas vindas da IA)
    g_alocacao = grafico_alocacao(resultado_pipeline["titulos_recomendados"])
    relatorio_markdown = montar_relatorio_markdown(relatorio_ia)

    return {
        "perfil_ml": perfil_ml,
        "analise_quantitativa": resultado_pipeline,
        "relatorio_markdown": relatorio_markdown,
        "relatorio_estruturado": relatorio_ia,
        # Origem interna da resposta: ia_real | fallback_cota | fallback_cooldown |
        # fallback_schema | fallback_erro | modo_fallback | mock. Para logs/telemetria
        # no frontend — não altera a UI.
        "origem_relatorio": relatorio_ia.get("_origem", "ia_real"),
        "dados_projecao": dados_projecao,
        "alerta_limite": alerta_limite,
        "grafico_alocacao_b64": g_alocacao,
    }


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _identificar_vencedor(ranking_ia: list, titulos_pipeline: list) -> tuple[dict, str]:
    """
    A IA decide a ordem; o backend resolve o casamento NOME ↔ DADOS NUMÉRICOS.

    1. Tenta achar item com posicao=1 no ranking da IA.
    2. Casa o `nome_ativo` (case-insensitive, com fallback de substring) contra
       a lista do pipeline — que carrega taxa_juros e anos_vencimento.
    3. Em qualquer falha (IA sem ranking, nome não casa), faz fallback
       transparente para o top1 quantitativo do pipeline.

    Retorna: (titulo_dict_do_pipeline, nome_a_exibir)
    """
    vencedor_ia = next((r for r in ranking_ia if r.get("posicao") == 1), None)

    if vencedor_ia and titulos_pipeline:
        nome_alvo = (vencedor_ia.get("nome_ativo") or "").strip().lower()
        if nome_alvo:
            for t in titulos_pipeline:
                nome_t = t["nome"].lower()
                if nome_t == nome_alvo or nome_alvo in nome_t or nome_t in nome_alvo:
                    return t, vencedor_ia["nome_ativo"]

    # Fallback: top1 do pipeline (mantém a UX funcional quando a IA falha)
    fallback = titulos_pipeline[0]
    return fallback, fallback["nome"]


# ── Frontend estático (deve vir APÓS todas as rotas /api/*) ───────────────────

app.mount("/", StaticFiles(directory="client", html=True), name="static")


# ── Ponto de entrada direto ───────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
