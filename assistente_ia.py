import os
import json
import time
from dotenv import load_dotenv
import sqlite3
from google import genai
from google.genai import types

load_dotenv()

_MODOS_GEMINI_VALIDOS = {"mock", "fallback", "real"}


def _resolver_modo_gemini() -> str:
    modo = (os.getenv("RENDE_IA_GEMINI_MODE", "real") or "real").strip().lower()
    if modo not in _MODOS_GEMINI_VALIDOS:
        print("[Gemini] RENDE_IA_GEMINI_MODE inválido. Usando modo real.")
        return "real"
    return modo


class _ModelosGeminiIndisponiveis:
    def generate_content(self, *args, **kwargs):
        raise RuntimeError("Gemini não configurado para chamada real.")


class _ClienteGeminiIndisponivel:
    models = _ModelosGeminiIndisponiveis()


# 1. Configurando a chave de acesso da IA
CHAVE_API = os.getenv("GEMINI_API_KEY")

# Fonte única de verdade do modelo. Para demonstração real, defina GEMINI_MODEL no .env.
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
MODELO = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
GEMINI_MODE = _resolver_modo_gemini()

# IA OBRIGATÓRIA: quando True, a camada real NÃO cai em fallback determinístico.
# Qualquer falha (429, timeout, schema) vira um erro controlado
# (GeminiObrigatorioError) para o app.py devolver mensagem amigável ao usuário.
REQUIRE_GEMINI = os.getenv("RENDE_IA_REQUIRE_GEMINI", "false").strip().lower() == "true"

client = genai.Client(api_key=CHAVE_API) if CHAVE_API else _ClienteGeminiIndisponivel()

print(f"[Gemini] Modelo configurado: {MODELO}")
print(f"[Gemini] Modo configurado: {GEMINI_MODE}")
print(f"[Gemini] IA obrigatória: {str(REQUIRE_GEMINI).lower()}")


def modelo_gemini_configurado() -> str:
    """Modelo Gemini efetivamente usado nas chamadas reais."""
    return MODELO


class GeminiObrigatorioError(Exception):
    """Lançada quando RENDE_IA_REQUIRE_GEMINI=true e a IA real falha — sinaliza ao
    app.py para devolver erro controlado (sem fallback determinístico). O atributo
    `motivo` traz o código sanitizado (ex.: 'quota/429', 'erro de schema')."""

    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


# ── PERSONA INSTITUCIONAL (System Instruction) ─────────────────────────────────
# Define o "DNA" do modelo. A saída é JSON estruturado (response_schema) — por isso
# este texto NÃO traz mais regras de Markdown/H2; foca exclusivamente em tom,
# integridade dos dados financeiros e regra de ranqueamento.
SYSTEM_INSTRUCTION = """Você é um Assessor Financeiro Sênior e Copywriter de Elite.
Suas respostas devem ser concisas, altamente persuasivas e escaneáveis.
Foque na TRANSFORMAÇÃO: mostre como a recomendação blinda o patrimônio do cliente e traz previsibilidade.
Nunca seja prolixo. Seja objetivo, confiante e transmita extrema autoridade.

REGRAS INVIOLÁVEIS DE ESCRITA:
1. Sempre em SEGUNDA PESSOA ("você", "seu capital", "sua carteira"). Jamais em terceira pessoa.
2. Proibido iniciar com saudações ("Prezado", "Olá", "É um prazer atendê-lo"). Vá direto à análise.
3. Proibido clichê de coaching ("rumo à liberdade financeira", "faça seu dinheiro trabalhar").
4. Cada campo do JSON tem um papel ÚNICO. Não repita conteúdo entre 'estrategia_recomendada'
   e 'ranking_oportunidades'.
5. Use apenas dados fornecidos. NUNCA invente taxas, vencimentos ou nomes de títulos.
6. RENTABILIDADE — REGRA CRÍTICA: ao preencher 'rentabilidade' no ranking, copie o
   campo "Rentabilidade" dos dados EXATAMENTE (ex.: "IPCA + 7,82%", "Selic + 0,15%",
   "10,28%" para prefixado). É TERMINANTEMENTE PROIBIDO omitir "IPCA" ou "Selic",
   suprimir o sinal "+", ou exibir apenas o número quando o título for híbrido.
   Confundir taxa híbrida com prefixada é erro grave que invalida o relatório.

REGRA DE RANQUEAMENTO (CRÍTICA):
Você deve analisar os dados coletados do Tesouro Direto e preencher o array
'ranking_oportunidades' ordenando-os ESTRITAMENTE do melhor para o pior ativo de
acordo com o perfil do usuário. O ativo na posição 1 será considerado o VENCEDOR
ABSOLUTO e guiará a projeção visual do sistema (gráfico de evolução patrimonial).
Escolha a posição 1 com cuidado — ela define o que o cliente vê na tela.

REGRA DE CORRESPONDÊNCIA TEMPORAL (CRÍTICA — sobrepõe retorno bruto):
O backend já calculou o ANO ALVO DE RESGATE (Ano atual + horizonte exato do cliente)
e o injetou no bloco <META_TEMPORAL> do prompt. Você DEVE usar esse valor.

1. CÁLCULO DA DATA ALVO: o Ano Alvo está dado em <META_TEMPORAL>. Não recalcule.
2. CORRESPONDÊNCIA: ao montar 'ranking_oportunidades', priorize títulos cujo
   'Ano de Vencimento' esteja MAIS PRÓXIMO do Ano Alvo. A posicao=1 é o título
   com MENOR distância absoluta entre Ano de Vencimento e Ano Alvo, respeitando
   o perfil de risco do cliente. NUNCA escolha posicao=1 só pelo maior retorno
   bruto quando houver candidato com alinhamento de prazo materialmente melhor.
3. FALLBACK DO LIMITE DO TESOURO: o Tesouro Direto tem um limite máximo de
   vencimento (o maior disponível na base está em <META_TEMPORAL>). Se o Ano
   Alvo do cliente for MAIOR que esse limite, selecione o título mais longo
   disponível e DECLARE explicitamente isso no campo 'alinhamento_prazo'.
4. PREENCHIMENTO OBRIGATÓRIO de dois campos novos em cada item do ranking:
   - ano_vencimento_ativo: o ano (inteiro, 4 dígitos) extraído da data de
     vencimento copiada. Ex.: "15/12/2084" → 2084.
   - alinhamento_prazo: frase curta em UMA linha declarando como o vencimento
     daquele título se relaciona com o Ano Alvo do cliente. Padrões aceitos:
       • "Alinhamento perfeito — vence em 2064, apenas 2 anos após o alvo 2062."
       • "Alinhamento aceitável — vence em 2074, 12 anos após o alvo 2062
         (carrega proteção real adicional)."
       • "Título mais longo disponível no Tesouro — vence em 2084, supera o
         alvo 2062 em 22 anos. Você fica exposto a marcação a mercado se quiser
         resgatar exatamente no alvo."
       • "Título mais longo disponível no Tesouro — vence em 2084, ainda
         INFERIOR ao alvo 2110 do cliente em 26 anos (FALLBACK do limite)."
     Sempre cite o Ano de Vencimento e o Ano Alvo nominalmente na frase.

INTEGRIDADE DO RELATÓRIO (CRÍTICA):
O JSON tem 5 campos OBRIGATÓRIOS e NENHUM pode vir vazio ou pulado:
  1. analise_macroeconomica  — contexto de cenário (parágrafo curto)
  2. estrategia_recomendada  — porquê da estratégia (2-3 parágrafos)
  3. riscos_pontos_atencao   — alertas em bullets curtos
  4. ranking_oportunidades   — exatamente 3 ativos ordenados (posicao 1, 2, 3)
  5. glossario               — termos técnicos do relatório explicados
Omitir qualquer campo invalida a entrega. Preencha TODOS com riqueza de detalhes
proporcional ao nível de conhecimento do cliente."""


# ── MAPA DE TOM POR NÍVEL DE CONHECIMENTO ──────────────────────────────────────
_TONS = {
    "iniciante": {
        "rotulo": "INICIANTE",
        "tom": "EDUCATIVO, ACOLHEDOR E FOCADO EM SEGURANÇA ABSOLUTA",
        "diretrizes": (
            "- Trate o cliente como alguém dando os primeiros passos. Sem julgamento, sem pressão.\n"
            "- Use metáforas concretas e cotidianas (ex.: 'cofre digital', 'reserva de emergência', "
            "'colchão financeiro'). Evite analogias abstratas.\n"
            "- Proibido jargão solto. Se precisar citar 'IPCA' ou 'Selic', explique em UMA linha imediatamente.\n"
            "- Reforce previsibilidade, garantia do Tesouro Nacional e baixíssimo risco.\n"
            "- Proibido falar em duration, marcação a mercado, curva de juros, spread ou convexidade."
        ),
    },
    "intermediário": {
        "rotulo": "INTERMEDIÁRIO",
        "tom": "CONSULTIVO, EQUILIBRADO E ESTRATÉGICO",
        "diretrizes": (
            "- Trate o cliente como alguém que já entende o básico e quer evoluir.\n"
            "- Foque em DIVERSIFICAÇÃO (por indexador e prazo), PROTEÇÃO CONTRA INFLAÇÃO e BALANCEAMENTO da carteira.\n"
            "- Pode usar termos como 'IPCA+', 'prefixado', 'liquidez' e 'retorno real' sem definir — "
            "contextualize só quando agregar valor.\n"
            "- Evite jargão de mesa: sem 'duration', 'convexidade' ou 'forward rates'.\n"
            "- Argumente cada escolha em termos de cenário macro e horizonte do cliente."
        ),
    },
    "avançado": {
        "rotulo": "EXPERIENTE",
        "tom": "DIRETO, INSTITUCIONAL E ANALÍTICO",
        "diretrizes": (
            "- Trate o cliente como par técnico. Pressuponha fluência total em renda fixa.\n"
            "- Use livremente: DURATION, MARCAÇÃO A MERCADO, CURVA DE JUROS, SPREAD sobre o livre de risco, "
            "EFICIÊNCIA TRIBUTÁRIA (tabela regressiva de IR), CARRY e CONVEXIDADE quando pertinentes.\n"
            "- Vá direto aos números: taxas, retorno real (Fisher), score de risco, prazo em anos.\n"
            "- Recomende táticas avançadas quando fizer sentido (laddering, barbell, exploração de "
            "inclinação da curva).\n"
            "- Zero metáforas. Zero didatismo. Linguagem de mesa institucional."
        ),
    },
}


