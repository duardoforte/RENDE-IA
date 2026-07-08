// Respostas mockadas do POST /api/analise — espelham o contrato real do backend.
// Mantém os testes determinísticos e sem custo de chamada ao Gemini.

const projecaoBase = (totalMeses) => {
  const meses = Array.from({ length: totalMeses + 1 }, (_, i) => i);
  const montante = meses.map((m) => 10000 * Math.pow(1.01, m));
  const capital = meses.map((m) => 10000 + 300 * m);
  const juros = meses.map((m, i) => montante[i] - capital[i]);
  return {
    meses_anos: meses,
    capital_investido: capital,
    juros_acumulados: juros,
    montante_total: montante,
    montante_final: montante[totalMeses],
    capital_final: capital[totalMeses],
    juros_totais: juros[totalMeses],
    taxa_anual_pct: 12.69,
    total_meses: totalMeses,
    tempo_investimento: totalMeses,
    unidade_tempo: "meses",
    aporte_mensal: 300,
  };
};

const rankingOk = [
  { posicao: 1, nome_ativo: "Tesouro Prefixado 2029", rentabilidade: "14,86%", vencimento: "01/01/2029", ano_vencimento_ativo: 2029, alinhamento_prazo: "Vence em 2029, próximo do alvo.", papel_carteira: "Trava de taxa nominal." },
  { posicao: 2, nome_ativo: "Tesouro Educa+ 2027", rentabilidade: "IPCA + 8,64%", vencimento: "15/12/2031", ano_vencimento_ativo: 2031, alinhamento_prazo: "Vence em 2031, proteção real.", papel_carteira: "Proteção contra inflação." },
  { posicao: 3, nome_ativo: "Tesouro Prefixado 2032", rentabilidade: "14,85%", vencimento: "01/01/2032", ano_vencimento_ativo: 2032, alinhamento_prazo: "Vence em 2032, taxa fixa longa.", papel_carteira: "Diversificação de prazo." },
];

// Resposta de SUCESSO sem alerta de limite
const respostaOk = {
  perfil_ml: { perfil_classificado: "conservador", confianca_pct: 90.3, distribuicao_prob: {} },
  analise_quantitativa: { titulos_recomendados: [], ipca_focus_pct: 5.3 },
  relatorio_markdown:
    "## 📊 ANÁLISE MACROECONÔMICA\n\nVocê está diante de um cenário de juros altos.\n\n" +
    "## 🏆 RANKING DE OPORTUNIDADES\n\n" +
    "* **Tesouro Prefixado 2029 (1ª Opção)** — Rentabilidade: 14,86% | Vencimento: 01/01/2029 | Papel na carteira: Trava de taxa.",
  relatorio_estruturado: {
    analise_macroeconomica: "Você está diante de um cenário de juros altos.",
    estrategia_recomendada: "Racional da estratégia.",
    riscos_pontos_atencao: "- Evite prefixado longo.",
    ranking_oportunidades: rankingOk,
    glossario: [{ termo: "IPCA", explicacao: "Índice oficial de inflação." }],
  },
  dados_projecao: { ...projecaoBase(96), nome_ativo_vencedor: "Tesouro Prefixado 2029" },
  alerta_limite: { excedido: false, tipo: null, linha_vertical_meses: 30 },
  grafico_alocacao_b64: "",
};

// Resposta com ALERTA de limite (tesouro_limit)
const respostaAlerta = {
  ...respostaOk,
  dados_projecao: { ...projecaoBase(840), nome_ativo_vencedor: "Tesouro RendA+ Aposentadoria Extra 2065" },
  alerta_limite: {
    excedido: true,
    tipo: "tesouro_limit",
    linha_vertical_meses: 702,
    prazo_usuario_meses: 840,
    anos_a_descoberto: 11.5,
    prazo_max_anos: 58.5,
    titulo_mais_longo: "Tesouro RendA+ Aposentadoria Extra 2065",
  },
};

// Resposta de FALLBACK determinístico (Gemini falhou por 429/quota/timeout/503).
// Espelha o que o backend devolve quando a IA está indisponível: todas as 5 seções
// preenchidas, mensagem amigável, ranking de títulos REAIS — e NENHUM erro técnico.
const respostaFallback = {
  ...respostaOk,
  relatorio_markdown:
    "## 📊 ANÁLISE MACROECONÔMICA\n\n" +
    "A análise textual avançada ficou temporariamente indisponível. A simulação abaixo " +
    "foi gerada com base nos cálculos determinísticos do sistema.\n\n" +
    "## ⚠️ RISCOS E PONTOS DE ATENÇÃO\n\n- Em resgate antecipado há marcação a mercado.\n\n" +
    "## 📌 ESTRATÉGIA RECOMENDADA\n\nFoco em liquidez e preservação de capital.\n\n" +
    "## 🏆 RANKING DE OPORTUNIDADES\n\n" +
    "* **Tesouro Prefixado 2029 (1ª Opção)** — Rentabilidade: 14,86% | Vencimento: 01/01/2029 | Papel na carteira: Trava de taxa.\n\n" +
    "## 💡 GLOSSÁRIO RÁPIDO\n\n- **IPCA** — Índice oficial de inflação.",
};

module.exports = { respostaOk, respostaAlerta, respostaFallback };
