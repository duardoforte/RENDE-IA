import io
import base64
import numpy as np
import matplotlib
matplotlib.use("Agg")  # backend sem display — obrigatório em servidor
import matplotlib.pyplot as plt

# Paleta idêntica ao CSS do frontend
_COR = {
    "fundo":    "#f7f7f5",
    "escuro":   "#0e0e0e",
    "medio":    "#555555",
    "suave":    "#aaaaaa",
    "destaque": "#e08a00",
    "grade":    "#e8e8e8",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 13,
    "axes.facecolor": _COR["fundo"],
    "figure.facecolor": _COR["fundo"],
    "text.color": _COR["escuro"],
    "axes.labelcolor": _COR["medio"],
    "xtick.color": _COR["medio"],
    "ytick.color": _COR["medio"],
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
})


def _para_base64(fig: plt.Figure, pad_inches: float = 0.1) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                pad_inches=pad_inches, facecolor=_COR["fundo"])
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def grafico_alocacao(titulos: list) -> str:
    """
    Gráfico de pizza com alocação igualmente ponderada dos títulos recomendados.
    (Em produção, pode ser substituído por risk-parity ou outro critério.)
    """
    if not titulos:
        return ""

    nomes = [
        t["nome"].replace("Tesouro ", "").replace(" (Juros semestrais)", " *")
        for t in titulos
    ]
    n = len(nomes)
    pesos = np.ones(n) / n * 100

    # Escala de cinzas + destaque para o primeiro (melhor rankeado)
    tons = ["#0e0e0e", "#444444", "#777777", "#aaaaaa", "#cccccc"]
    cores = [_COR["destaque"]] + tons[: n - 1]

    fig, ax = plt.subplots(figsize=(7, 5))

    wedges, texts, autotexts = ax.pie(
        pesos,
        labels=nomes,
        autopct="%1.0f%%",
        colors=cores[:n],
        startangle=140,
        pctdistance=0.72,
        wedgeprops={"linewidth": 2.5, "edgecolor": _COR["fundo"]},
        textprops={"fontsize": 12, "color": _COR["medio"]},
    )
    for at in autotexts:
        at.set_color("white")
        at.set_fontsize(12)
        at.set_fontweight("bold")


    plt.tight_layout()
    return _para_base64(fig)