def _resolver_tom(conhecimento: str) -> dict:
    """Normaliza variações com/sem acento e devolve o bloco de tom correspondente."""
    chave = (conhecimento or "").strip().lower()
    if chave in ("intermediario", "intermediário"):
        chave = "intermediário"
    elif chave in ("avancado", "avançado", "experiente", "expert"):
        chave = "avançado"
    elif chave in ("iniciante", "novato", "principiante"):
        chave = "iniciante"
    return _TONS.get(chave, _TONS["iniciante"])


def _nivel_canonico(conhecimento: str) -> str:
    """Reduz a descrição de conhecimento a uma de três chaves estáveis usadas
    pelo fallback determinístico para calibrar linguagem e profundidade:
    'iniciante' | 'intermediario' | 'avancado'."""
    chave = (conhecimento or "").strip().lower()
    if chave in ("intermediario", "intermediário"):
        return "intermediario"
    if chave in ("avancado", "avançado", "experiente", "expert"):
        return "avancado"
    return "iniciante"


# ── MAPA DE FOCO POR OBJETIVO ───────────────────────────────────────────────────
# Cada objetivo do formulário (reserva/juros/bem/render) tem um EIXO próprio que
# muda o que importa na recomendação. 'diretriz' alimenta o prompt do Gemini;
# 'estrategia_fb'/'risco_fb' alimentam o fallback determinístico. O objetivo é
# ortogonal ao nível de experiência (linguagem) — os dois se cruzam na resposta.
_OBJETIVOS = {
    "reserva": {
        "rotulo": "RESERVA DE EMERGÊNCIA",
        "diretriz": (
            "Priorize LIQUIDEZ, SEGURANÇA e baixa volatilidade — o dinheiro precisa estar "
            "acessível a qualquer momento. Deixe claro que rentabilidade máxima NÃO é o "
            "critério principal e alerte sobre marcação a mercado em prefixados/IPCA+ longos."
        ),
        "estrategia_fb": (
            "Como o objetivo é reserva de emergência, priorize liquidez diária e segurança: "
            "o dinheiro precisa estar acessível a qualquer momento, então a maior rentabilidade "
            "nominal não é o critério principal."
        ),
        "risco_fb": (
            "- Para reserva de emergência, evite prefixados ou IPCA+ longos: a marcação a "
            "mercado pode reduzir o valor caso você precise resgatar de imediato."
        ),
    },
    "juros": {
        "rotulo": "VIVER DE JUROS",
        "diretriz": (
            "Priorize GERAÇÃO DE RENDA e previsibilidade de fluxo; considere títulos com juros "
            "semestrais quando fizer sentido. Aborde risco de reinvestimento, imposto de renda, "
            "a necessidade de patrimônio suficiente e a diferença entre receber juros e resgatar "
            "patrimônio, sem ilusão de renda que ignore a inflação."
        ),
        "estrategia_fb": (
            "Para viver de juros, o foco é renda recorrente e previsibilidade de fluxo; receber "
            "juros depende de patrimônio acumulado, taxa e inflação, e títulos com juros "
            "semestrais podem ajudar a estruturar essa renda."
        ),
        "risco_fb": (
            "- Para viver de juros, atenção ao risco de reinvestimento e ao imposto de renda "
            "sobre os cupons; renda nominal sem descontar a inflação ilude o resultado real."
        ),
    },
    "bem": {
        "rotulo": "COMPRAR UM BEM",
        "diretriz": (
            "Há uma DATA-ALVO: priorize preservar o valor até a compra e a ADERÊNCIA do "
            "vencimento ao prazo. Explique por que a aderência ao prazo pode importar mais que a "
            "maior taxa nominal e alerte sobre resgatar antes do vencimento (marcação a mercado). "
            "Evite recomendar título mais longo que a data do objetivo."
        ),
        "estrategia_fb": (
            "Como o objetivo é comprar um bem com data-alvo, a aderência do vencimento ao prazo "
            "e a previsibilidade tendem a importar mais do que a maior taxa nominal — o foco é "
            "preservar o valor até a data da compra."
        ),
        "risco_fb": (
            "- Se a data da compra for rígida, evite títulos mais longos que o prazo: resgatar "
            "antes do vencimento expõe à marcação a mercado e quebra a previsibilidade."
        ),
    },
    "render": {
        "rotulo": "RENDER SEM META ESPECÍFICA",
        "diretriz": (
            "Sem data rígida, foque CRESCIMENTO PATRIMONIAL e retorno real, com diversificação "
            "entre pós-fixado, prefixado e IPCA+ e flexibilidade para revisar a estratégia no "
            "futuro. A estratégia pode ser mais ampla."
        ),
        "estrategia_fb": (
            "Sem meta específica, há flexibilidade para focar crescimento patrimonial e retorno "
            "real, diversificando entre pós-fixado, prefixado e IPCA+, com flexibilidade para "
            "revisar a estratégia no futuro."
        ),
        "risco_fb": (
            "- Mesmo com horizonte aberto, equilibre retorno, prazo e risco; alguma volatilidade "
            "de marcação a mercado é tolerável, desde que o retorno real seja preservado."
        ),
    },
}


def _objetivo_canonico(perfil_investidor: dict) -> str:
    """Mapeia o objetivo (chave de fio 'reserva'/'juros'/'bem'/'render' ou a descrição
    traduzida) para uma das quatro chaves de _OBJETIVOS. Default 'render' (neutro/flexível)."""
    raw = str((perfil_investidor or {}).get("objetivo") or "").strip().lower()
    if raw in _OBJETIVOS:
        return raw
    desc = str((perfil_investidor or {}).get("objetivo_descricao") or raw).strip().lower()
    if "reserva" in desc or "emerg" in desc:
        return "reserva"
    if "juros" in desc:
        return "juros"
    if "bem" in desc or "carro" in desc or "imóvel" in desc or "imovel" in desc:
        return "bem"
    if "render" in desc:
        return "render"
    return "render"


# ── MAPA DE CENÁRIO POR APORTE ──────────────────────────────────────────────────
# Eixo "como o dinheiro entra": aporte único vs. recorrente, cruzado com a magnitude
# do capital inicial e do aporte. 'diretriz' alimenta o prompt; 'estrategia_fb'/
# 'risco_fb' alimentam o fallback. Ortogonal a objetivo e nível de experiência.
_CENARIOS_APORTE = {
    "aporte_unico": {
        "rotulo": "APORTE ÚNICO (sem recorrência)",
        "diretriz": (
            "NÃO há aportes mensais — é um investimento ÚNICO. A evolução depende apenas do "
            "capital inicial e da taxa; NÃO fale em disciplina de aportes nem em construir "
            "patrimônio com recorrência mensal. Deixe claro que, sem novos aportes, o montante "
            "final é mais limitado, e reforce a importância de prazo, taxa e liquidez."
        ),
        "estrategia_fb": (
            "Como você fará um investimento único (sem aportes mensais), a evolução depende "
            "apenas do capital inicial e da taxa contratada — o prazo e a escolha do título "
            "pesam mais do que qualquer rotina de contribuição."
        ),
        "risco_fb": (
            "- Sem novos aportes, o montante final fica limitado ao capital inicial "
            "capitalizado; prazo, taxa e liquidez tornam-se ainda mais decisivos."
        ),
    },
    "aporte_unico_valor_alto": {
        "rotulo": "APORTE ÚNICO (valor inicial alto)",
        "diretriz": (
            "NÃO há aportes mensais (investimento único) e o valor inicial é alto. Foque "
            "PRESERVAÇÃO DE CAPITAL, liquidez e adequação ao prazo; a escolha do título tem "
            "impacto relevante no patrimônio. Reforce marcação a mercado, inflação e vencimento. "
            "NÃO trate o cliente como iniciante em acumulação mensal nem fale em disciplina de aportes."
        ),
        "estrategia_fb": (
            "Com um valor inicial alto aplicado de uma só vez (sem aportes mensais), o foco é "
            "preservação de capital, liquidez e aderência ao prazo: a seleção do título tem "
            "impacto relevante sobre o patrimônio."
        ),
        "risco_fb": (
            "- Com capital alto e sem aportes, marcação a mercado, inflação e vencimento "
            "concentram o risco; a escolha do título define o resultado mais do que qualquer rotina."
        ),
    },
    "aporte_baixo": {
        "rotulo": "APORTE MENSAL BAIXO",
        "diretriz": (
            "HÁ aportes mensais, porém de valor baixo. Explique o papel da DISCIPLINA de aportes "
            "e que o crescimento tende a ser gradual; a consistência pode importar mais do que "
            "buscar a maior taxa. O resultado depende da regularidade das contribuições."
        ),
        "estrategia_fb": (
            "Com aportes mensais regulares (de valor mais modesto), a disciplina de contribuição "
            "é o motor do crescimento: o resultado vem da consistência ao longo do tempo, mais "
            "do que de perseguir a maior taxa nominal."
        ),
        "risco_fb": (
            "- O aporte mensal constante é premissa da simulação; se a regularidade das "
            "contribuições mudar, a projeção muda junto."
        ),
    },
    "aporte_relevante": {
        "rotulo": "APORTE MENSAL RELEVANTE",
        "diretriz": (
            "HÁ aportes mensais com peso RELEVANTE no resultado. Destaque o efeito dos juros "
            "compostos somado à acumulação mensal, a importância de disciplina e revisão "
            "periódica, e o risco de interromper os aportes. Conecte aporte, prazo e objetivo."
        ),
        "estrategia_fb": (
            "Seus aportes mensais têm peso relevante: o resultado combina juros compostos com a "
            "acumulação recorrente das contribuições. Disciplina e revisão periódica passam a ser "
            "tão importantes quanto a escolha do título."
        ),
        "risco_fb": (
            "- Como o aporte mensal constante carrega boa parte do crescimento projetado, "
            "interromper as contribuições altera fortemente o resultado."
        ),
    },
    "valor_baixo_aporte_alto": {
        "rotulo": "VALOR INICIAL BAIXO + APORTE ALTO",
        "diretriz": (
            "O capital inicial é baixo e os aportes mensais são altos: o plano depende MUITO MAIS "
            "da capacidade de contribuição futura do que do valor inicial. Destaque consistência "
            "e que a projeção é sensível à manutenção dos aportes; interromper as contribuições "
            "altera fortemente o resultado."
        ),
        "estrategia_fb": (
            "Com capital inicial baixo e aportes mensais altos, o plano depende muito mais da sua "
            "capacidade de contribuição futura do que do valor inicial — a consistência dos "
            "aportes é o que sustenta a projeção."
        ),
        "risco_fb": (
            "- A projeção é altamente sensível à manutenção dos aportes; como o aporte mensal "
            "constante domina o crescimento, interrompê-lo muda fortemente o resultado."
        ),
    },
}


