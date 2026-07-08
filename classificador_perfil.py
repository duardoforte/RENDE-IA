import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# --- Mapeamentos dos campos do formulário principal.html ---
OBJETIVO_MAP   = {"reserva": 0, "render": 1, "bem": 2, "juros": 3}
PRAZO_MAP      = {"less1": 0, "1to3": 1, "3to5": 2, "more5": 3}
CONHECIMENTO_MAP = {"iniciante": 0, "intermediario": 1, "avancado": 2}

# Traduções para o prompt do Gemini
OBJETIVO_BR    = {"reserva": "reserva de emergência", "render": "fazer o dinheiro render",
                  "bem": "comprar um bem (carro ou imóvel)", "juros": "viver de juros"}
PRAZO_BR       = {"less1": "menos de 1 ano", "1to3": "entre 1 e 3 anos",
                  "3to5": "entre 3 e 5 anos", "more5": "mais de 5 anos"}
CONHECIMENTO_BR = {"iniciante": "iniciante", "intermediario": "intermediário", "avancado": "avançado"}

# --- Dataset de treino baseado nas diretrizes ANBIMA de suitability ---
# Features: [valor, aporte, objetivo(0-3), prazo(0-3), conhecimento(0-2)]
# Target: perfil de risco
_TREINO = pd.DataFrame([
    # ── CONSERVADORES ──────────────────────────────────────────────────────────
    # Reserva de emergência + curto prazo + iniciante → sempre conservador
    {"v":  1_000, "a":    0, "o": 0, "pr": 0, "c": 0, "p": "conservador"},
    {"v":  2_500, "a":  100, "o": 0, "pr": 0, "c": 0, "p": "conservador"},
    {"v":  5_000, "a":    0, "o": 0, "pr": 0, "c": 0, "p": "conservador"},
    {"v":  8_000, "a":  200, "o": 0, "pr": 1, "c": 0, "p": "conservador"},
    {"v": 10_000, "a":    0, "o": 0, "pr": 0, "c": 1, "p": "conservador"},
    {"v":  3_000, "a":  100, "o": 0, "pr": 1, "c": 0, "p": "conservador"},
    {"v":  1_500, "a":   50, "o": 1, "pr": 0, "c": 0, "p": "conservador"},
    {"v":  4_000, "a":    0, "o": 0, "pr": 0, "c": 0, "p": "conservador"},
    {"v":  7_000, "a":  300, "o": 0, "pr": 1, "c": 0, "p": "conservador"},
    {"v":    500, "a":   50, "o": 0, "pr": 0, "c": 0, "p": "conservador"},
    {"v": 12_000, "a":    0, "o": 0, "pr": 0, "c": 1, "p": "conservador"},
    {"v":  6_000, "a":  200, "o": 1, "pr": 1, "c": 0, "p": "conservador"},
    # ── MODERADOS ──────────────────────────────────────────────────────────────
    # Crescer patrimônio + prazo médio + intermediário → moderado
    {"v": 10_000, "a":  500, "o": 1, "pr": 2, "c": 1, "p": "moderado"},
    {"v": 15_000, "a":  500, "o": 2, "pr": 2, "c": 1, "p": "moderado"},
    {"v": 20_000, "a":  800, "o": 1, "pr": 2, "c": 1, "p": "moderado"},
    {"v": 25_000, "a":    0, "o": 2, "pr": 1, "c": 1, "p": "moderado"},
    {"v": 30_000, "a": 1000, "o": 1, "pr": 3, "c": 1, "p": "moderado"},
    {"v": 12_000, "a":  400, "o": 1, "pr": 2, "c": 1, "p": "moderado"},
    {"v": 18_000, "a":  600, "o": 2, "pr": 2, "c": 2, "p": "moderado"},
    {"v": 22_000, "a":  700, "o": 1, "pr": 3, "c": 1, "p": "moderado"},
    {"v":  9_000, "a":  300, "o": 2, "pr": 1, "c": 1, "p": "moderado"},
    {"v": 28_000, "a":  800, "o": 1, "pr": 2, "c": 1, "p": "moderado"},
    {"v": 35_000, "a": 1000, "o": 2, "pr": 3, "c": 1, "p": "moderado"},
    {"v": 14_000, "a":  500, "o": 1, "pr": 2, "c": 2, "p": "moderado"},
    # ── ARROJADOS ──────────────────────────────────────────────────────────────
    # Viver de juros + longo prazo + experiente → arrojado
    {"v":  50_000, "a": 2_000, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
    {"v":  75_000, "a": 3_000, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
    {"v": 100_000, "a": 5_000, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
    {"v":  40_000, "a": 1_500, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
    {"v":  60_000, "a":     0, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
    {"v":  45_000, "a": 2_000, "o": 3, "pr": 3, "c": 1, "p": "arrojado"},
    {"v":  55_000, "a": 1_000, "o": 1, "pr": 3, "c": 2, "p": "arrojado"},
    {"v":  80_000, "a": 2_000, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
    {"v": 120_000, "a": 5_000, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
    {"v":  35_000, "a": 1_500, "o": 3, "pr": 2, "c": 2, "p": "arrojado"},
    {"v":  90_000, "a": 3_000, "o": 3, "pr": 3, "c": 2, "p": "arrojado"},
])


def _treinar() -> Pipeline:
    X = _TREINO[["v", "a", "o", "pr", "c"]]
    y = _TREINO["p"]
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=300,
            random_state=42,
            class_weight="balanced",
            max_depth=8,
        )),
    ])
    pipeline.fit(X, y)
    return pipeline


_modelo = _treinar()


def classificar_perfil(dados: dict) -> dict:
    """
    Classifica o perfil do investidor com base nos 5 campos do formulário
    principal.html, usando RandomForest treinado com regras ANBIMA.

    Campos esperados em `dados`:
        valorInicial   (float) — capital inicial
        aporteMensal   (float) — aporte mensal (0 se não houver)
        objetivo       (str)   — "reserva" | "render" | "bem" | "juros"
        prazo          (str)   — "less1" | "1to3" | "3to5" | "more5"
        conhecimento   (str)   — "iniciante" | "intermediario" | "avancado"
    """
    valor      = float(dados.get("valorInicial", 10_000))
    aporte     = float(dados.get("aporteMensal", 0))
    objetivo   = OBJETIVO_MAP.get(str(dados.get("objetivo", "reserva")), 0)
    prazo      = PRAZO_MAP.get(str(dados.get("prazo", "less1")), 0)
    conhecimento = CONHECIMENTO_MAP.get(str(dados.get("conhecimento", "iniciante")), 0)

    X = pd.DataFrame(
        [[valor, aporte, objetivo, prazo, conhecimento]],
        columns=["v", "a", "o", "pr", "c"],
    )
    perfil = _modelo.predict(X)[0]
    probas = _modelo.predict_proba(X)[0]

    distribuicao = {
        label: float(round(p * 100, 1))
        for label, p in zip(_modelo.classes_, probas)
    }

    return {
        "perfil_classificado": perfil,
        "tolerancia_risco": perfil,
        "confianca_pct": float(round(max(probas) * 100, 1)),
        "distribuicao_prob": distribuicao,
        "valor": valor,
        "aporteMensal": aporte,
        # campos traduzidos para uso no prompt do Gemini
        "objetivo_descricao": OBJETIVO_BR.get(str(dados.get("objetivo", "")), str(dados.get("objetivo", ""))),
        "prazo_descricao": PRAZO_BR.get(str(dados.get("prazo", "")), str(dados.get("prazo", ""))),
        "conhecimento_descricao": CONHECIMENTO_BR.get(str(dados.get("conhecimento", "")), ""),
    }
