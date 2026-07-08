import os
import sqlite3
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import numpy as np
import pandas as pd

_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tesouro_direto.db")


def carregar_titulos() -> pd.DataFrame:
    colunas = ["nome", "indexador", "taxa_juros", "preco_unitario", "vencimento"]
    try:
        with sqlite3.connect(_DB) as conn:
            df = pd.read_sql_query(
                "SELECT nome, indexador, taxa_juros, preco_unitario, vencimento FROM titulos",
                conn,
            )
    except (sqlite3.OperationalError, pd.errors.DatabaseError) as exc:
        print(f"[Banco] Base de títulos indisponível: {type(exc).__name__}: {exc}")
        return pd.DataFrame(columns=colunas)

    if df.empty:
        return df

    df["vencimento_dt"] = pd.to_datetime(df["vencimento"], format="%d/%m/%Y", errors="coerce")
    hoje = pd.Timestamp.today().normalize()
    df["dias_venc"] = (df["vencimento_dt"] - hoje).dt.days.clip(lower=1)
    df["anos_venc"] = (df["dias_venc"] / 365.25).round(2)
    return df


# ── Premissas macro (Boletim Focus / BACEN) ───────────────────────────────────
# _IPCA_PROJETADO_FALLBACK e _SELIC_PROJETADA_DEFAULT são usados APENAS como
# defesa em profundidade caso a API Olinda do BCB esteja indisponível. O valor
# vigente em produção vem de _buscar_ipca_focus(), atualizado diariamente
# pelo BCB e cacheado por 24h em memória.
_IPCA_PROJETADO_FALLBACK = 4.5    # IPCA anualizado (% a.a.) — fallback offline
_SELIC_PROJETADA_DEFAULT = 10.5   # Selic Meta média projetada (% a.a.)

# ── Cache in-memory da expectativa do Focus ────────────────────────────────────
# Vida útil de 24h: o Focus é divulgado uma vez por dia (segundas 8h30 BRT).
# Não persiste em disco — recriar o cache no boot do servidor é aceitável e
# evita lidar com invalidação cross-process.
_IPCA_CACHE: dict = {"valor": None, "expira_em": 0.0}
_OLINDA_BASE = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/"
    "odata/ExpectativasMercadoAnuais"
)