def _cenario_aporte(valor, aporte) -> str:
    """Classifica o par (valor inicial, aporte mensal) em um cenário estável.
    Eixo primário: há aporte recorrente ou não. Secundário: magnitude do capital
    e do aporte. Usado por prompt e fallback para diferenciar único vs. recorrente."""
    try:
        valor = float(valor or 0)
    except (TypeError, ValueError):
        valor = 0.0
    try:
        aporte = float(aporte or 0)
    except (TypeError, ValueError):
        aporte = 0.0

    faz_aporte = aporte > 0
    aporte_anual = aporte * 12
    valor_alto = valor >= 50_000

    if not faz_aporte:
        return "aporte_unico_valor_alto" if valor_alto else "aporte_unico"

    # Há aporte recorrente:
    aporte_dominante = valor <= 0 or aporte_anual >= valor
    if valor <= 2_000 and aporte_dominante:
        return "valor_baixo_aporte_alto"
    if aporte >= 1_000 or aporte_dominante:
        return "aporte_relevante"
    return "aporte_baixo"


# ── MAPA DE HORIZONTE POR PRAZO ─────────────────────────────────────────────────
# Eixo "por quanto tempo": curto/médio/longo muda o que importa (liquidez x duration).
# 'diretriz' alimenta o prompt; 'estrategia_fb'/'risco_fb' alimentam o fallback.
# Ortogonal a objetivo, aporte e nível de experiência.
_HORIZONTES = {
    "muito_curto": {
        "rotulo": "MUITO CURTO (até 12 meses)",
        "diretriz": (
            "Horizonte MUITO CURTO (até 12 meses): priorize LIQUIDEZ e segurança; alerte sobre "
            "marcação a mercado e NÃO trate títulos longos como escolha natural. Previsibilidade "
            "e acesso ao dinheiro importam mais que a maior taxa, e prazos curtos reduzem o "
            "efeito dos juros compostos."
        ),
        "estrategia_fb": (
            "Com um horizonte muito curto (até 12 meses), a prioridade é liquidez e segurança: "
            "o acesso rápido ao dinheiro e a previsibilidade importam mais do que perseguir a "
            "maior taxa nominal, e os juros compostos têm pouco tempo para agir."
        ),
        "risco_fb": (
            "- Em prazo curto, evite títulos longos: a marcação a mercado pode reduzir o valor no "
            "resgate antecipado — priorize liquidez."
        ),
    },
    "curto_medio": {
        "rotulo": "CURTO/MÉDIO (1 a 3 anos)",
        "diretriz": (
            "Horizonte CURTO/MÉDIO (1 a 3 anos): equilibre liquidez, previsibilidade e retorno; "
            "explique a aderência entre o vencimento do título e a data-alvo e alerte sobre "
            "resgate antes do vencimento. Prefixados podem fazer sentido quando prazo e "
            "vencimento são compatíveis."
        ),
        "estrategia_fb": (
            "Em um horizonte de 1 a 3 anos, equilibre liquidez, previsibilidade e retorno, "
            "priorizando títulos cujo vencimento seja compatível com a sua data-alvo."
        ),
        "risco_fb": (
            "- Resgatar antes do vencimento expõe à marcação a mercado; busque aderência entre o "
            "vencimento do título e o prazo desejado."
        ),
    },
    "medio": {
        "rotulo": "MÉDIO (3 a 5 anos)",
        "diretriz": (
            "Horizonte MÉDIO (3 a 5 anos): aprofunde o retorno real (inflação projetada vs. taxa "
            "nominal) e o trade-off entre retorno e volatilidade; avalie IPCA+, prefixado ou "
            "pós-fixado conforme perfil/objetivo, evitando vender antes do vencimento."
        ),
        "estrategia_fb": (
            "Em um horizonte de 3 a 5 anos, o retorno real (taxa acima da inflação projetada) "
            "ganha peso; avalie IPCA+, prefixado e pós-fixado conforme o objetivo, evitando "
            "precisar vender antes do vencimento."
        ),
        "risco_fb": (
            "- Considere a inflação projetada no retorno real e evite resgatar antes do "
            "vencimento para não se expor à marcação a mercado."
        ),
    },
    "longo": {
        "rotulo": "LONGO (acima de 5 anos)",
        "diretriz": (
            "Horizonte LONGO (acima de 5 anos): trate retorno real, inflação, duration e marcação "
            "a mercado; títulos longos são mais sensíveis a juros. IPCA+ pode proteger o poder de "
            "compra; aborde risco de reinvestimento (juros semestrais) e a necessidade de tolerar "
            "oscilações se vender antes do vencimento. Evite simplificações para o investidor experiente."
        ),
        "estrategia_fb": (
            "Em um horizonte longo (acima de 5 anos), retorno real e proteção contra a inflação "
            "ganham destaque; títulos IPCA+ podem preservar o poder de compra, mas a maior "
            "duration aumenta a sensibilidade à marcação a mercado."
        ),
        "risco_fb": (
            "- Títulos longos têm maior duration e mais volatilidade (marcação a mercado); a "
            "inflação ao longo do tempo e o risco de reinvestimento merecem atenção."
        ),
    },
    "muito_longo": {
        "rotulo": "MUITO LONGO (10 anos ou mais)",
        "diretriz": (
            "Horizonte MUITO LONGO (10 anos ou mais): destaque que a simulação assume PREMISSAS "
            "CONSTANTES e não é garantia; reforce a incerteza de inflação, juros e cenário macro, "
            "a necessidade de revisões periódicas e a compatibilidade entre vencimento e "
            "horizonte. Deixe claro quando a projeção foi limitada ao vencimento do título."
        ),
        "estrategia_fb": (
            "Em um horizonte muito longo (10 anos ou mais), a simulação assume premissas "
            "constantes e não deve ser lida como garantia: inflação, juros e cenário macro mudam, "
            "exigindo revisões periódicas e atenção à compatibilidade entre vencimento e horizonte."
        ),
        "risco_fb": (
            "- Em prazos muito longos, a incerteza de inflação/juros e a volatilidade de marcação "
            "a mercado pesam; revise a estratégia periodicamente e confira se o vencimento cobre o horizonte."
        ),
    },
}


def _total_meses_perfil(perfil_investidor: dict) -> int:
    """Total de meses do horizonte, robusto a chamadas diretas. Prefere 'total_meses'
    (injetado por app.py); senão deriva de tempo_investimento + unidade_tempo."""
    perfil_investidor = perfil_investidor or {}
    tm = perfil_investidor.get("total_meses")
    if tm:
        try:
            return int(tm)
        except (TypeError, ValueError):
            pass
    tempo = perfil_investidor.get("tempo_investimento")
    if tempo:
        try:
            tempo = int(tempo)
        except (TypeError, ValueError):
            return 0
        return tempo * 12 if perfil_investidor.get("unidade_tempo") == "anos" else tempo
    return 0


def _horizonte_classe(total_meses: int) -> str:
    """Classifica o total de meses em uma faixa estável de horizonte."""
    m = int(total_meses or 0)
    if m <= 12:
        return "muito_curto"
    if m <= 36:
        return "curto_medio"
    if m <= 60:
        return "medio"
    if m < 120:
        return "longo"
    return "muito_longo"


def _prazo_excede_vencimento_max(perfil_investidor: dict) -> bool:
    """True quando o Ano Alvo de Resgate supera o maior vencimento disponível na base
    (sinaliza projeção limitada ao vencimento). Apenas COMPARA valores já calculados
    pelo pipeline — não recalcula nada financeiro."""
    ano_alvo = (perfil_investidor or {}).get("ano_alvo_resgate")
    venc_max = (perfil_investidor or {}).get("vencimento_max_disponivel") or {}
    ano_max = venc_max.get("ano")
    try:
        return bool(ano_alvo) and bool(ano_max) and int(ano_alvo) > int(ano_max)
    except (TypeError, ValueError):
        return False


def _formatar_taxa_br(taxa: float) -> str:
    """4.5 → '4,50' (padrão brasileiro com 2 casas)."""
    return f"{float(taxa):.2f}".replace(".", ",")


def _capitalizar_termo(termo: str) -> str:
    """
    Capitaliza APENAS a primeira letra do termo, preservando o restante
    intacto. Por que não usar str.capitalize()? Porque .capitalize() força
    o restante a minúsculas, o que destrói siglas:

      'IPCA'                     → 'Ipca'   (errado — perde sigla)
      'marcação a mercado (MtM)' → 'Marcação a mercado (mtm)' (errado)

    A solução manual t[0].upper() + t[1:] preserva qualquer caracter após
    a primeira posição:

      'risco de reinvestimento' → 'Risco de reinvestimento'
      'IPCA'                    → 'IPCA' (intocado — já é maiúsculo)
      'duration de Macaulay'    → 'Duration de Macaulay'

    Também usar text-transform: capitalize no CSS seria errado — ele
    capitaliza TODA palavra (vira 'Risco De Reinvestimento'). E
    ::first-letter funciona mas acopla o CSS ao HTML que o marked.js
    produz a partir do markdown gerado aqui.
    """
    t = (termo or "").strip()
    if not t:
        return t
    return t[0].upper() + t[1:]


def formatar_rentabilidade(nome: str, indexador: str, taxa_juros: float) -> str:
    """
    Devolve a rentabilidade COMPLETA do título exatamente como exibida pelo Tesouro
    Direto, preservando o indexador.

    Regras de negócio (data enrichment baseado no nome do título):
      - Nome contém "IPCA+", "Educa+" ou "Renda+"  → "IPCA + <taxa>%"
      - Nome contém "Selic"                        → "Selic + <taxa>%"
      - Nome contém "Prefixado"                    → "<taxa>%" (taxa absoluta)
      - Fallback                                   → usa o campo indexador armazenado

    A taxa é formatada em padrão brasileiro (vírgula decimal).
    Esta função é a ÚNICA fonte de verdade para a rentabilidade enviada ao LLM.
    """
    taxa_br = _formatar_taxa_br(taxa_juros)
    n = (nome or "").lower()

    if "ipca+" in n or "educa+" in n or "renda+" in n:
        return f"IPCA + {taxa_br}%"
    if "selic" in n:
        return f"Selic + {taxa_br}%"
    if "prefixado" in n:
        return f"{taxa_br}%"

    # Fallback: confia no indexador persistido pelo processador
    idx = (indexador or "").strip()
    if idx and idx.lower() not in ("prefixado", ""):
        return f"{idx} + {taxa_br}%"
    return f"{taxa_br}%"


def coletar_dados_para_ia():
    """Lê o banco de dados e monta um resumo em texto para mandar para a IA."""
    try:
        conexao = sqlite3.connect("tesouro_direto.db")
        cursor = conexao.cursor()
        cursor.execute("SELECT nome, indexador, taxa_juros, preco_unitario, vencimento FROM titulos")
        todos_titulos = cursor.fetchall()
        conexao.close()

        if not todos_titulos:
            return None

        resumo_dados = "DADOS DO TESOURO DIRETO DE HOJE:\n"
        for nome, indexador, taxa_juros, preco_unitario, vencimento in todos_titulos:
            rentab = formatar_rentabilidade(nome, indexador, taxa_juros)
            resumo_dados += (
                f"- {nome}: Rentabilidade {rentab}, "
                f"Preço R${preco_unitario}, Vence em {vencimento}\n"
            )

        return resumo_dados

    except Exception as e:
        print(f"Erro ao ler o banco: {e}")
        return None


def _montar_prompt(perfil_investidor=None, titulos_rankeados=None):
    """Monta o prompt do Gemini com TODA a personalização do cliente:
    perfil/risco, objetivo, nível de experiência, valor inicial, aporte mensal,
    prazo (meses/anos), títulos rankeados e META_TEMPORAL (IPCA/Selic via perfil).
    Retorna a string do prompt, ou None se não houver dados de mercado."""
    if not perfil_investidor:
        perfil_investidor = {
            "valor": 10000,
            "prazo": "longo prazo (acima de 5 anos)",
            "objetivo": "aposentadoria",
            "tolerancia_risco": "conservador",
            "conhecimento_descricao": "iniciante",
        }

    # Monta contexto de mercado — usa dados enriquecidos do pipeline se disponíveis
    if titulos_rankeados:
        dados_mercado = (
            "DADOS DO TESOURO DIRETO — ANALISADOS PELO PIPELINE QUANTITATIVO\n"
            "(ordenados por retorno real após inflação, com score de risco calculado).\n"
            "IMPORTANTE: o campo 'Rentabilidade' já vem formatado com o indexador correto "
            "(IPCA+, Selic+ ou prefixado). Copie-o LITERALMENTE no ranking — NÃO recalcule, "
            "NÃO simplifique, NÃO remova 'IPCA' ou 'Selic'.\n"
            "Cada linha inclui o ANO DE VENCIMENTO em destaque — use-o para aplicar a Regra\n"
            "de Correspondência Temporal contra o Ano Alvo do <META_TEMPORAL>.\n"
        )
        for t in titulos_rankeados:
            rentab = formatar_rentabilidade(t["nome"], t["indexador"], t["taxa_juros"])
            # Extrai o ano final do vencimento (DD/MM/AAAA) para destacar no payload.
            try:
                ano_venc = int(t["vencimento"].split("/")[-1])
            except (ValueError, AttributeError, IndexError):
                ano_venc = None
            ano_venc_txt = f" | Ano de vencimento: {ano_venc}" if ano_venc else ""
            dados_mercado += (
                f"- {t['nome']}: Rentabilidade {rentab}, "
                f"Retorno real {t['retorno_real']}% (já líquido de inflação), "
                f"Score de risco {t['score_risco']} (escala 0-1), "
                f"Preço R$ {t['preco_unitario']}, "
                f"Vence em {t['vencimento']} ({t['anos_vencimento']} anos){ano_venc_txt}\n"
            )
    else:
        dados_mercado = coletar_dados_para_ia()

    if not dados_mercado:
        return None

    valor       = perfil_investidor.get("valor", 10000)
    tolerancia  = perfil_investidor.get("tolerancia_risco", "conservador")
    objetivo    = perfil_investidor.get("objetivo_descricao", perfil_investidor.get("objetivo", "preservação de capital"))
    conhecimento = perfil_investidor.get("conhecimento_descricao", "iniciante")
    aporte      = perfil_investidor.get("aporteMensal", 0)
    confianca   = perfil_investidor.get("confianca_pct", "")
    confianca_txt = f" (classificação ML com {confianca}% de confiança)" if confianca else ""
    valor_br    = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    aporte_br   = f"{aporte:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # ── Horizonte EXATO do usuário ─────────────────────────────────────────────
    # O formulário agora captura o tempo como input livre (input number + select
    # meses/anos). Renderizamos uma frase explícita ("36 meses (3 anos)") para
    # que o LLM use esse horizonte como restrição dura no ranking.
    tempo_user = perfil_investidor.get("tempo_investimento")
    unidade_user = perfil_investidor.get("unidade_tempo", "meses")
    if tempo_user:
        tempo_int = int(tempo_user)
        if unidade_user == "anos":
            total_meses_user = tempo_int * 12
            horizonte_exato = f"{tempo_int} {'ano' if tempo_int == 1 else 'anos'} ({total_meses_user} meses)"
        else:
            total_meses_user = tempo_int
            anos_eq = round(tempo_int / 12, 1)
            horizonte_exato = f"{tempo_int} {'mês' if tempo_int == 1 else 'meses'} (~{anos_eq} anos)"
    else:
        # Fallback (chamada direta sem perfil novo): usa a descrição antiga
        horizonte_exato = perfil_investidor.get("prazo_descricao",
                          perfil_investidor.get("prazo", "a definir"))

    perfil_tom = _resolver_tom(conhecimento)
    objetivo_foco = _OBJETIVOS[_objetivo_canonico(perfil_investidor)]
    aporte_cenario = _CENARIOS_APORTE[_cenario_aporte(valor, aporte)]
    faz_aporte_txt = "Sim" if (aporte or 0) > 0 else "Não"
    total_meses_prompt = _total_meses_perfil(perfil_investidor)
    horizonte_foco = _HORIZONTES[_horizonte_classe(total_meses_prompt)]

    # ── META_TEMPORAL: ground-truth determinístico para a Regra de Correspondência ──
    # Calculado no backend (pipeline_quantitativo) e injetado via perfil_ml em app.py.
    # Tira do LLM a responsabilidade de fazer a matemática do horizonte e dá base
    # para a Regra de Fallback do Limite do Tesouro.
    ano_atual_meta     = perfil_investidor.get("ano_atual")
    ano_alvo_meta      = perfil_investidor.get("ano_alvo_resgate")
    venc_max_meta      = perfil_investidor.get("vencimento_max_disponivel") or {}
    venc_max_ano       = venc_max_meta.get("ano")
    venc_max_titulo    = venc_max_meta.get("titulo")

    if ano_atual_meta and ano_alvo_meta and venc_max_ano:
        if ano_alvo_meta > venc_max_ano:
            cenario_alinhamento = (
                f"ATENÇÃO — FALLBACK ATIVO: o Ano Alvo ({ano_alvo_meta}) supera o vencimento "
                f"mais longo disponível ({venc_max_ano}). Selecione na posicao=1 o título mais "
                f"longo da base e declare o FALLBACK no campo 'alinhamento_prazo'."
            )
        else:
            cenario_alinhamento = (
                f"Existe na base pelo menos um título cujo vencimento cobre o Ano Alvo "
                f"({ano_alvo_meta}). Priorize na posicao=1 o título cujo Ano de Vencimento "
                f"esteja MAIS PRÓXIMO de {ano_alvo_meta}."
            )
        bloco_meta_temporal = f"""
<META_TEMPORAL>
- Ano atual: {ano_atual_meta}
- Ano Alvo de Resgate do cliente (Ano atual + horizonte): {ano_alvo_meta}
- Vencimento mais longo disponível na base: {venc_max_ano} ({venc_max_titulo})
- Cenário de alinhamento: {cenario_alinhamento}
</META_TEMPORAL>
"""
    else:
        bloco_meta_temporal = ""

    prompt = f"""<DADOS_DO_CLIENTE>
- Valor disponível: R$ {valor_br}
- Aporte mensal: R$ {aporte_br}
- Horizonte de investimento (ESTRITO E EXATO): {horizonte_exato}
- Objetivo: {objetivo}
- Nível de conhecimento: {conhecimento}
- Perfil de risco: {tolerancia}{confianca_txt}
</DADOS_DO_CLIENTE>

<RESTRICAO_DE_PRAZO>
O usuário definiu um horizonte ESTRITO E EXATO de {horizonte_exato}. Você DEVE
escolher e ordenar os títulos do Tesouro Direto cujos vencimentos e
características se alinhem perfeitamente a esse prazo exato:
- Priorize títulos cuja data de vencimento esteja PRÓXIMA ou INFERIOR ao
  horizonte do usuário (evita marcação a mercado em resgate antecipado).
- Para horizontes curtos (≤ 24 meses): privilegie Tesouro Selic (liquidez
  diária) e prefixados curtos. Evite IPCA+ longo.
- Para horizontes médios (24-60 meses): equilibre Prefixado e IPCA+ médio
  com vencimentos compatíveis.
- Para horizontes longos (> 60 meses): privilegie IPCA+ e Renda+/Educa+
  cujos vencimentos cubram ou se aproximem do prazo do usuário.
A posicao=1 do ranking deve ser o título com MELHOR ALINHAMENTO ao prazo
exato, NÃO simplesmente o de maior retorno bruto.
</RESTRICAO_DE_PRAZO>
{bloco_meta_temporal}
<DADOS_DE_MERCADO fonte_unica_de_verdade="true">
{dados_mercado}
</DADOS_DE_MERCADO>

<NIVEL_DO_CLIENTE rotulo="{perfil_tom['rotulo']}">
Nível de experiência do investidor: {conhecimento}.
Adapte OBRIGATORIAMENTE linguagem, profundidade técnica, exemplos, alertas e o
glossário a esse nível — a resposta para um cliente {conhecimento} deve ser
PERCEPTIVELMENTE diferente da de outro nível (não entregue texto genérico).
Tom obrigatório: {perfil_tom['tom']}
Diretrizes de comunicação (cumpra à risca):
{perfil_tom['diretrizes']}
</NIVEL_DO_CLIENTE>

<OBJETIVO_DO_CLIENTE rotulo="{objetivo_foco['rotulo']}">
Objetivo do investidor: {objetivo}.
Adapte a análise, a estratégia, os riscos e o glossário a este objetivo:
{objetivo_foco['diretriz']}
CRUZE este objetivo com o nível de experiência ({conhecimento}): a resposta deve
refletir AMBOS os eixos (o QUE o dinheiro precisa fazer + COMO comunicar ao cliente).
</OBJETIVO_DO_CLIENTE>

<CENARIO_DE_APORTE rotulo="{aporte_cenario['rotulo']}">
Valor inicial investido: R$ {valor_br}.
Aporte mensal: R$ {aporte_br}.
O usuário fará aportes mensais? {faz_aporte_txt}.
Prazo de investimento: {horizonte_exato}.
Explique a estratégia considerando a diferença entre investimento ÚNICO e
investimento RECORRENTE:
{aporte_cenario['diretriz']}
Integre este cenário ao objetivo e ao nível de experiência — sem texto genérico.
</CENARIO_DE_APORTE>

<HORIZONTE_DE_PRAZO rotulo="{horizonte_foco['rotulo']}">
Prazo informado pelo usuário: {horizonte_exato}.
Prazo convertido para a simulação: {total_meses_prompt} meses.
Classifique e ADAPTE a resposta a este horizonte:
{horizonte_foco['diretriz']}
Explique a compatibilidade entre o prazo desejado, o VENCIMENTO do título escolhido,
a liquidez e o risco de resgate antecipado (marcação a mercado). Se o prazo desejado
ultrapassar o maior vencimento disponível (<META_TEMPORAL>), explique que a projeção
fica limitada ao vencimento do título.
Cruze este horizonte com objetivo, aporte e nível de experiência — sem texto genérico.
</HORIZONTE_DE_PRAZO>

<TAREFA>
Gere o relatório financeiro preenchendo OBRIGATORIAMENTE os CINCO campos do JSON
estruturado (response_schema). Nenhum campo pode vir vazio ou ser omitido.

CAMPO 1 — analise_macroeconomica (STRING)
PAPEL: contextualizar o cenário em UM parágrafo curto (máximo 4 linhas).
- Onde as taxas estão hoje frente ao histórico
- O que a curva de juros está sinalizando
- Como isso impacta especificamente o perfil {tolerancia}
Comece em segunda pessoa ("Você está diante de...", "Seu capital encontra...").
NÃO use cabeçalhos Markdown aqui — apenas o texto corrido do parágrafo.

CAMPO 2 — estrategia_recomendada (STRING)  ← apenas o "PORQUÊ"
PAPEL: argumentação persuasiva. Copywriting de elite. 2 a 3 parágrafos curtos.
- Apresente o RACIONAL: por que esta combinação blinda o patrimônio AGORA,
  dado o momento econômico.
- Foque em PRESERVAÇÃO DE CAPITAL, PREVISIBILIDADE e MOMENTO ECONÔMICO.
- PROIBIDO: listar títulos, citar nomes específicos, taxas ou vencimentos.
  Esses dados pertencem ao ranking_oportunidades.
- PROIBIDO: usar a palavra "ranking" ou antecipar a execução tática.
- Separe parágrafos com "\\n\\n" (duas quebras). NÃO use cabeçalhos.

CAMPO 3 — riscos_pontos_atencao (STRING)  ← alertas objetivos
PAPEL: lista de alertas em formato Markdown de BULLETS. Cada bullet começa
com "- " (hífen + espaço) seguido de UMA frase curta. Separe os bullets com
"\\n" simples. Inclua pelo menos 3 bullets cobrindo:
- Quais títulos você deve EVITAR e por quê (dado o perfil {tolerancia}).
- O que acontece em caso de RESGATE ANTECIPADO (marcação a mercado, em
  linguagem do nível {conhecimento} do cliente).
- O RISCO-CHAVE específico para este perfil (ex.: inflação corroendo prefixado,
  reinvestimento em Selic+, liquidez em vencimentos longos).
NÃO use cabeçalhos Markdown. Apenas os bullets.

CAMPO 4 — ranking_oportunidades (ARRAY)  ← apenas o "O QUÊ"
PAPEL: execução pura. Exatamente 3 itens, ordenados ESTRITAMENTE do melhor
(posicao=1) ao pior (posicao=3) segundo o perfil {tolerancia}.

Para cada item do array:
- posicao: número inteiro (1, 2 ou 3).
- nome_ativo: copie LITERALMENTE o nome do título dos dados de mercado
  (ex.: "Tesouro Prefixado 2029", "Tesouro IPCA+ 2035"). NÃO encurte, NÃO
  invente, NÃO reescreva.
- rentabilidade: copie LITERALMENTE o campo "Rentabilidade" dos dados
  (ex.: "IPCA + 7,82%", "Selic + 0,15%", "10,28%"). PRESERVE o indexador
  e o sinal "+". JAMAIS exiba só o número de um título IPCA+ ou Selic+.
- vencimento: copie LITERALMENTE a data dos dados (formato DD/MM/AAAA).
- ano_vencimento_ativo: ano (inteiro, 4 dígitos) extraído do campo vencimento
  (ex.: "15/12/2084" → 2084). Use o "Ano de vencimento" já marcado em cada
  linha dos dados de mercado.
- alinhamento_prazo: frase curta (UMA linha) declarando como o vencimento
  daquele título se relaciona com o Ano Alvo do cliente (<META_TEMPORAL>).
  Cite os anos nominalmente. Exemplos: "Alinhamento perfeito — vence em 2064,
  apenas 2 anos após o alvo 2062." | "Título mais longo disponível no Tesouro
  — vence em 2084, ainda inferior ao alvo 2110 do cliente em 26 anos (fallback
  do limite)." Veja exemplos completos na REGRA DE CORRESPONDÊNCIA TEMPORAL.
- papel_carteira: papel TÁTICO específico daquele título em UMA frase curta
  (ex.: "trava da taxa nominal no médio prazo", "proteção real contra
  inflação no longo prazo", "liquidez e baixa volatilidade").
  NÃO repita argumentos do campo estrategia_recomendada.

REGRA DE OURO: a posicao=1 é o vencedor absoluto que guiará a projeção visual
(gráfico de evolução patrimonial). O cliente verá o nome desse ativo na tela —
escolha conforme o perfil dele E o alinhamento ao Ano Alvo de <META_TEMPORAL>,
NUNCA apenas pelo retorno bruto.

CAMPO 5 — glossario (ARRAY)  ← didática
PAPEL: explicar APENAS os termos técnicos que de fato apareceram nos campos
anteriores (analise_macroeconomica, estrategia_recomendada, riscos_pontos_atencao
ou nos papel_carteira do ranking). NÃO traga termos que não foram usados.

Para cada item do array:
- termo: o termo EXATAMENTE como apareceu no relatório (ex.: "IPCA", "Selic",
  "marcação a mercado", "duration", "curva de juros", "retorno real").
- explicacao: definição clara em UMA linha, calibrada ao nível {conhecimento}.
  Iniciante → metáfora cotidiana, sem outros jargões.
  Intermediário → técnica e objetiva.
  Avançado → institucional, pode pressupor base teórica.

Quantidade típica: 3 a 6 termos. Se nenhum termo técnico foi usado (caso raro
em relatórios para iniciante), devolva um array com 1 item explicando o
indexador principal (IPCA, Selic ou Prefixado) do título vencedor.
</TAREFA>

<CHECKLIST_FINAL>
Antes de retornar o JSON, valide silenciosamente:
✔ Os CINCO campos foram preenchidos? Nenhum vazio, nenhum pulado?
✔ estrategia_recomendada está LIVRE de nomes de títulos, taxas e vencimentos?
✔ ranking_oportunidades tem EXATAMENTE 3 itens com posicao 1, 2 e 3 (sem buracos, sem repetição)?
✔ Para cada item, rentabilidade foi copiada LITERALMENTE dos dados (com "IPCA +" ou "Selic +" quando aplicável)?
✔ Para cada item, ano_vencimento_ativo é o inteiro de 4 dígitos extraído do vencimento?
✔ Para cada item, alinhamento_prazo cita Ano de Vencimento e Ano Alvo nominalmente?
✔ A posicao=1 é o título com MENOR distância ao Ano Alvo do <META_TEMPORAL>, respeitando o perfil de risco — NÃO foi escolhida pelo maior retorno bruto?
✔ Se Ano Alvo > vencimento máximo da base, o item posicao=1 declara "FALLBACK" no alinhamento_prazo?
✔ riscos_pontos_atencao usou bullets "- " (cada bullet em UMA linha)?
✔ glossario só contém termos que de fato aparecem no relatório?
✔ Nenhuma frase de estrategia_recomendada aparece, mesmo parafraseada, em algum papel_carteira?
✔ Todo o texto está em segunda pessoa? Zero saudações?
✔ O tom corresponde ao nível {conhecimento}?
Se algum item falhar, REESCREVA antes de retornar.
</CHECKLIST_FINAL>"""

    return prompt