def _buscar_ipca_focus(ttl_segundos: int = 86_400, timeout: int = 6) -> float:
    """
    Devolve a mediana das expectativas ANUAIS do IPCA do Boletim Focus para
    o ANO ATUAL, em pontos percentuais (ex.: 5.30 = 5,30% a.a.). Consulta a
    API Olinda de Dados Abertos do BCB.

    Estratégia:
      • Cache in-memory com TTL (default 24h). Evita bater na API a cada request.
      • Filtro Focus: baseCalculo=0 (mediana com TODOS os respondentes ativos).
      • Pega o registro MAIS RECENTE para o ano corrente (`$orderby=Data desc`,
        `$top=1`).
      • Sanidade: rejeita valores fora de [0, 30] (proteção contra resposta
        corrompida).

    Fallback (sem cachear, para tentar de novo no próximo request):
      • Falha de rede / HTTP error / timeout
      • Resposta vazia ou sem 'Mediana'
      • Mediana fora do range de sanidade
      Devolve `_IPCA_PROJETADO_FALLBACK` (4.5% a.a.) e loga o motivo.

    Detalhe crítico (URL encoding): a Olinda EXIGE %20 nos espaços do $filter
    — `+` (usado pelo urlencode default) retorna 400 com mensagem enganosa
    "Edm.Boolean and Edm.String are not compatible". Forçamos `quote_via=quote`.
    """
    agora = time.time()
    if _IPCA_CACHE["valor"] is not None and _IPCA_CACHE["expira_em"] > agora:
        return _IPCA_CACHE["valor"]

    ano = datetime.now().year
    params = {
        "$filter":  f"Indicador eq 'IPCA' and DataReferencia eq '{ano}' and baseCalculo eq 0",
        "$orderby": "Data desc",
        "$top":     "1",
        "$format":  "json",
    }
    url = (
        f"{_OLINDA_BASE}?"
        + urllib.parse.urlencode(params, safe="$", quote_via=urllib.parse.quote)
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "RENDE-AI/1.0", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        registros = payload.get("value") or []
        if not registros:
            raise ValueError(f"Focus retornou lista vazia para o ano {ano}")
        mediana = float(registros[0].get("Mediana") or 0)
        if not (0 < mediana < 30):
            raise ValueError(f"Mediana fora do range plausível: {mediana}")
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as e:
        print(
            f"[IPCA Focus] Falha ao consultar Olinda — usando fallback "
            f"{_IPCA_PROJETADO_FALLBACK}%. Motivo: {type(e).__name__}: {e}"
        )
        return _IPCA_PROJETADO_FALLBACK

    _IPCA_CACHE["valor"]     = mediana
    _IPCA_CACHE["expira_em"] = agora + ttl_segundos
    print(f"[IPCA Focus] Mediana {ano} = {mediana:.2f}% a.a. (cacheada por {ttl_segundos//3600}h)")
    return mediana


def _compor_taxa_nominal_anual(
    nome: str,
    indexador: str,
    taxa_titulo: float,
    ipca_pct: float,
    selic_projetada_pct: float = _SELIC_PROJETADA_DEFAULT,
) -> float:
    """
    Devolve a taxa NOMINAL anual em % a.a. a ser aplicada no loop de juros
    compostos do gráfico (`projecao_juros_compostos`). A composição é
    CONDICIONAL ao tipo de indexador — usar a taxa crua do título sem
    compor produziria projeções erradas para IPCA+ e Selic+:

      • IPCA+ (Educa+, Renda+, IPCA+):
          nominal = ((1 + taxa_real/100) · (1 + ipca/100) - 1) · 100
          A taxa contratada do título é o CUPOM REAL (acima da inflação).
          Compomos via Fisher: o investidor recebe cupom real + correção
          monetária do principal pelo IPCA.

      • Selic+:
          nominal = ((1 + selic/100) · (1 + spread/100) - 1) · 100
          A taxa contratada é o SPREAD sobre Selic. Compomos com a Selic
          projetada (também via Fisher para consistência matemática;
          para spreads pequenos o resultado é numericamente próximo da
          simples soma selic + spread, mas a composição é a forma correta).

      • Prefixado:
          nominal = taxa_titulo
          A taxa contratada JÁ é a nominal. Sem composição.

    `nome` + `indexador` desambiguam casos onde o branding mascara o
    indexador (Educa+, Renda+ são IPCA+). Reaproveita `_classificar_indexador`.
    """
    tipo = _classificar_indexador(nome, indexador)
    t = float(taxa_titulo)
    if tipo == "ipca":
        return (((1 + t / 100) * (1 + ipca_pct / 100)) - 1) * 100
    if tipo == "selic":
        return (((1 + selic_projetada_pct / 100) * (1 + t / 100)) - 1) * 100
    return t


def _classificar_indexador(nome: str, indexador: str) -> str:
    """
    Retorna 'ipca' | 'selic' | 'prefixado'.

    Prioriza o campo 'indexador' persistido pelo scraper (fonte oficial),
    com fallback baseado no nome para títulos cujo branding mascara o indexador
    (Educa+, Renda+).
    """
    idx = (indexador or "").strip().lower()
    n   = (nome or "").lower()

    if idx == "ipca" or "ipca+" in n or "educa+" in n or "renda+" in n:
        return "ipca"
    if idx == "selic" or "selic" in n:
        return "selic"
    return "prefixado"


def calcular_retorno_real(
    df: pd.DataFrame,
    inflacao_pct: float = _IPCA_PROJETADO_FALLBACK,
    selic_projetada_pct: float = _SELIC_PROJETADA_DEFAULT,
) -> pd.DataFrame:
    """
    Calcula o retorno real anualizado (% a.a.) com lógica CONDICIONAL por indexador,
    refletindo a matemática financeira correta de cada tipo de título do Tesouro.

    Regras de negócio:
      • IPCA+ (Educa+, Renda+, IPCA+):
            retorno_real = taxa_juros
            (a taxa contratada JÁ É o cupom real, acima da inflação — não se aplica Fisher)

      • Prefixado:
            retorno_real = ((1 + taxa_juros/100) / (1 + inflacao/100) - 1) * 100
            (Fisher: a taxa contratada é nominal; descontamos a inflação projetada)

      • Selic+:
            nominal = selic_projetada + spread (taxa_juros é o spread sobre a Selic)
            retorno_real = ((1 + nominal/100) / (1 + inflacao/100) - 1) * 100
            (Fisher sobre a Selic projetada acrescida do spread)

    Parâmetros:
        inflacao_pct         — IPCA anualizado projetado (% a.a.). Fonte: Boletim Focus.
        selic_projetada_pct  — Selic Meta média projetada (% a.a.). Fonte: Boletim Focus.

    Retorna o DataFrame com a coluna 'retorno_real' populada (arredondada a 4 casas).
    """
    df = df.copy()

    tipo = df.apply(lambda r: _classificar_indexador(r.get("nome"), r.get("indexador")), axis=1)
    taxa = df["taxa_juros"].astype(float)

    # Branches vetorizados — np.select escolhe um valor por linha sem laços Python.
    real_ipca      = taxa
    real_prefixado = (((1 + taxa / 100) / (1 + inflacao_pct / 100)) - 1) * 100
    nominal_selic  = selic_projetada_pct + taxa
    real_selic     = (((1 + nominal_selic / 100) / (1 + inflacao_pct / 100)) - 1) * 100

    df["retorno_real"] = np.select(
        condlist=[tipo == "ipca", tipo == "selic"],
        choicelist=[real_ipca, real_selic],
        default=real_prefixado,
    )
    df["retorno_real"] = df["retorno_real"].round(4)
    return df


def calcular_score_risco(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score [0-1] onde maior valor = maior risco.
    Composição: 60% peso no prazo (duration) + 40% peso na taxa (spread sobre livre de risco).
    """
    df = df.copy()
    anos = df["anos_venc"].values.astype(float)
    taxas = df["taxa_juros"].values.astype(float)

    def min_max(v: np.ndarray) -> np.ndarray:
        rng = v.max() - v.min()
        return (v - v.min()) / rng if rng > 0 else np.zeros_like(v)

    df["score_risco"] = np.round(min_max(anos) * 0.6 + min_max(taxas) * 0.4, 4)
    return df


def projecao_juros_compostos(
    principal: float,
    taxa_anual_pct: float,
    tempo_investimento: int,
    unidade_tempo: str = "meses",
    aporte_mensal: float = 0.0,
) -> dict:
    """
    Projeta a evolução patrimonial mês a mês com juros compostos e aportes mensais,
    devolvendo a série temporal pronta para o gráfico interativo do frontend
    (Chart.js). As três curvas — capital investido, juros acumulados e montante
    total — são calculadas vetorialmente em NumPy.

    O horizonte é convertido em meses na entrada (regra: anos → tempo*12,
    meses → tempo). NÃO existe cap de 10 anos: o array vai EXATAMENTE de 0 ao
    total_meses informado pelo usuário, de modo que o eixo X do gráfico termine
    no limite que ele digitou.
    """
    # ── Conversão de unidade → total_meses ─────────────────────────────────────
    # Esta é a regra de negócio do produto: o que o usuário digitou define
    # exatamente quantos pontos terá o eixo X do gráfico de projeção.
    total_meses = int(tempo_investimento) * 12 if unidade_tempo == "anos" else int(tempo_investimento)
    if total_meses < 1:
        total_meses = 1

    taxa_mensal = (1 + taxa_anual_pct / 100) ** (1 / 12) - 1
    meses = np.arange(0, total_meses + 1, dtype=float)

    montante_principal = principal * (1 + taxa_mensal) ** meses

    if aporte_mensal > 0 and taxa_mensal > 0:
        # Fórmula de anuidade para aportes mensais
        montante_aportes = aporte_mensal * (((1 + taxa_mensal) ** meses - 1) / taxa_mensal)
    else:
        montante_aportes = aporte_mensal * meses

    montante_total = montante_principal + montante_aportes
    capital_investido = principal + aporte_mensal * meses
    juros_acumulados = montante_total - capital_investido

    return {
        "meses_anos": meses.astype(int).tolist(),
        "capital_investido": np.round(capital_investido, 2).tolist(),
        "juros_acumulados": np.round(juros_acumulados, 2).tolist(),
        "montante_total": np.round(montante_total, 2).tolist(),
        "montante_final": float(np.round(montante_total[-1], 2)),
        "capital_final": float(np.round(capital_investido[-1], 2)),
        "juros_totais": float(np.round(juros_acumulados[-1], 2)),
        "taxa_anual_pct": taxa_anual_pct,
        "total_meses": int(total_meses),
        "tempo_investimento": int(tempo_investimento),
        "unidade_tempo": unidade_tempo,
        "aporte_mensal": aporte_mensal,
    }


def _selecionar_titulo_alinhado_prazo(
    df: pd.DataFrame, total_meses_user: int
) -> pd.Series | None:
    """
    Localiza o título cujo vencimento melhor se alinha ao horizonte EXATO do usuário.

    Critério: menor distância em dias entre vencimento_dt e a data-alvo de resgate.
    Empates desempata pelo maior retorno_real.

    Esta função enxerga o UNIVERSO COMPLETO (sem filtro de tolerância) — o objetivo
    é garantir que o LLM tenha sempre pelo menos UMA opção time-aligned no payload,
    mesmo em horizontes longos onde o filtro de risco rejeita todos os Renda+ longos
    para perfis conservadores. A escolha final entre top5 (otimizado por retorno)
    e esta âncora temporal (otimizada por prazo) fica a cargo da IA — que pondera
    prazo × perfil de risco no contexto do <RESTRICAO_DE_PRAZO>.
    """
    if df.empty or total_meses_user <= 0:
        return None
    data_alvo = pd.Timestamp.today().normalize() + pd.Timedelta(days=total_meses_user * 30.4375)
    candidatos = df.copy()
    candidatos["distancia_alvo_dias"] = (candidatos["vencimento_dt"] - data_alvo).dt.days.abs()
    candidatos = candidatos.sort_values(
        ["distancia_alvo_dias", "retorno_real"], ascending=[True, False]
    )
    return candidatos.iloc[0]


def _filtrar_por_tolerancia(df: pd.DataFrame, tolerancia: str) -> pd.DataFrame:
    if tolerancia == "conservador":
        mask = df["score_risco"] < 0.45
    elif tolerancia == "moderado":
        mask = (df["score_risco"] >= 0.3) & (df["score_risco"] <= 0.70)
    else:  # arrojado
        mask = df["score_risco"] > 0.55

    filtrado = df[mask].copy()
    # Fallback: se nenhum título passar no filtro, usa todos
    return filtrado if not filtrado.empty else df.copy()


def analisar_portfolio(perfil: dict) -> dict:
    tolerancia = perfil.get("tolerancia_risco", "conservador")
    valor = float(perfil.get("valor", 10_000))

    df = carregar_titulos()
    if df.empty:
        return {"erro": "Banco de dados vazio. Execute banco_dados.py primeiro."}

    # IPCA live do Boletim Focus (cacheado 24h) — alimenta tanto o retorno real
    # do ranking quanto a composição Fisher da projeção no app.py. Fallback
    # automático para _IPCA_PROJETADO_FALLBACK se a Olinda estiver fora do ar.
    ipca_focus = _buscar_ipca_focus()
    df = calcular_retorno_real(df, inflacao_pct=ipca_focus)
    df = calcular_score_risco(df)

    top5 = (
        _filtrar_por_tolerancia(df, tolerancia)
        .sort_values("retorno_real", ascending=False)
        .head(5)
    )

    # ── Âncora temporal ────────────────────────────────────────────────────────
    # Garante que a IA enxergue o título mais alinhado ao horizonte do usuário,
    # mesmo que o filtro de tolerância o tenha excluído. Caso clássico:
    # conservador + 36 anos — o filtro corta os Renda+ longos por duration alta,
    # mas eles são justamente o que o cliente precisa. Injetamos como 6ª opção
    # e deixamos a IA decidir entre retorno bruto × alinhamento de prazo.
    tempo_user_raw = perfil.get("tempo_investimento")
    unidade_user_raw = (perfil.get("unidade_tempo") or "meses").lower()
    total_meses_user = (
        int(perfil.get("total_meses") or 0)
        or (int(tempo_user_raw) * (12 if unidade_user_raw == "anos" else 1) if tempo_user_raw else 0)
    )

    if total_meses_user > 0:
        titulo_alinhado = _selecionar_titulo_alinhado_prazo(df, total_meses_user)
        if titulo_alinhado is not None and titulo_alinhado["nome"] not in set(top5["nome"]):
            top5 = pd.concat([top5, titulo_alinhado.to_frame().T], ignore_index=True)

    melhor = top5.iloc[0]
    aporte = float(perfil.get("aporteMensal", 0))

    # Projeção quantitativa preliminar — usa o horizonte EXATO do usuário se
    # disponível no perfil; fallback para o vencimento do título quando o
    # endpoint não tiver injetado o tempo (ex.: chamadas de teste isoladas).
    # Esta projeção fica em resultado["projecao"] como informativo: a projeção
    # final do gráfico é recalculada em app.py em cima do VENCEDOR escolhido
    # pela IA, garantindo que o eixo X reflita exatamente o input do usuário.
    # Composição Fisher antes do loop de juros compostos — o `melhor` pode ser
    # IPCA+ ou Selic+, e a taxa_juros crua não é a nominal. Sem isto, a projeção
    # preliminar fica errada para títulos indexados.
    taxa_nominal_melhor = _compor_taxa_nominal_anual(
        nome=str(melhor["nome"]),
        indexador=str(melhor["indexador"]),
        taxa_titulo=float(melhor["taxa_juros"]),
        ipca_pct=ipca_focus,
        selic_projetada_pct=_SELIC_PROJETADA_DEFAULT,
    )
    tempo_user = perfil.get("tempo_investimento")
    unidade_user = perfil.get("unidade_tempo", "meses")
    if tempo_user:
        projecao = projecao_juros_compostos(
            valor,
            taxa_nominal_melhor,
            tempo_investimento=int(tempo_user),
            unidade_tempo=unidade_user,
            aporte_mensal=aporte,
        )
    else:
        meses_venc = max(int(float(melhor["anos_venc"]) * 12), 1)
        projecao = projecao_juros_compostos(
            valor,
            taxa_nominal_melhor,
            tempo_investimento=meses_venc,
            unidade_tempo="meses",
            aporte_mensal=aporte,
        )

    # Estatísticas descritivas do mercado completo (NumPy)
    taxas_all = df["taxa_juros"].values.astype(float)
    estatisticas = {
        "taxa_media": float(round(np.mean(taxas_all), 2)),
        "taxa_maxima": float(round(np.max(taxas_all), 2)),
        "taxa_minima": float(round(np.min(taxas_all), 2)),
        "desvio_padrao": float(round(np.std(taxas_all), 2)),
        "total_titulos_analisados": int(len(df)),
    }

    titulos_serializaveis = [
        {
            "nome": str(r["nome"]),
            "indexador": str(r["indexador"]),
            "taxa_juros": float(r["taxa_juros"]),
            "preco_unitario": float(r["preco_unitario"]),
            "vencimento": str(r["vencimento"]),
            "retorno_real": float(r["retorno_real"]),
            "score_risco": float(r["score_risco"]),
            "anos_vencimento": float(r["anos_venc"]),
        }
        for _, r in top5.iterrows()
    ]

    # ── Metadados temporais para o prompt do Gemini ────────────────────────────
    # Calculados aqui (no pipeline, com pandas) para serem ground-truth
    # determinístico no <META_TEMPORAL> do prompt — evita o LLM errar a
    # matemática do horizonte e dá base para a regra de fallback do Tesouro.
    ano_atual = int(pd.Timestamp.today().year)
    ano_alvo_resgate = ano_atual + (total_meses_user // 12) if total_meses_user else None

    idx_max_venc = df["vencimento_dt"].idxmax()
    venc_max_dt   = df.loc[idx_max_venc, "vencimento_dt"]
    hoje          = pd.Timestamp.today().normalize()
    dias_max      = max(int((venc_max_dt - hoje).days), 1)
    meses_max     = max(int(round(dias_max / 30.4375)), 1)
    vencimento_max_disponivel = {
        "ano":            int(venc_max_dt.year),
        "titulo":         str(df.loc[idx_max_venc, "nome"]),
        "data":           venc_max_dt.strftime("%d/%m/%Y"),
        "meses_ate_hoje": meses_max,
        "anos_ate_hoje":  round(meses_max / 12, 1),
    }

    return {
        "titulos_recomendados": titulos_serializaveis,
        "projecao": projecao,
        "estatisticas_mercado": estatisticas,
        "titulo_base_projecao": str(melhor["nome"]),
        "ano_atual": ano_atual,
        "ano_alvo_resgate": ano_alvo_resgate,
        "vencimento_max_disponivel": vencimento_max_disponivel,
        # IPCA Focus (live, cacheado) — disponibilizado para o app.py compor a
        # taxa nominal da projeção via Fisher, evitando bater na Olinda de novo.
        "ipca_focus_pct": float(ipca_focus),
    }