def gerar_relatorio_financeiro(perfil_investidor=None, titulos_rankeados=None) -> dict:
    """Função PÚBLICA principal. Decide o modo e devolve o relatório (5 seções) com
    o campo interno '_origem'.

    Fluxo (previsível):
      • modo mock      → _relatorio_mock (não chama Gemini).
      • modo fallback  → _relatorio_deterministico (não chama Gemini).
      • modo real      → _montar_prompt → _chamar_gemini.
          - sucesso        → relatório real (_origem='ia_real').
          - falha + REQUIRE_GEMINI=true  → levanta GeminiObrigatorioError (sem fallback).
          - falha + REQUIRE_GEMINI=false → fallback determinístico (plano B).
    """
    modo = _modo_gemini_atual()

    if modo == "mock":
        print("[Gemini] Modo mock ativo")
        return _tag_origem(_relatorio_mock(perfil_investidor, titulos_rankeados), "mock")

    if modo == "fallback":
        print("[Gemini] Fallback determinístico ativo")
        return _tag_origem(_relatorio_deterministico(perfil_investidor, titulos_rankeados), "modo_fallback")

    # modo real
    prompt = _montar_prompt(perfil_investidor, titulos_rankeados)
    if prompt is None:
        return _falhar_ia("sem dados de mercado", perfil_investidor, titulos_rankeados)

    try:
        relatorio = _chamar_gemini(prompt)
    except Exception as e:
        return _falhar_ia(_motivo_falha(e), perfil_investidor, titulos_rankeados)

    return _tag_origem(relatorio, "ia_real")


# ── SCHEMA DA SAÍDA ESTRUTURADA (JSON) ─────────────────────────────────────────
# response_schema do modelo Gemini configurado. Quando combinado com response_mime_type=
# "application/json" na GenerateContentConfig, o modelo é OBRIGADO a devolver
# um JSON conforme este shape — sem texto livre antes/depois. Isso elimina a
# necessidade de parsing fuzzy de Markdown e dá um contrato estável para o
# orquestrador (app.py) usar dinamicamente na projeção e no ranking visual.

_RANKING_ITEM_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "posicao": types.Schema(
            type=types.Type.INTEGER,
            description="Posição no ranking. 1 = melhor opção (vencedor absoluto), 2 = segunda, 3 = terceira.",
        ),
        "nome_ativo": types.Schema(
            type=types.Type.STRING,
            description="Nome LITERAL do título copiado dos dados de mercado (ex.: 'Tesouro Prefixado 2029').",
        ),
        "rentabilidade": types.Schema(
            type=types.Type.STRING,
            description="Rentabilidade LITERAL do campo Rentabilidade dos dados (ex.: 'IPCA + 7,82%', 'Selic + 0,15%', '10,28%').",
        ),
        "vencimento": types.Schema(
            type=types.Type.STRING,
            description="Data de vencimento literal no formato DD/MM/AAAA.",
        ),
        "ano_vencimento_ativo": types.Schema(
            type=types.Type.INTEGER,
            description=(
                "Ano (inteiro 4 dígitos) extraído do campo vencimento. Ex.: '15/12/2084' → 2084. "
                "Usado pela camada de produto para comparar nominalmente com o Ano Alvo do cliente."
            ),
        ),
        "alinhamento_prazo": types.Schema(
            type=types.Type.STRING,
            description=(
                "Frase curta (UMA linha) declarando como o vencimento do título se relaciona com "
                "o Ano Alvo do cliente (<META_TEMPORAL>). DEVE citar Ano de Vencimento e Ano Alvo "
                "nominalmente. Padrões: 'Alinhamento perfeito — vence em YYYY, X anos do alvo YYYY.' "
                "ou 'Título mais longo disponível no Tesouro — vence em YYYY, inferior ao alvo YYYY "
                "em X anos (fallback do limite).'"
            ),
        ),
        "papel_carteira": types.Schema(
            type=types.Type.STRING,
            description="Papel tático específico deste título na carteira, em UMA frase curta.",
        ),
    },
    required=[
        "posicao",
        "nome_ativo",
        "rentabilidade",
        "vencimento",
        "ano_vencimento_ativo",
        "alinhamento_prazo",
        "papel_carteira",
    ],
)

# Cada termo do glossário é um par {termo, explicação} — permite renderização
# como lista de definições no frontend (bullet "**termo** — explicação").
_GLOSSARIO_ITEM_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "termo": types.Schema(
            type=types.Type.STRING,
            description="Termo técnico exato como apareceu no relatório (ex.: 'IPCA', 'duration', 'marcação a mercado').",
        ),
        "explicacao": types.Schema(
            type=types.Type.STRING,
            description="Definição clara em UMA linha, calibrada ao nível de conhecimento do cliente.",
        ),
    },
    required=["termo", "explicacao"],
)

# Schema UNIFICADO — cobre as 5 seções fundamentais do relatório:
#   1. analise_macroeconomica   (STRING)
#   2. estrategia_recomendada   (STRING)
#   3. riscos_pontos_atencao    (STRING)   ← reincorporado
#   4. ranking_oportunidades    (ARRAY[5])
#   5. glossario                (ARRAY[N]) ← reincorporado
_RELATORIO_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "analise_macroeconomica": types.Schema(
            type=types.Type.STRING,
            description="Parágrafo curto (máx. 4 linhas) sobre cenário macro e curva de juros, em segunda pessoa.",
        ),
        "estrategia_recomendada": types.Schema(
            type=types.Type.STRING,
            description="2-3 parágrafos curtos com o RACIONAL da estratégia. Não cita nomes/taxas/vencimentos.",
        ),
        "riscos_pontos_atencao": types.Schema(
            type=types.Type.STRING,
            description=(
                "Bullets curtos (um por linha, iniciados por '- ') com alertas objetivos: "
                "títulos a evitar e por quê, marcação a mercado em caso de resgate antecipado, "
                "risco-chave específico do perfil. UMA frase por bullet."
            ),
        ),
        "ranking_oportunidades": types.Schema(
            type=types.Type.ARRAY,
            description="Lista de exatamente 3 ativos, ordenados estritamente do melhor (posicao=1) ao pior.",
            items=_RANKING_ITEM_SCHEMA,
        ),
        "glossario": types.Schema(
            type=types.Type.ARRAY,
            description=(
                "Lista de termos técnicos que APARECEM no relatório, com explicação de UMA linha. "
                "Profundidade calibrada ao nível de conhecimento do cliente."
            ),
            items=_GLOSSARIO_ITEM_SCHEMA,
        ),
    },
    required=[
        "analise_macroeconomica",
        "estrategia_recomendada",
        "riscos_pontos_atencao",
        "ranking_oportunidades",
        "glossario",
    ],
)


# ── HELPER DE APRESENTAÇÃO: JSON estruturado → Markdown ────────────────────────
def montar_relatorio_markdown(relatorio: dict) -> str:
    """
    Converte o JSON estruturado da IA em Markdown pronto para o frontend
    (renderizado por marked.js). Cobre as 5 seções do relatório completo:
      1. Análise Macroeconômica
      2. Riscos e Pontos de Atenção
      3. Estratégia Recomendada
      4. Ranking de Oportunidades  ← posição é interpolada DINAMICAMENTE da IA
      5. Glossário

    A ordem em tela é Macro → Riscos → Estratégia → Ranking → Glossário, que
    corresponde ao fluxo narrativo de copywriting (contexto → alerta → racional
    → execução → didática).

    Defesa em profundidade: ordena o ranking pelo campo 'posicao' caso o
    modelo entregue o array fora de ordem.
    """
    analise    = (relatorio.get("analise_macroeconomica") or "").strip()
    estrategia = (relatorio.get("estrategia_recomendada") or "").strip()
    riscos     = (relatorio.get("riscos_pontos_atencao") or "").strip()
    ranking    = relatorio.get("ranking_oportunidades") or []
    glossario  = relatorio.get("glossario") or []

    partes = []

    if analise:
        partes.append("## 📊 ANÁLISE MACROECONÔMICA\n\n" + analise)

    if riscos:
        partes.append("## ⚠️ RISCOS E PONTOS DE ATENÇÃO\n\n" + riscos)

    if estrategia:
        partes.append("## 📌 ESTRATÉGIA RECOMENDADA\n\n" + estrategia)

    if ranking:
        ranking_ordenado = sorted(ranking, key=lambda r: r.get("posicao") or 999)
        linhas = []
        for item in ranking_ordenado:
            posicao    = item.get("posicao", "?")
            nome       = (item.get("nome_ativo") or "Ativo").strip()
            rentab     = (item.get("rentabilidade") or "").strip()
            venc       = (item.get("vencimento") or "").strip()
            papel      = (item.get("papel_carteira") or "").strip()
            alinhamento = (item.get("alinhamento_prazo") or "").strip()
            # Formato dinâmico exigido pela camada de produto:
            # * <Nome> (<N>ª Opção) — Rentabilidade: ... | Vencimento: ... | Papel na carteira: ...
            linhas.append(
                f"* **{nome} ({posicao}ª Opção)** — "
                f"Rentabilidade: {rentab} | Vencimento: {venc} | Papel na carteira: {papel}"
            )
            # Linha auxiliar com o alinhamento temporal explícito — torna visível
            # quando estamos no FALLBACK do limite do Tesouro (Ano Alvo > 2084).
            if alinhamento:
                linhas.append(f"    - 🎯 *Alinhamento de prazo:* {alinhamento}")
        partes.append("## 🏆 RANKING DE OPORTUNIDADES\n\n" + "\n".join(linhas))

    if glossario:
        linhas_g = []
        for g in glossario:
            # _capitalizar_termo mexe SÓ na primeira letra — preserva siglas
            # (IPCA, VPL, MtM) e maiúsculas internas (Macaulay, Fisher).
            termo = _capitalizar_termo(g.get("termo") or "")
            expl  = (g.get("explicacao") or "").strip()
            if termo and expl:
                linhas_g.append(f"- **{termo}** — {expl}")
        if linhas_g:
            partes.append("## 💡 GLOSSÁRIO RÁPIDO\n\n" + "\n".join(linhas_g))

    return "\n\n".join(partes)


# Esperas (s) entre retries de erros recuperáveis (503/timeout E 429/rate-limit): 2 → 4 → 8.
# 429 no free-tier do Gemini Flash é tipicamente limite POR MINUTO (transitório, a chave
# volta a responder em segundos) — por isso é re-tentado, não falha direto. Sem cooldown global.
_ESPERAS_RETRY = [2, 4, 8]


def _tag_origem(relatorio: dict, origem: str) -> dict:
    """Marca internamente de onde veio a resposta (ia_real / mock / fallback_*).
    Campo extra '_origem' — não faz parte do contrato de 5 seções e não quebra a UI."""
    if isinstance(relatorio, dict):
        relatorio["_origem"] = origem
    return relatorio

# Config de geração compartilhada — temperatura calibrada para precisão financeira
# com fluidez de copywriting; system_instruction injeta a persona em toda chamada.
#
# Limite de saída suficiente para o JSON estruturado de 5 seções, sem manter
# um teto excessivo que incentive consumo desnecessário de tokens.
_GEN_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    temperature=0.5,
    top_p=0.9,
    max_output_tokens=6144,
    # Structured Output: força o modelo a devolver JSON conforme _RELATORIO_SCHEMA.
    # Combinação response_mime_type + response_schema = parsing 100% confiável,
    # sem precisar de regex/marked.js para extrair o ranking. Quem define a
    # ordem dos ativos passa a ser exclusivamente a IA, e o backend lê a posição
    # dinamicamente para alimentar o gráfico e o texto.
    response_mime_type="application/json",
    response_schema=_RELATORIO_SCHEMA,
)


_MSG_IA_INDISPONIVEL = "O relatório foi gerado em modo determinístico do RENDE-IA."


def _modo_gemini_atual() -> str:
    modo = (GEMINI_MODE or "real").strip().lower()
    if modo not in _MODOS_GEMINI_VALIDOS:
        print("[Gemini] RENDE_IA_GEMINI_MODE inválido em runtime. Usando modo real.")
        return "real"
    return modo


def _require_gemini_atual() -> bool:
    """Lê o flag de IA obrigatória (atributo de módulo, para testes poderem alternar)."""
    return bool(REQUIRE_GEMINI)


def _falhar_ia(motivo: str, perfil_investidor=None, titulos_rankeados=None) -> dict:
    """Ponto ÚNICO de decisão quando a IA real falha (regra final de fallback):
      • REQUIRE_GEMINI=true  → levanta GeminiObrigatorioError (NUNCA fallback);
      • REQUIRE_GEMINI=false → fallback determinístico (plano B)."""
    print(f"[Gemini] Falha na IA real: {motivo}")
    if _require_gemini_atual():
        print("[Gemini] Fallback bloqueado por RENDE_IA_REQUIRE_GEMINI=true")
        raise GeminiObrigatorioError(motivo)
    return _acionar_fallback(motivo, perfil_investidor, titulos_rankeados)


class RespostaIAInvalida(Exception):
    """Resposta do Gemini que não é JSON válido ou não cumpre o contrato de 5 seções."""


def _eh_429(exc: Exception) -> bool:
    """Detector ÚNICO de 429/quota/rate-limit."""
    s = str(exc).lower()
    return any(t in s for t in ("429", "resource_exhausted", "quota", "rate-limit", "rate limit"))


def _eh_429_diario(exc: Exception) -> bool:
    """429 de cota DIÁRIA (RequestsPerDay do free-tier). Re-tentar é INÚTIL: o
    contador só reseta à meia-noite no horário do Pacífico, não em segundos. Por
    isso falha rápido (sem gastar os 14s de backoff). Distinto do 429 por minuto,
    esse sim transitório e re-tentável."""
    s = str(exc).lower()
    return _eh_429(exc) and any(t in s for t in ("perday", "per day", "requests_per_day", "per_day"))


def _eh_transitorio(exc: Exception) -> bool:
    """Erro transitório que vale re-tentar (sobrecarga/timeout do modelo)."""
    s = str(exc).upper()
    return any(t in s for t in ("503", "UNAVAILABLE", "TIMEOUT", "DEADLINE_EXCEEDED", "TEMPORAR"))


def _motivo_falha(exc: Exception) -> str:
    """Motivo sanitizado e curto da falha (para log e código de origem). Sem detalhe técnico."""
    if isinstance(exc, RespostaIAInvalida):
        return "resposta inválida"
    if _eh_429(exc):
        return "quota/429"
    if _eh_transitorio(exc):
        return "timeout/503"
    return "erro na chamada"


def _formatar_percentual(valor, default: float) -> str:
    try:
        return _formatar_taxa_br(float(valor))
    except (TypeError, ValueError):
        return _formatar_taxa_br(default)


def _extrair_ano_vencimento(vencimento) -> int | None:
    try:
        return int(str(vencimento).split("/")[-1])
    except (TypeError, ValueError, IndexError):
        return None


def _titulos_reais_para_fallback(titulos_rankeados=None) -> list[dict]:
    if titulos_rankeados:
        return [dict(t) for t in titulos_rankeados if isinstance(t, dict)]

    try:
        conexao = sqlite3.connect("tesouro_direto.db")
        cursor = conexao.cursor()
        cursor.execute("SELECT nome, indexador, taxa_juros, preco_unitario, vencimento FROM titulos")
        rows = cursor.fetchall()
        conexao.close()
    except Exception:
        return []

    return [
        {
            "nome": nome,
            "indexador": indexador,
            "taxa_juros": taxa_juros,
            "preco_unitario": preco_unitario,
            "vencimento": vencimento,
            "retorno_real": taxa_juros,
            "score_risco": 0.5,
            "anos_vencimento": 0,
        }
        for nome, indexador, taxa_juros, preco_unitario, vencimento in rows
    ]


def _descrever_horizonte(perfil_investidor: dict) -> str:
    tempo = perfil_investidor.get("tempo_investimento")
    unidade = perfil_investidor.get("unidade_tempo", "meses")
    if tempo:
        try:
            tempo_int = int(tempo)
        except (TypeError, ValueError):
            return str(perfil_investidor.get("prazo_descricao") or perfil_investidor.get("prazo") or "a definir")
        if unidade == "anos":
            return f"{tempo_int} {'ano' if tempo_int == 1 else 'anos'}"
        return f"{tempo_int} {'mês' if tempo_int == 1 else 'meses'}"
    return str(perfil_investidor.get("prazo_descricao") or perfil_investidor.get("prazo") or "a definir")


def _descrever_alinhamento_prazo(ano_vencimento: int | None, perfil_investidor: dict) -> str:
    ano_alvo = perfil_investidor.get("ano_alvo_resgate")
    venc_max = perfil_investidor.get("vencimento_max_disponivel") or {}
    ano_max = venc_max.get("ano")

    if not ano_vencimento or not ano_alvo:
        return "Alinhamento estimado a partir do vencimento informado pelo pipeline quantitativo."

    try:
        ano_alvo = int(ano_alvo)
        ano_max = int(ano_max) if ano_max else None
    except (TypeError, ValueError):
        return "Alinhamento estimado a partir do vencimento informado pelo pipeline quantitativo."

    diferenca = ano_vencimento - ano_alvo
    distancia = abs(diferenca)

    if ano_max and ano_alvo > ano_max and ano_vencimento == ano_max:
        return (
            f"Título mais longo disponível no Tesouro - vence em {ano_vencimento}, "
            f"ainda inferior ao alvo {ano_alvo} em {distancia} anos (fallback do limite)."
        )
    if distancia <= 2:
        return f"Alinhamento próximo - vence em {ano_vencimento}, {distancia} anos do alvo {ano_alvo}."
    if diferenca > 0:
        return f"Alinhamento aceitável - vence em {ano_vencimento}, {distancia} anos após o alvo {ano_alvo}."
    return (
        f"Vence antes do alvo - vence em {ano_vencimento}, {distancia} anos antes do alvo {ano_alvo}; "
        "requer reinvestimento no caminho."
    )


def _montar_ranking_deterministico(titulos_reais: list[dict], perfil_investidor: dict) -> list[dict]:
    ranking = []
    for posicao, titulo in enumerate(titulos_reais[:3], start=1):
        nome = str(titulo.get("nome") or titulo.get("nome_ativo") or "").strip()
        if not nome:
            continue
        indexador = str(titulo.get("indexador") or "")
        taxa = titulo.get("taxa_juros") or 0
        vencimento = str(titulo.get("vencimento") or "").strip()
        ano_vencimento = _extrair_ano_vencimento(vencimento)
        ranking.append({
            "posicao": posicao,
            "nome_ativo": nome,
            "rentabilidade": formatar_rentabilidade(nome, indexador, taxa),
            "vencimento": vencimento,
            "ano_vencimento_ativo": ano_vencimento or 0,
            "alinhamento_prazo": _descrever_alinhamento_prazo(ano_vencimento, perfil_investidor),
            "papel_carteira": _papel_carteira_deterministico(nome, indexador),
        })
    return ranking


def _papel_carteira_deterministico(nome: str, indexador: str) -> str:
    n = (nome or "").lower()
    idx = (indexador or "").lower()
    if "selic" in n or "selic" in idx:
        return "liquidez e baixa volatilidade para preservar flexibilidade."
    if "ipca" in n or "renda+" in n or "educa+" in n or "ipca" in idx:
        return "proteção real contra inflação em prazo compatível com o objetivo."
    if "prefixado" in n or "prefixado" in idx:
        return "trava de taxa nominal para aumentar previsibilidade do retorno."
    return "diversificação tática dentro do universo de títulos públicos disponíveis."


def _relatorio_deterministico(perfil_investidor=None, titulos_rankeados=None) -> dict:
    perfil_investidor = perfil_investidor or {}
    titulos_reais = _titulos_reais_para_fallback(titulos_rankeados)
    ranking = _montar_ranking_deterministico(titulos_reais, perfil_investidor)

    tolerancia = perfil_investidor.get("tolerancia_risco", "conservador")
    conhecimento = perfil_investidor.get("conhecimento_descricao", "intermediário")
    nivel = _nivel_canonico(conhecimento)
    obj_foco = _OBJETIVOS[_objetivo_canonico(perfil_investidor)]
    aporte_cenario = _CENARIOS_APORTE[_cenario_aporte(
        perfil_investidor.get("valor", 0), perfil_investidor.get("aporteMensal", 0))]
    horizonte_foco = _HORIZONTES[_horizonte_classe(_total_meses_perfil(perfil_investidor))]
    objetivo = perfil_investidor.get("objetivo_descricao", perfil_investidor.get("objetivo", "preservação de capital"))
    horizonte = _descrever_horizonte(perfil_investidor)
    ipca = _formatar_percentual(perfil_investidor.get("ipca_focus_pct"), 5.30)
    selic = _formatar_percentual(perfil_investidor.get("selic_focus_pct"), 13.75)
    vencedor = ranking[0]["nome_ativo"] if ranking else "o título com melhor aderência no pipeline quantitativo"

    # Cenário macro comum a todos os níveis (preserva IPCA/Selic Focus, horizonte e
    # perfil). O fechamento de cada seção é calibrado ao nível de experiência logo
    # abaixo — assim iniciante/intermediário/avançado recebem linguagem e profundidade
    # PERCEPTIVELMENTE diferentes mesmo no fallback determinístico.
    cenario_base = (
        f"{_MSG_IA_INDISPONIVEL} Você está diante de um cenário com IPCA projetado em {ipca}% "
        f"e Selic em {selic}%, em que inflação, retorno real, vencimento e liquidez precisam "
        f"ser balanceados para o horizonte de {horizonte} e para um perfil {tolerancia}."
    )

    if nivel == "iniciante":
        analise = (
            cenario_base + " Em palavras simples: o IPCA mede a inflação e a Selic é o juro básico "
            "do país; juntos eles mostram o quanto o seu dinheiro realmente rende depois de "
            "descontar o aumento dos preços."
        )
        estrategia = (
            f"De forma simples e segura, a referência desta simulação é {vencedor}, escolhida entre "
            "títulos reais do Tesouro Direto pelo pipeline. A ideia é proteger o seu dinheiro e ter "
            "previsibilidade, sem correr risco desnecessário.\n\n"
            f"Para o objetivo de {objetivo}, lembre-se de um ponto importante: a maior taxa nominal "
            "nem sempre é a melhor escolha. Compare com calma o prazo, a liquidez e o quanto o título "
            "rende acima da inflação."
        )
        riscos = (
            "- Se você resgatar antes do vencimento, o título passa por marcação a mercado e pode "
            "valer menos do que você esperava naquele dia.\n"
            "- O imposto de renda segue uma tabela regressiva: quanto menos tempo investido, maior "
            "o desconto; por isso ter pressa costuma custar caro.\n"
            "- Títulos muito longos podem ser difíceis de usar se você precisar do dinheiro antes da data."
        )
        glossario = [
            {"termo": "IPCA", "explicacao": "É o índice que mede a inflação — o quanto os preços sobem ao longo do ano."},
            {"termo": "Selic", "explicacao": "É o juro básico do país; quando ela sobe, os investimentos seguros tendem a render mais."},
            {"termo": "retorno real", "explicacao": "É o ganho que sobra depois de descontar a inflação do período."},
            {"termo": "vencimento", "explicacao": "É a data em que o título termina e paga o que foi combinado."},
            {"termo": "marcação a mercado", "explicacao": "É a variação diária do preço do título caso você queira vendê-lo antes do vencimento."},
            {"termo": "liquidez", "explicacao": "É a facilidade de transformar o investimento em dinheiro quando você precisar."},
        ]
    elif nivel == "avancado":
        analise = (
            cenario_base + " Tecnicamente, a inclinação da curva de juros e o nível atual da Selic "
            "definem o carrego; avalie duration, risco de reinvestimento e o prêmio real (Fisher) "
            "antes de fixar a posição."
        )
        estrategia = (
            f"O candidato tático desta simulação é {vencedor}, derivado do ranqueamento quantitativo "
            "por retorno real e score de risco. O racional prioriza aderência de duration ao "
            "horizonte e eficiência tributária, não o maior cupom nominal.\n\n"
            f"Para {objetivo}, pondere marcação a mercado em resgate antecipado, risco de "
            "reinvestimento em pós-fixados e o spread sobre o livre de risco ao comparar indexadores."
        )
        riscos = (
            "- Resgate antecipado expõe a posição à marcação a mercado, função da duration e do "
            "deslocamento da curva de juros.\n"
            "- O imposto de renda regressivo reduz o retorno líquido e altera a comparação entre "
            "prazos; modele o resultado líquido, não o bruto.\n"
            "- Pós-fixados (Selic+) carregam risco de reinvestimento; prefixados longos carregam "
            "risco de marcação se a curva abrir."
        )
        glossario = [
            {"termo": "duration", "explicacao": "Sensibilidade do preço do título a variações na taxa de juros."},
            {"termo": "marcação a mercado", "explicacao": "Reprecificação diária do título a valor presente pela curva vigente."},
            {"termo": "risco de reinvestimento", "explicacao": "Risco de reinvestir fluxos futuros a taxas inferiores às atuais."},
            {"termo": "retorno real", "explicacao": "Retorno líquido de inflação, via composição de Fisher."},
            {"termo": "curva de juros", "explicacao": "Estrutura a termo das taxas que baliza o preço de cada vencimento."},
        ]
    else:  # intermediário (padrão) — linguagem consultiva, trade-offs sem tecnicismo excessivo
        analise = cenario_base
        estrategia = (
            f"A referência tática desta simulação é {vencedor}, selecionada a partir dos títulos reais "
            "processados pelo pipeline quantitativo. A escolha prioriza aderência ao prazo informado, "
            "previsibilidade e proteção do capital, sem extrapolar dados fora da base disponível.\n\n"
            f"Para o objetivo de {objetivo}, avalie o trade-off entre taxa nominal, inflação, retorno "
            "real, liquidez e vencimento antes de assumir que a maior taxa nominal é a melhor escolha."
        )
        riscos = (
            "- Resgates antes do vencimento podem sofrer marcação a mercado e alterar o valor recebido.\n"
            "- O imposto de renda segue tabela regressiva e reduz o retorno líquido, especialmente em prazos curtos.\n"
            "- Títulos longos exigem atenção à liquidez se o objetivo tiver data rígida."
        )
        glossario = [
            {"termo": "IPCA", "explicacao": "Índice usado como referência para medir a inflação oficial no período."},
            {"termo": "Selic", "explicacao": "Taxa básica de juros que influencia a remuneração de títulos pós-fixados."},
            {"termo": "retorno real", "explicacao": "Ganho estimado depois de descontar a inflação projetada."},
            {"termo": "vencimento", "explicacao": "Data em que o título encerra e paga as condições contratadas."},
            {"termo": "marcação a mercado", "explicacao": "Atualização diária do preço do título antes do vencimento."},
        ]

    # Cruza o EIXO DO OBJETIVO (o que o dinheiro precisa fazer) com a linguagem já
    # calibrada por nível acima — assim reserva/juros/bem/render geram estratégia e
    # alertas perceptivelmente diferentes mesmo no fallback determinístico.
    estrategia = estrategia + "\n\n" + obj_foco["estrategia_fb"]
    riscos = riscos + "\n" + obj_foco["risco_fb"]

    # Cruza o EIXO DO APORTE (único vs. recorrente, e magnitude) — diferencia quem
    # investe uma única vez de quem aporta todo mês, sem falar em disciplina de
    # aportes quando aporte = 0.
    estrategia = estrategia + "\n\n" + aporte_cenario["estrategia_fb"]
    riscos = riscos + "\n" + aporte_cenario["risco_fb"]

    # Cruza o EIXO DO HORIZONTE (curto/médio/longo) — diferencia 6 meses de 10 anos.
    estrategia = estrategia + "\n\n" + horizonte_foco["estrategia_fb"]
    riscos = riscos + "\n" + horizonte_foco["risco_fb"]

    # Quando o prazo desejado supera o maior vencimento da base, sinaliza que a
    # projeção fica limitada ao vencimento do título (mesma regra do alerta_limite).
    if _prazo_excede_vencimento_max(perfil_investidor):
        riscos = riscos + (
            "\n- O prazo desejado ultrapassa o maior vencimento disponível no Tesouro: a "
            "projeção fica limitada ao vencimento do título recomendado."
        )

    return {
        "analise_macroeconomica": analise,
        "estrategia_recomendada": estrategia,
        "riscos_pontos_atencao": riscos,
        "ranking_oportunidades": ranking,
        "glossario": glossario,
    }


def _relatorio_tem_contrato_minimo(relatorio: dict) -> bool:
    if not isinstance(relatorio, dict):
        return False
    campos = [
        "analise_macroeconomica",
        "estrategia_recomendada",
        "riscos_pontos_atencao",
        "ranking_oportunidades",
        "glossario",
    ]
    return all(bool(relatorio.get(campo)) for campo in campos)


def _relatorio_mock(perfil_investidor=None, titulos_rankeados=None) -> dict:
    """Resposta MOCK estruturada (modo mock) — não chama Gemini, não é o fallback
    determinístico. Usa títulos reais no ranking para manter o contrato consistente."""
    ranking = _montar_ranking_deterministico(
        _titulos_reais_para_fallback(titulos_rankeados), perfil_investidor or {})
    return {
        "analise_macroeconomica": "[MOCK] Resposta simulada para testes — Gemini não foi chamado.",
        "estrategia_recomendada": "[MOCK] Estratégia simulada de demonstração.\n\n[MOCK] Sem chamada real à IA.",
        "riscos_pontos_atencao": "- [MOCK] Alerta simulado de exemplo.",
        "ranking_oportunidades": ranking,
        "glossario": [{"termo": "IPCA", "explicacao": "[MOCK] Índice de inflação (exemplo)."}],
    }


def _acionar_fallback(motivo: str, perfil_investidor=None, titulos_rankeados=None) -> dict:
    """Fallback determinístico, com código de origem derivado do motivo.
    (Origem sem termos sensíveis — o detector de vazamento proíbe 'quota'/'429'.)"""
    print(f"[Gemini] Fallback determinístico acionado: {motivo}")
    if "429" in motivo:
        origem = "fallback_cota"
    elif "inválida" in motivo:
        origem = "fallback_schema"
    else:
        origem = "fallback_erro"
    return _tag_origem(_relatorio_deterministico(perfil_investidor, titulos_rankeados), origem)


def _validar_resposta(resposta) -> dict:
    """Faz o parsing do JSON e garante as 5 seções. Levanta RespostaIAInvalida se falhar."""
    try:
        relatorio = json.loads(resposta.text)
    except (TypeError, json.JSONDecodeError) as e:
        raise RespostaIAInvalida("json") from e
    if not _relatorio_tem_contrato_minimo(relatorio):
        raise RespostaIAInvalida("schema")
    return relatorio


def _chamar_gemini(prompt: str) -> dict:
    """ÚNICA função que chama generate_content. Faz retry de erro recuperável
    (503/timeout E 429/rate-limit). NÃO contém fallback: devolve o relatório validado
    ou levanta a exceção (429 persistente, schema inválido, etc.) para o nível superior
    decidir (_falhar_ia)."""
    modelo = modelo_gemini_configurado()
    print(f"[Gemini] Chamada real iniciada | modelo={modelo}")
    for tentativa in range(len(_ESPERAS_RETRY) + 1):
        try:
            print(f"[Gemini] API request generate_content | modelo={modelo}")
            resposta = client.models.generate_content(
                model=modelo, contents=prompt, config=_GEN_CONFIG,
            )
        except Exception as e:
            # 429 por minuto (rate-limit) e 503/timeout são re-tentáveis; 429 de
            # cota DIÁRIA não é (só reseta à meia-noite PT) → falha rápido.
            recuperavel = _eh_transitorio(e) or (_eh_429(e) and not _eh_429_diario(e))
            if recuperavel and tentativa < len(_ESPERAS_RETRY):
                espera = _ESPERAS_RETRY[tentativa]
                rotulo = "rate-limit/429" if _eh_429(e) else "transitório (503/timeout)"
                print(f"[Gemini] Erro {rotulo}. Retry "
                      f"{tentativa + 1}/{len(_ESPERAS_RETRY)} em {espera}s.")
                time.sleep(espera)
                continue
            raise
        relatorio = _validar_resposta(resposta)  # pode levantar RespostaIAInvalida
        print(f"[Gemini] API response recebida | modelo={modelo} | status=sucesso")
        return relatorio
    # Defensivo: esgotou retries transitórios sem sucesso.
    raise RuntimeError("503/timeout após retries")


if __name__ == "__main__":
    meu_perfil = {
        "valor": 10000,
        "prazo": "longo prazo (acima de 5 anos)",
        "objetivo": "aposentadoria",
        "tolerancia_risco": "conservador",
        "conhecimento_descricao": "iniciante",
    }
    print("🤖 Consultor IA acordando e lendo seus dados do banco...")
    print("🧠 Analisando o mercado e gerando o JSON estruturado...\n")
    relatorio = gerar_relatorio_financeiro(perfil_investidor=meu_perfil)

    print("=" * 50)
    print("        📦 JSON ESTRUTURADO DA IA 📦        ")
    print("=" * 50 + "\n")
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))

    print("\n" + "=" * 50)
    print("        📊 RELATÓRIO RENDERIZADO 📊        ")
    print("=" * 50 + "\n")
    print(montar_relatorio_markdown(relatorio))
    print("\n" + "=" * 50)
