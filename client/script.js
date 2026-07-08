// Chamada relativa: o próprio FastAPI serve este frontend (StaticFiles em "/"),
// então as requisições vão para a MESMA origem — herdam o HTTPS do domínio em
// produção e dispensam CORS/mixed-content. Em dev local (uvicorn na 8000) também
// funciona, pois a página é servida pela mesma porta. Para apontar para uma API
// externa, defina uma URL absoluta aqui (ex.: "https://rende-ia.com.br").
const API_URL = "";

/* ─── TYPING ANIMATION ──────────────────────────────────────────────────────── */
const fullText = "Encontrando a melhor opção de renda fixa para o seu perfil conservador...";
let idx = 0;

function typeEffect() {
  if (idx < fullText.length) {
    document.getElementById("typed-text").textContent += fullText.charAt(idx++);
    setTimeout(typeEffect, 32);
  } else {
    document.getElementById("subtitle").classList.add("show");
    document.getElementById("buttons").classList.add("show");
    setTimeout(() => document.getElementById("panel").classList.add("show"), 280);
  }
}
typeEffect();

/* ─── TEXT-TO-SPEECH (WEB SPEECH API) ───────────────────────────────────── */
const TTS_SUPORTADO = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
// === EDITE AQUI: mensagem inicial do narrador ===
const TTS_MENSAGEM_BOAS_VINDAS =
  "Olá eu sou a Queli, sou a sua assistente inteligente de investimentos e vou pedir para você responder algumas perguntas rápidas a seguir, e depois irei traçar a estratégia mais segura e rentável para você.";

// === EDITE AQUI: roteiro falado de cada etapa do formulário ===
// Use as chaves s1, s2, s3, s4 e s5 para controlar exatamente o que o narrador diz.
// Estes textos NÃO precisam ser iguais ao texto visual da tela.
const TTS_NARRACOES_ETAPAS = {
  s1: "Me diga o quantoo você tem para investir hojee.Se ainda não tiver um valor inicial, pode deixar em branco. ",
  s2: "você pretende fazer depósitos mensais?",
  s3: "Escolha o que pretende fazer com o dinheiro. ",
  s4: "Quando você pretende resgatar esse dinheiro. você pode colocar em anos ou até mesmo meses.",
  s5: "Por fim, informe seu nível de conhecimento sobre investimentos.",
};

// === EDITE AQUI: texto falado quando o usuário clicar em "Sobre" ===
const TTS_TEXTO_SOBRE =
  "Esta plataforma foi desenvolvida por Eduardo Forte, Ele é aluno de Engenharia de Software na Universidade do Estado do Pará, e atua como desenvolvedor Full-Stack com foco em Engenharia de Dados e Soluções de Inteligência Artificial, logo ele tem experiência na construção de pipelines de dados e integração de sistemas com modelos de elieliemis, como GPT, Gemini e Claudi, a função desse projeto é simplificar a tomada de decisão financeira, unindo tecnologia e análise de dados, nesse projeto, as tecnologias utilizadas foram Python, Festi eipiai, Gemini 3 ponto 1 Flash Light, isquissiti lârni, SQl light, pandas, numpai, javaiscript, docker,Web Speech eipiai para a minha narração e  muitas outras tecnologias. Em se tratando de transparência de dados, É importante ressaltar que esta é uma ferramenta de estudo e simulação automatizada por Inteligência Artificial,ou seja, isso significa que todas as opções de investimentos são retiradas do site oficial do Tesouro Direto. Caso você tenha se interessado pelo projeto e queira falar com o eduardo, você pode acessar o perfil dele no LinkedIn apenas clicando no nome dele no fim da página.";

// === EDITE AQUI: encerramento falado após a resposta da IA ===
const TTS_ENCERRAMENTO_RESPOSTA_GEMINI =
  "Logo abaixo, você pode conferir um gráfico detalhado que projeta o rendimento e o acúmulo de juros da nossa principal recomendação. Para explorar mais detalhes ou realizar o aporte, clique no botão e acesse o site oficial do Tesouro Direto.";

let soundOn = false;
let ttsJaApresentou = false;
let ttsBoasVindasAgendada = false;
let ttsBoasVindasEmAndamento = false;
let ttsNarrarEtapaDepoisDaBoasVindas = false;
let ttsVozes = [];
let ttsVozSelecionada = null;
let ttsFalaAtual = null;
let ttsFilaAtual = [];
let ttsOpcoesAtual = null;
let ttsIniciouExecucaoAtual = false;
let ttsExecucaoAtual = 0;
let ttsBoasVindasTimer = null;
let narradorJaFoiAtivado = false;
let ttsUltimaRespostaGeminiMarkdown = "";
let ttsRespostaGeminiJaNarrada = false;

function normalizarTextoFala(texto) {
  return String(texto || "").replace(/\s+/g, " ").trim();
}

function selecionarVozTTS(vozes = []) {
  const candidatas = vozes.filter(voz => {
    const lang = String(voz.lang || "").toLowerCase();
    return lang === "pt-br" || lang.startsWith("pt");
  });

  const femininas = [
    "female", "feminina", "mulher", "luciana", "francisca", "maria",
    "helena", "camila", "vitoria", "vitória", "leticia", "letícia"
  ];
  const naturais = ["natural", "neural", "google", "microsoft", "premium"];

  function pontuar(voz) {
    const nome = String(voz.name || "").toLowerCase();
    const lang = String(voz.lang || "").toLowerCase();
    let pontos = 0;

    if (lang === "pt-br") pontos += 100;
    else if (lang.startsWith("pt")) pontos += 70;

    if (femininas.some(termo => nome.includes(termo))) pontos += 30;
    if (naturais.some(termo => nome.includes(termo))) pontos += 12;
    if (voz.localService) pontos += 4;

    return pontos;
  }

  return candidatas.sort((a, b) => pontuar(b) - pontuar(a))[0] || vozes[0] || null;
}

function carregarVozesTTS() {
  if (!TTS_SUPORTADO) return;
  ttsVozes = window.speechSynthesis.getVoices();
  ttsVozSelecionada = selecionarVozTTS(ttsVozes);
}

if (TTS_SUPORTADO) {
  carregarVozesTTS();
  if (typeof window.speechSynthesis.addEventListener === "function") {
    window.speechSynthesis.addEventListener("voiceschanged", carregarVozesTTS);
  } else {
    window.speechSynthesis.onvoiceschanged = carregarVozesTTS;
  }
}

function criarFala(texto) {
  const fala = new SpeechSynthesisUtterance(texto);
  fala.lang = "pt-BR";
  fala.rate = 1.01;
  fala.pitch = 1.04;
  fala.volume = 1;

  if (!ttsVozSelecionada) carregarVozesTTS();
  if (ttsVozSelecionada) fala.voice = ttsVozSelecionada;

  return fala;
}

function dividirTextoParaFala(texto) {
  const textoLimpo = normalizarTextoFala(texto);
  if (!textoLimpo) return [];

  const partes = textoLimpo.match(/[^.!?;:]+[.!?;:]?/g) || [textoLimpo];
  const blocos = [];

  partes.forEach(parte => {
    const trecho = normalizarTextoFala(parte);
    if (!trecho) return;

    if (trecho.length <= 260) {
      blocos.push(trecho);
      return;
    }

    let bloco = "";
    trecho.split(" ").forEach(palavra => {
      const candidato = bloco ? `${bloco} ${palavra}` : palavra;
      if (candidato.length > 1660 && bloco) {
        blocos.push(bloco);
        bloco = palavra;
      } else {
        bloco = candidato;
      }
    });

    if (bloco) blocos.push(bloco);
  });

  return blocos;
}

function limparEstadoFilaTTS() {
  ttsFalaAtual = null;
  ttsFilaAtual = [];
  ttsOpcoesAtual = null;
  ttsIniciouExecucaoAtual = false;
}

function cancelarFalaAtual() {
  if (!TTS_SUPORTADO) return;

  ttsExecucaoAtual += 1;
  limparEstadoFilaTTS();
  window.speechSynthesis.cancel();
}

function finalizarFilaTTS(execucaoId, tipo, evento) {
  if (execucaoId !== ttsExecucaoAtual) return;

  const opcoes = ttsOpcoesAtual || {};
  limparEstadoFilaTTS();

  if (tipo === "erro" && typeof opcoes.onError === "function") {
    opcoes.onError(evento);
    return;
  }

  if (typeof opcoes.onEnd === "function") opcoes.onEnd(evento);
}

function falarProximoBlocoTTS(execucaoId) {
  if (execucaoId !== ttsExecucaoAtual || !soundOn || !TTS_SUPORTADO) return;

  const texto = ttsFilaAtual.shift();
  if (!texto) {
    finalizarFilaTTS(execucaoId, "fim");
    return;
  }

  const fala = criarFala(texto);
  ttsFalaAtual = fala;

  fala.onstart = () => {
    if (execucaoId !== ttsExecucaoAtual) return;

    if (!ttsIniciouExecucaoAtual) {
      ttsIniciouExecucaoAtual = true;
      if (typeof ttsOpcoesAtual?.onStart === "function") ttsOpcoesAtual.onStart();
    }
  };

  fala.onend = (evento) => {
    if (execucaoId !== ttsExecucaoAtual) return;

    ttsFalaAtual = null;
    if (!ttsFilaAtual.length) {
      finalizarFilaTTS(execucaoId, "fim", evento);
      return;
    }

    setTimeout(() => falarProximoBlocoTTS(execucaoId), 90);
  };

  fala.onerror = (evento) => {
    if (execucaoId !== ttsExecucaoAtual) return;

    ttsFalaAtual = null;
    if (ttsFilaAtual.length) {
      setTimeout(() => falarProximoBlocoTTS(execucaoId), 90);
      return;
    }

    finalizarFilaTTS(execucaoId, "erro", evento);
  };

  window.speechSynthesis.resume();
  window.speechSynthesis.speak(fala);
}

function falarTexto(texto, opcoes = {}) {
  if (!soundOn || !TTS_SUPORTADO) return false;

  const fila = dividirTextoParaFala(texto);
  if (!fila.length) return false;

  cancelarFalaAtual();
  const execucaoId = ++ttsExecucaoAtual;
  ttsFilaAtual = fila;
  ttsOpcoesAtual = opcoes;
  ttsIniciouExecucaoAtual = false;

  setTimeout(() => falarProximoBlocoTTS(execucaoId), 0);
  return true;
}

function falarTextosEmSequencia(textos = []) {
  const texto = textos.map(normalizarTextoFala).filter(Boolean).join(" ");
  if (texto) falarTexto(texto);
}

function limparTextoParaVoz(textoBruto) {
  return String(textoBruto || "")
    .replace(/[📊⚠️📌🏆🎯💡]/gu, "")
    .replace(/\uFE0F/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[`*_#>]/g, "")
    .replace(/[•●▪▫]/g, "")
    .replace(/^\s*[-+]\s+/gm, "")
    .replace(/[—–]/g, ", ")
    .replace(/(\d+(?:[.,]\d+)?)\s*%/g, "$1 por cento")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .split("\n")
    .map(linha => linha.trim())
    .join("\n")
    .trim();
}

function fatiarTextoParaVoz(texto, limite = 420) {
  const textoLimpo = limparTextoParaVoz(texto);
  if (!textoLimpo) return [];

  const paragrafos = textoLimpo
    .split(/\n{2,}/)
    .map(paragrafo => normalizarTextoFala(paragrafo))
    .filter(Boolean);
  const pedacos = [];

  paragrafos.forEach(paragrafo => {
    const frases = paragrafo.match(/[^.!?;:]+[.!?;:]?/g) || [paragrafo];
    let bloco = "";

    frases.forEach(frase => {
      const trecho = normalizarTextoFala(frase);
      if (!trecho) return;

      const candidato = bloco ? `${bloco} ${trecho}` : trecho;
      if (candidato.length > limite && bloco) {
        pedacos.push(bloco);
        bloco = trecho;
      } else {
        bloco = candidato;
      }

      while (bloco.length > limite) {
        const corte = bloco.lastIndexOf(" ", limite);
        const indiceCorte = corte > 80 ? corte : limite;
        pedacos.push(bloco.slice(0, indiceCorte).trim());
        bloco = bloco.slice(indiceCorte).trim();
      }
    });

    if (bloco) pedacos.push(bloco);
  });

  return pedacos;
}

function falarTextoLongo(arrayDeTextos, opcoes = {}) {
  if (!soundOn || !TTS_SUPORTADO) return false;

  const fila = arrayDeTextos
    .map(trecho => normalizarTextoFala(trecho))
    .filter(Boolean);
  if (!fila.length) return false;

  cancelarFalaAtual();
  const execucaoId = ++ttsExecucaoAtual;
  ttsFilaAtual = fila;
  ttsOpcoesAtual = opcoes;
  ttsIniciouExecucaoAtual = false;

  setTimeout(() => falarProximoBlocoTTS(execucaoId), 0);
  return true;
}

function registrarRespostaGeminiParaNarracao(relatorioMarkdown) {
  ttsUltimaRespostaGeminiMarkdown = String(relatorioMarkdown || "");
  ttsRespostaGeminiJaNarrada = false;
}

function narrarRespostaGeminiSeAtivo(relatorioMarkdown = ttsUltimaRespostaGeminiMarkdown) {
  if (!soundOn || !narradorJaFoiAtivado || !TTS_SUPORTADO) return false;
  if (ttsRespostaGeminiJaNarrada) return false;

  const pedacos = fatiarTextoParaVoz(relatorioMarkdown);
  if (!pedacos.length) return false;

  pedacos.push(TTS_ENCERRAMENTO_RESPOSTA_GEMINI);
  return falarTextoLongo(pedacos, {
    onEnd: () => {
      ttsRespostaGeminiJaNarrada = true;
    },
    onError: () => {
      ttsRespostaGeminiJaNarrada = false;
    },
  });
}

function obterTextoNarracaoDaEtapa(target) {
  return normalizarTextoFala(TTS_NARRACOES_ETAPAS[target]);
}

function obterViewAtual() {
  return Object.entries(views).find(([, view]) => view.classList.contains("view--visible"))?.[0] || "";
}

function falarNarracaoDaEtapa(target, opcoes = {}) {
  if (!opcoes.ignorarBoasVindas && ttsBoasVindasEmAndamento) {
    ttsNarrarEtapaDepoisDaBoasVindas = true;
    return;
  }

  const texto = obterTextoNarracaoDaEtapa(target);
  if (texto) falarTexto(texto);
}

function falarNarracaoDaViewAtual() {
  const target = obterViewAtual();
  falarNarracaoDaEtapa(target);
}

function ativarNarrador() {
  soundOn = true;
  narradorJaFoiAtivado = true;

  if (typeof atualizarBotaoSom === "function") atualizarBotaoSom();
}

function falarTextoSobre() {
  if (!soundOn || !narradorJaFoiAtivado) return;

  cancelarBoasVindasAgendada();
  ttsBoasVindasEmAndamento = false;
  ttsNarrarEtapaDepoisDaBoasVindas = false;
  falarTexto(TTS_TEXTO_SOBRE);
}

function prepararTextoBoasVindasParaFala(texto) {
  return normalizarTextoFala(texto).replace(/^Olá!\s*/i, "Olá, ");
}

function finalizarFalaBoasVindas() {
  ttsBoasVindasAgendada = false;
  ttsBoasVindasEmAndamento = false;

  if (!soundOn || !ttsNarrarEtapaDepoisDaBoasVindas) return;

  ttsNarrarEtapaDepoisDaBoasVindas = false;
  const etapaAtual = obterViewAtual();

  if (cards[etapaAtual]) {
    setTimeout(() => falarNarracaoDaEtapa(etapaAtual, { ignorarBoasVindas: true }), 160);
  }
}

function cancelarBoasVindasAgendada() {
  if (ttsBoasVindasTimer) {
    clearTimeout(ttsBoasVindasTimer);
    ttsBoasVindasTimer = null;
  }

  ttsBoasVindasAgendada = false;
}

function limparEstadoBoasVindas() {
  ttsBoasVindasEmAndamento = false;
  ttsNarrarEtapaDepoisDaBoasVindas = false;
}

function pararNarracaoAtual() {
  cancelarFalaAtual();
  cancelarBoasVindasAgendada();
  limparEstadoBoasVindas();
}

function lerMensagemBoasVindas(atraso = 900, opcoes = {}) {
  const deveRepetir = opcoes.repetir === true;
  if (!soundOn || !TTS_SUPORTADO || ttsBoasVindasEmAndamento) return;
  if (ttsJaApresentou && !deveRepetir) return;

  if (opcoes.forcar) cancelarBoasVindasAgendada();
  if (ttsBoasVindasAgendada) return;

  ttsBoasVindasAgendada = true;

  ttsBoasVindasTimer = setTimeout(() => {
    ttsBoasVindasTimer = null;
    ttsBoasVindasAgendada = false;

    if (!soundOn || ttsBoasVindasEmAndamento) return;
    if (ttsJaApresentou && !deveRepetir) return;
    if (obterViewAtual() !== "landing") return;

    console.info("[TTS] Tentando boas-vindas:", TTS_MENSAGEM_BOAS_VINDAS);

    falarTexto(prepararTextoBoasVindasParaFala(TTS_MENSAGEM_BOAS_VINDAS), {
      onStart: () => {
        console.info("[TTS] Boas-vindas iniciada");
        ttsJaApresentou = true;
        ttsBoasVindasEmAndamento = true;
        removerFallbackBoasVindas();
      },
      onEnd: (evento) => {
        console.info("[TTS] Boas-vindas finalizada");
        finalizarFalaBoasVindas(evento);
      },
      onError: (evento) => {
        console.warn("[TTS] Falha na boas-vindas:", evento?.error || evento);
        finalizarFalaBoasVindas(evento);
      },
    });
  }, atraso);
}

const TTS_EVENTOS_FALLBACK_BOAS_VINDAS = ["pointerdown", "keydown"];

function removerFallbackBoasVindas() {
  TTS_EVENTOS_FALLBACK_BOAS_VINDAS.forEach(evento => {
    document.removeEventListener(evento, tentarFallbackBoasVindasPorInteracao, true);
  });
}

function tentarFallbackBoasVindasPorInteracao(evento) {
  if (!soundOn || !TTS_SUPORTADO || ttsJaApresentou) {
    removerFallbackBoasVindas();
    return;
  }

  const alvo = evento.target;
  const temClosest = alvo && typeof alvo.closest === "function";

  if (temClosest && alvo.closest("#btnStartAnalysis, #soundButton")) return;
  if (obterViewAtual() !== "landing") return;

  lerMensagemBoasVindas(40, { forcar: true });
}

function registrarFallbackBoasVindas() {
  if (!TTS_SUPORTADO || ttsJaApresentou) return;

  TTS_EVENTOS_FALLBACK_BOAS_VINDAS.forEach(evento => {
    document.addEventListener(evento, tentarFallbackBoasVindasPorInteracao, true);
  });
}


/* ─── VIEW NAVIGATION ───────────────────────────────────────────────────────── */
const views = {
  landing: document.getElementById("view-landing"),
  s1:      document.getElementById("view-step-1"),
  s2:      document.getElementById("view-step-2"),
  s3:      document.getElementById("view-step-3"),
  s4:      document.getElementById("view-step-4"),
  s5:      document.getElementById("view-step-5"),
  loading: document.getElementById("view-loading"),
  results: document.getElementById("view-results"),
  sobre:   document.getElementById("view-sobre"),
};
const cards = { s1: "card1", s2: "card2", s3: "card3", s4: "card4", s5: "card5" };

function showView(target, dir, options = {}) {
  const entering = views[target];
  const current  = Object.values(views).find(v => v.classList.contains("view--visible"));

  if (current) {
    current.classList.remove("view--visible");
    current.classList.add(dir === "back" ? "view--hidden-right" : "view--hidden-left");
  }

  entering.classList.remove("view--hidden-left", "view--hidden-right");
  entering.classList.add("view--visible");
  entering.scrollTop = 0;

  if (cards[target]) {
    const card = document.getElementById(cards[target]);
    card.classList.remove("entered");
    setTimeout(() => card.classList.add("entered"), 150);
  }

  if (cards[target] && !options.silenciarNarracao) {
    setTimeout(() => falarNarracaoDaEtapa(target), 360);
  }
}

function narrarBoasVindasSeAtivo() {
  if (soundOn && narradorJaFoiAtivado) {
    lerMensagemBoasVindas(0, { forcar: true, repetir: true });
  }
}

function voltarParaHomeComNarracao() {
  pararNarracaoAtual();
  showView("landing", "back");
  narrarBoasVindasSeAtivo();
}

document.getElementById("btnStartAnalysis").addEventListener("click", () => {
  pararNarracaoAtual();
  showView("s1");
});
document.getElementById("btnSobre").addEventListener("click", () => {
  showView("sobre");
  falarTextoSobre();
});

document.getElementById("btnBackSobre").addEventListener("click", voltarParaHomeComNarracao);
document.getElementById("btnBackStep1").addEventListener("click", voltarParaHomeComNarracao);
document.getElementById("btnBackStep2").addEventListener("click",     () => showView("s1", "back"));
document.getElementById("btnBackStep3").addEventListener("click",     () => showView("s2", "back"));
document.getElementById("btnBackStep4").addEventListener("click",     () => showView("s3", "back"));
document.getElementById("btnBackStep5").addEventListener("click",     () => showView("s4", "back"));

// O navegador exige uma interação explícita para liberar áudio com som.
// Por isso, a boas-vindas começa no botão fixo #soundButton, não no load da página.
function cancelarNarracaoAoSairDaPagina() {
  pararNarracaoAtual();
}

window.addEventListener("pagehide", cancelarNarracaoAoSairDaPagina);
window.addEventListener("beforeunload", cancelarNarracaoAoSairDaPagina);

/* ─── MONEY INPUT HELPER ────────────────────────────────────────────────────── */
function formatBRL(digits) {
  return digits ? parseInt(digits, 10).toLocaleString("pt-BR") : "";
}

function bindMoneyInput(inputId, chipsId, onChange) {
  const input   = document.getElementById(inputId);
  const chipsEl = document.getElementById(chipsId);
  let raw = "";

  function emitirMudanca() {
    if (typeof onChange === "function") onChange(raw);
  }

  input.addEventListener("input", () => {
    raw = input.value.replace(/\D/g, "");
    input.value = formatBRL(raw);
    chipsEl.querySelectorAll(".chip").forEach(c => c.classList.remove("selected"));
    emitirMudanca();
  });

  input.addEventListener("paste", e => {
    e.preventDefault();
    const pasted = (e.clipboardData || window.clipboardData).getData("text");
    raw = (raw + pasted).replace(/\D/g, "");
    input.value = formatBRL(raw);
    emitirMudanca();
  });

  chipsEl.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    chipsEl.querySelectorAll(".chip").forEach(c => c.classList.remove("selected"));
    chip.classList.add("selected");
    raw = chip.dataset.value;
    input.value = formatBRL(raw);
    emitirMudanca();
  });

  return { getRaw: () => raw };
}

/* Steps 1 & 2: pelo menos um dos dois valores precisa ser maior que zero. */
let step1;
let step2;
const btnStep2 = document.getElementById("btnStep2");
const TEXTO_BTN_CONTINUAR = "Continuar";
const TEXTO_BTN_CAPITAL_OBRIGATORIO = "Preencha essa pergunta ou a anterior";

function valorMonetarioPositivo(raw) {
  const valor = parseInt(raw, 10);
  return Number.isFinite(valor) && valor > 0;
}

function definirTextoBotaoStep2(texto) {
  if (!btnStep2) return;

  const svg = btnStep2.querySelector("svg");
  btnStep2.replaceChildren(document.createTextNode(texto));
  if (svg) btnStep2.appendChild(svg);
}

function atualizarEstadoCapitalParaJuros() {
  if (!step1 || !step2 || !btnStep2) return;

  const temCapital = valorMonetarioPositivo(step1.getRaw()) || valorMonetarioPositivo(step2.getRaw());

  if (temCapital) {
    btnStep2.disabled = false;
    definirTextoBotaoStep2(TEXTO_BTN_CONTINUAR);
  } else {
    btnStep2.disabled = true;
    definirTextoBotaoStep2(TEXTO_BTN_CAPITAL_OBRIGATORIO);
  }
}

step1 = bindMoneyInput("inputStep1", "chipsStep1", atualizarEstadoCapitalParaJuros);
step2 = bindMoneyInput("inputStep2", "chipsStep2", atualizarEstadoCapitalParaJuros);
atualizarEstadoCapitalParaJuros();

document.getElementById("btnStep1").addEventListener("click", () => {
  atualizarEstadoCapitalParaJuros();
  showView("s2");
});
document.getElementById("btnStep2").addEventListener("click", () => {
  atualizarEstadoCapitalParaJuros();
  if (!btnStep2.disabled) showView("s3");
});

/* ─── CHIP SELECTION (steps 3–5) ───────────────────────────────────────────── */
function bindChips(chipsId, btnId, onNext) {
  const chipsEl = document.getElementById(chipsId);
  const btn     = document.getElementById(btnId);
  let selected  = "";

  chipsEl.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    chipsEl.querySelectorAll(".chip").forEach(c => c.classList.remove("selected"));
    chip.classList.add("selected");
    selected = chip.dataset.value;
    btn.disabled = false;
  });

  btn.addEventListener("click", () => { if (!btn.disabled && onNext) onNext(selected); });

  return { getSelected: () => selected };
}

const step3 = bindChips("chipsStep3", "btnStep3", () => showView("s4"));

/* Passo 4: campo numérico livre + toggle de unidade (Meses / Anos).
   Captura precisa do horizonte exato — o gráfico vai EXATAMENTE até o prazo
   informado, sem cap. O toggle substitui o <select> nativo: dois botões pill
   que alternam .active e atualizam o <input type="hidden" id="unidade_tempo">. */
const step4 = (() => {
  const inp    = document.getElementById("tempo_investimento");
  const hidden = document.getElementById("unidade_tempo");
  const toggle = document.getElementById("unitToggle");
  const btn    = document.getElementById("btnStep4");

  function validar() {
    const v = parseInt(inp.value, 10);
    btn.disabled = !(Number.isFinite(v) && v >= 1);
  }
  inp.addEventListener("input", validar);

  // Delegação no contêiner — alterna .active e sincroniza o hidden input.
  toggle.addEventListener("click", (e) => {
    const opt = e.target.closest(".unit-toggle-btn");
    if (!opt) return;
    toggle.querySelectorAll(".unit-toggle-btn").forEach(b => {
      b.classList.remove("active");
      b.setAttribute("aria-selected", "false");
    });
    opt.classList.add("active");
    opt.setAttribute("aria-selected", "true");
    hidden.value = opt.dataset.unit;  // "meses" | "anos"
  });

  btn.addEventListener("click", () => {
    if (!btn.disabled) showView("s5");
  });

  return {
    getTempo:   () => parseInt(inp.value, 10) || 0,
    getUnidade: () => hidden.value,
  };
})();

const step5 = bindChips("chipsStep5", "btnStep5", conhecimento => {
  const dados = {
    valorInicial:       parseInt(step1.getRaw(), 10) || 0,
    aporteMensal:       parseInt(step2.getRaw(), 10) || 0,
    objetivo:           step3.getSelected(),
    tempo_investimento: step4.getTempo(),
    unidade_tempo:      step4.getUnidade(),
    conhecimento:       conhecimento,
  };
  submeterFormulario(dados);
});

document.getElementById("btnNovaAnalise").addEventListener("click", () => {
  if (_graficoProjecao) {
    _graficoProjecao.destroy();
    _graficoProjecao = null;
  }
  showView("landing", "back");
});

/* ─── LOADING ────────────────────────────────────────────────────────────────── */
const MSGS_LOADING = [
  "Consultando o Tesouro Direto...",
  "Classificando seu perfil com o Rende IA...",
  "Calculando retorno real e score de risco...",
  "Gerando relatório com o Rende IA...",
  "Preparando os gráficos...",
];
let _loadingIdx   = 0;
let _loadingTimer = null;

function iniciarLoading() {
  _loadingIdx = 0;
  document.getElementById("loadingMsg").textContent = MSGS_LOADING[0];
  clearInterval(_loadingTimer);
  _loadingTimer = setInterval(() => {
    _loadingIdx = (_loadingIdx + 1) % MSGS_LOADING.length;
    document.getElementById("loadingMsg").textContent = MSGS_LOADING[_loadingIdx];
  }, 2800);
}

/* ─── CHAMADA À API ──────────────────────────────────────────────────────────── */
// Trava de concorrência: impede que duplo clique / reenvio rápido dispare mais de
// um POST /api/analise (cada POST extra é uma chamada Gemini extra → 429). Enquanto
// houver uma análise em andamento, novos envios são ignorados e o botão fica disabled.
let _analiseEmAndamento = false;

async function submeterFormulario(dados) {
  if (_analiseEmAndamento) return;          // já existe uma análise em voo
  _analiseEmAndamento = true;
  const btn = document.getElementById("btnStep5");
  if (btn) btn.disabled = true;             // bloqueia o botão durante a requisição

  showView("loading");
  iniciarLoading();

  try {
    const resp = await fetch(`${API_URL}/api/analise`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    });

    clearInterval(_loadingTimer);

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      // Erros amigáveis (HTTP 503 ia_indisponivel | HTTP 429 limite_usuario):
      // mensagem amigável, SEM relatório determinístico e sem detalhe técnico.
      const e = new Error(
        err.mensagem || err.detail ||
        "Não foi possível gerar a análise com IA neste momento. Tente novamente em alguns instantes."
      );
      e.tipo = err.tipo;
      throw e;
    }

    const resultado = await resp.json();
    if (resultado.origem_relatorio) {
      console.info(`[RENDE-IA] origem do relatório: ${resultado.origem_relatorio}`);
    }
    mostrarResultados(resultado);

  } catch (err) {
    clearInterval(_loadingTimer);
    showView("s5", "back");
    // Não renderiza relatório determinístico; volta ao passo de confirmação e
    // mostra apenas a mensagem amigável (sem stack/erro técnico).
    const titulo = err.tipo === "limite_usuario" ? "Limite de análises" : "IA indisponível";
    mostrarToast({ titulo, mensagem: err.message });
  } finally {
    // Reabilita o reenvio apenas ao final (sucesso ou erro).
    _analiseEmAndamento = false;
    if (btn) btn.disabled = false;
  }
}

/* ─── EXIBIÇÃO DOS RESULTADOS ────────────────────────────────────────────────── */
const PERFIL_LABEL = {
  conservador: "Perfil Conservador",
  moderado:    "Perfil Moderado",
  arrojado:    "Perfil Arrojado",
};

function mostrarResultados(data) {
  const { perfil_ml, relatorio_markdown, dados_projecao, alerta_limite } = data;

  // ── Trava de usabilidade: descasamento de prazo (2 gradações) ─────────────
  // O backend classifica em:
  //   "tesouro_limit"      → horizonte > teto institucional do Tesouro Direto
  //                          (nenhum título do mundo cobre o prazo do cliente)
  //   "recomendacao_curta" → horizonte > vencimento do título escolhido para
  //                          o perfil específico (caso perfil-aware: filtro de
  //                          risco restringiu a opções mais curtas que o
  //                          horizonte, mesmo dentro do teto do Tesouro)
  //
  // Em ambos os casos o gráfico recebe uma linha vermelha tracejada exatamente
  // sobre o vencimento do título recomendado (ver renderGraficoProjecao).
  if (alerta_limite && alerta_limite.excedido) {
    let mensagem;

    if (alerta_limite.tipo === "tesouro_limit") {
      const anosMax = alerta_limite.prazo_max_anos
        ? `${alerta_limite.prazo_max_anos} anos`
        : "o limite atual";
      mensagem =
        "O prazo inserido excede o vencimento máximo disponível no Tesouro Direto " +
        `(${anosMax}). O gráfico e as recomendações foram ajustados para o título ` +
        "mais longo possível.";
    } else {
      // "recomendacao_curta" — fallback para qualquer tipo desconhecido também
      const vencAnos    = alerta_limite.vencimento_recomendado_anos;
      const aDescoberto = alerta_limite.anos_a_descoberto;
      const descTxt =
        aDescoberto >= 1
          ? `${aDescoberto} ${aDescoberto >= 2 ? "anos" : "ano"}`
          : `${Math.round(aDescoberto * 12)} meses`;
      mensagem =
        `O título mais alinhado ao seu perfil vence em ~${vencAnos} anos — ${descTxt} ` +
        "antes do horizonte que você informou. O gráfico marca o ponto exato onde " +
        "esse investimento se encerra.";
    }

    mostrarToast({ titulo: "Atenção", mensagem });
  }

  // Badge de perfil ML
  // NOTA UX: NUNCA expor `perfil_ml.confianca_pct` aqui. O score de confiança da
  // classificação é uma métrica interna do modelo — mostrar "47% de confiança"
  // para o investidor leigo soa como "o sistema não tem certeza" e mina o
  // engajamento. A métrica continua disponível no JSON da resposta para logs
  // de backend e debugging via DevTools.
  const label = PERFIL_LABEL[perfil_ml.perfil_classificado] || perfil_ml.perfil_classificado;
  document.getElementById("perfilTexto").textContent = `${label}  ·  Análise Concluída`;

  // Relatório em Markdown → HTML
  const container = document.getElementById("relatorioContent");
  if (window.marked) {
    container.innerHTML = marked.parse(relatorio_markdown || "");
  } else {
    container.textContent = relatorio_markdown || "";
  }

  registrarRespostaGeminiParaNarracao(relatorio_markdown || "");
  narrarRespostaGeminiSeAtivo();

  // Gráfico de projeção INTERATIVO (Chart.js) — único gráfico da tela
  // O nome do ativo vencedor vem do JSON estruturado da IA (posicao=1),
  // permitindo que a tela mostre dinamicamente qual título guiou a projeção.
  if (dados_projecao) {
    const tituloVencedor = document.getElementById("tituloVencedor");
    if (tituloVencedor) {
      tituloVencedor.textContent = dados_projecao.nome_ativo_vencedor
        ? ` · ${dados_projecao.nome_ativo_vencedor}`
        : "";
    }
    renderGraficoProjecao(dados_projecao, alerta_limite);
  }

  showView("results");
}

/* ─── TOAST MINIMALISTA ──────────────────────────────────────────────────────
   Renderiza uma notificação flutuante no #toastStack.
   - Slide-in da direita, PERMANENTE até o usuário clicar no "×"
   - Múltiplos toasts empilham com gap definido no CSS
   - Conteúdo passa por textContent (não innerHTML) — imune a XSS
   - Suporta prefers-reduced-motion (CSS já trata) */
function mostrarToast({ titulo = "", mensagem = "" } = {}) {
  const stack = document.getElementById("toastStack");
  if (!stack) return;

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.setAttribute("role", "alert");

  // Estrutura: ícone | corpo (título + msg) | botão fechar
  const icon = document.createElement("span");
  icon.className = "toast-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "!";

  const body = document.createElement("div");
  body.className = "toast-body";
  if (titulo) {
    const t = document.createElement("div");
    t.className = "toast-title";
    t.textContent = titulo;
    body.appendChild(t);
  }
  const m = document.createElement("div");
  m.className = "toast-msg";
  m.textContent = mensagem;
  body.appendChild(m);

  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Fechar notificação");
  close.textContent = "×";

  toast.append(icon, body, close);
  stack.appendChild(toast);

  // Dispara a transição CSS no próximo frame (precisa estar no DOM antes)
  requestAnimationFrame(() => toast.classList.add("show"));

  // Fechamento APENAS por interação do usuário (sem auto-dismiss).
  const remover = () => {
    toast.classList.remove("show");
    toast.addEventListener(
      "transitionend",
      () => toast.remove(),
      { once: true }
    );
    // Fallback se a transição for suprimida (prefers-reduced-motion)
    setTimeout(() => toast.isConnected && toast.remove(), 500);
  };
  close.addEventListener("click", remover);
}

/* ─── GRÁFICO INTERATIVO DE EVOLUÇÃO PATRIMONIAL (Chart.js) ─────────────────── */

const BRL_INTEIRO = new Intl.NumberFormat("pt-BR", {
  style: "currency", currency: "BRL", maximumFractionDigits: 0,
});
const BRL_EXATO = new Intl.NumberFormat("pt-BR", {
  style: "currency", currency: "BRL", minimumFractionDigits: 2,
});

// Referência ao chart vivo — usada para destruir antes de re-renderizar e evitar
// vazamento de listeners + canvas com tooltip duplicado.
let _graficoProjecao = null;

function formatarTitleTooltip(mes) {
  if (mes === 0) return "Início";
  const anos = Math.floor(mes / 12);
  const meses = mes % 12;
  if (anos === 0) return `${meses} ${meses === 1 ? "mês" : "meses"}`;
  if (meses === 0) return `${anos} ${anos === 1 ? "ano" : "anos"}`;
  return `${anos} ${anos === 1 ? "ano" : "anos"} e ${meses} ${meses === 1 ? "mês" : "meses"}`;
}

function formatarTickEixoX(mes) {
  if (mes === 0) return "Hoje";
  if (mes % 12 === 0) {
    const anos = mes / 12;
    return anos === 1 ? "1 ano" : `${anos} anos`;
  }
  // Tick caiu em mês não-redondo (curto prazo OU passo escolhido pelo autoSkip
  // do Chart.js quando o horizonte é muito longo). Formata como label compacto:
  //   < 1 ano  → "6m"
  //   misto    → "3a 6m"
  const anos = Math.floor(mes / 12);
  const meses = mes % 12;
  if (anos === 0) return `${meses}m`;
  return `${anos}a ${meses}m`;
}

function renderGraficoProjecao(dados, alertaLimite) {
  const canvas = document.getElementById("graficoProjecao");
  const wrap   = document.getElementById("wrapProjecao");
  if (!canvas || !window.Chart) return;

  // Sempre destruir o anterior — Chart.js não permite reusar canvas vivo
  if (_graficoProjecao) {
    _graficoProjecao.destroy();
    _graficoProjecao = null;
  }

  // Wrapper precisa estar visível ANTES do new Chart() para que o canvas tenha
  // dimensões reais (Chart.js mede o container no momento da inicialização)
  wrap.style.display = "flex";

  const meses = dados.meses_anos;
  const N = meses.length;

  // ── Animação progressiva (linhas crescem da esquerda para a direita) ────────
  // Padrão recomendado pela doc do Chart.js para "progressive line animation":
  // cada ponto entra com delay proporcional ao seu índice. O efeito visual é
  // o desenho da curva avançando ao longo do eixo X.
  const totalDuration = 1400;
  const delayPerPoint = N > 1 ? totalDuration / N : 0;
  const progressiveAnim = {
    x: {
      type: "number",
      easing: "linear",
      duration: delayPerPoint,
      from: NaN,
      delay(ctx) {
        if (ctx.type !== "data" || ctx.xStarted) return 0;
        ctx.xStarted = true;
        return ctx.index * delayPerPoint;
      },
    },
    y: {
      type: "number",
      easing: "linear",
      duration: delayPerPoint,
      from: (ctx) => {
        // Guard CRÍTICO contra o chartjs-plugin-annotation: o plugin envia
        // elementos do tipo "annotation" pelo mesmo pipeline de animação dos
        // datasets, mas SEM datasetIndex/index válidos. Sem este return early,
        // getDatasetMeta(undefined).data[-1].getProps(...) estoura
        // "Cannot read properties of undefined (reading 'getProps')" e derruba
        // o renderGraficoProjecao inteiro.
        if (ctx.type !== "data") return undefined;
        if (ctx.index === 0) return ctx.chart.scales.y.getPixelForValue(0);
        const meta = ctx.chart.getDatasetMeta(ctx.datasetIndex);
        const prev = meta && meta.data && meta.data[ctx.index - 1];
        if (!prev) return undefined;
        return prev.getProps(["y"], true).y;
      },
      delay(ctx) {
        if (ctx.type !== "data" || ctx.yStarted) return 0;
        ctx.yStarted = true;
        return ctx.index * delayPerPoint;
      },
    },
  };

  // ── Annotation: linha vertical tracejada no FIM REAL do investimento ──────
  // A linha marca o vencimento do título efetivamente recomendado (não o teto
  // institucional do Tesouro). Isso cobre AMBOS os cenários:
  //   tesouro_limit      → vencimento recomendado = teto do Tesouro (~58.5 anos)
  //   recomendacao_curta → vencimento recomendado = título perfil-aware mais curto
  // O label muda conforme o tipo: "Teto do Tesouro" vs "Vencimento Recomendado".
  const annotationsConfig = {};
  if (alertaLimite && alertaLimite.excedido && Number.isFinite(alertaLimite.linha_vertical_meses)) {
    const labelTexto =
      alertaLimite.tipo === "tesouro_limit"
        ? "Teto do Tesouro"
        : "Vencimento Previsto";

    annotationsConfig.vencimentoMaximoTesouro = {
      type: "line",
      scaleID: "x",
      value: alertaLimite.linha_vertical_meses,
      borderColor: "#d04545",
      borderWidth: 1.6,
      borderDash: [6, 5],
      label: {
        display: true,
        content: labelTexto,
        position: "start",            // topo da linha vertical
        backgroundColor: "rgba(208, 69, 69, 0.94)",
        color: "#ffffff",
        font: { family: "'DM Sans', system-ui, sans-serif", size: 10, weight: "600" },
        padding: { top: 4, bottom: 4, left: 8, right: 8 },
        borderRadius: 4,
        yAdjust: -2,
      },
    };
  }

  _graficoProjecao = new Chart(canvas, {
    type: "line",
    data: {
      labels: meses,
      datasets: [
        {
          // 1. MONTANTE TOTAL — destaque (cor da marca, sólida, com área sombreada)
          label: "Montante Total",
          data: dados.montante_total,
          borderColor: "#e08a00",
          backgroundColor: "rgba(224, 138, 0, 0.10)",
          borderWidth: 2.6,
          fill: true,
          tension: 0.28,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: "#e08a00",
          pointHoverBorderColor: "#ffffff",
          pointHoverBorderWidth: 2,
          order: 3,
        },
        {
          // 2. CAPITAL INVESTIDO — linha neutra tracejada
          label: "Capital Investido",
          data: dados.capital_investido,
          borderColor: "#555555",
          borderDash: [6, 6],
          borderWidth: 1.8,
          fill: false,
          tension: 0,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: "#555555",
          pointHoverBorderColor: "#ffffff",
          pointHoverBorderWidth: 2,
          order: 1,
        },
        {
          // 3. JUROS ACUMULADOS — verde positivo
          label: "Juros Acumulados",
          data: dados.juros_acumulados,
          borderColor: "#2e8b57",
          backgroundColor: "rgba(46, 139, 87, 0.08)",
          borderWidth: 2.2,
          fill: false,
          tension: 0.28,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: "#2e8b57",
          pointHoverBorderColor: "#ffffff",
          pointHoverBorderWidth: 2,
          order: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      // mode:"index" + intersect:false = tooltip vertical cruza as 3 linhas no
      // mesmo X. É exatamente o "balão único cruzando as três séries" pedido.
      interaction: { mode: "index", intersect: false, axis: "x" },
      hover:       { mode: "index", intersect: false },
      animations: progressiveAnim,
      animation:  { duration: totalDuration },
      plugins: {
        // Linha vertical tracejada no vencimento máximo do Tesouro — vazia quando
        // alertaLimite.excedido é falso (não polui o gráfico nos casos normais).
        annotation: { annotations: annotationsConfig },
        legend: {
          position: "top",
          align: "end",
          labels: {
            usePointStyle: true,
            boxWidth: 8,
            boxHeight: 8,
            padding: 14,
            color: "#0e0e0e",
            font: { family: "'DM Sans', system-ui, sans-serif", size: 12, weight: "500" },
          },
        },
        tooltip: {
          enabled: true,
          backgroundColor: "rgba(14, 14, 14, 0.94)",
          titleColor: "#ffffff",
          bodyColor: "#ffffff",
          titleFont: { family: "'DM Sans', system-ui, sans-serif", size: 12, weight: "600" },
          bodyFont:  { family: "'DM Sans', system-ui, sans-serif", size: 13 },
          padding: 12,
          cornerRadius: 8,
          displayColors: true,
          boxPadding: 6,
          callbacks: {
            title: (items) => {
              if (!items.length) return "";
              const mes = meses[items[0].dataIndex];
              return formatarTitleTooltip(mes);
            },
            label: (ctx) => ` ${ctx.dataset.label}: ${BRL_EXATO.format(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false, drawBorder: false },
          border: { color: "#e8e8e8" },
          ticks: {
            color: "#555555",
            font: { family: "'DM Sans', system-ui, sans-serif", size: 11 },
            // autoSkip + maxTicksLimit = Chart.js distribui no máximo 8 rótulos
            // ao longo do eixo X, independente do horizonte (12 ou 432 meses).
            // Elimina a sobreposição de textos em prazos longos (30+ anos).
            autoSkip: true,
            maxTicksLimit: 8,
            maxRotation: 0,
            callback: function (_, index) {
              return formatarTickEixoX(meses[index]);
            },
          },
        },
        y: {
          grid: { color: "#e8e8e8", drawBorder: false },
          border: { display: false },
          ticks: {
            color: "#555555",
            font: { family: "'DM Sans', system-ui, sans-serif", size: 11 },
            callback: (value) => BRL_INTEIRO.format(value),
          },
        },
      },
    },
  });
}

/* ─── SOUND BUTTON ───────────────────────────────────────────────────────────── */
const soundButton = document.getElementById("soundButton");
const soundIcon   = document.getElementById("soundIcon");
const soundLabel  = document.getElementById("soundLabel");

const SVG_ATTRS = 'fill="none" stroke="#111111" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
const iconOn  = `<path ${SVG_ATTRS} d="M11 5L6 9H3V15H6L11 19V5Z"></path><path ${SVG_ATTRS} d="M15 9C16.2 10 17 11.3 17 12.5C17 13.7 16.2 15 15 16"></path><path ${SVG_ATTRS} d="M17.5 6.5C19.5 8.2 21 10.2 21 12.5C21 14.8 19.5 16.8 17.5 18.5"></path>`;
const iconOff = `<path ${SVG_ATTRS} d="M11 5L6 9H3V15H6L11 19V5Z"></path><line ${SVG_ATTRS} x1="4" y1="4" x2="20" y2="20"></line>`;

function atualizarBotaoSom() {
  if (!soundButton || !soundIcon) return;

  const textoInativo = narradorJaFoiAtivado ? "Ativar som" : "Ativar narrador";
  const label = soundOn ? "Desativar som" : textoInativo;

  soundButton.classList.toggle("is-compact", narradorJaFoiAtivado);
  soundButton.setAttribute("aria-label", label);
  soundButton.setAttribute("title", soundOn ? "Som ativado" : textoInativo);
  soundIcon.innerHTML = soundOn ? iconOn : iconOff;
  if (soundLabel) soundLabel.textContent = textoInativo;
}

function narrarViewAtualAoAtivarSom() {
  const viewAtual = obterViewAtual();

  if (viewAtual === "landing") {
    lerMensagemBoasVindas(0, { forcar: true, repetir: true });
    return;
  }

  if (viewAtual === "sobre") {
    falarTextoSobre();
    return;
  }

  if (viewAtual === "results") {
    narrarRespostaGeminiSeAtivo();
    return;
  }

  falarNarracaoDaViewAtual();
}

if (soundButton && soundIcon) {
  atualizarBotaoSom();

  soundButton.addEventListener("click", () => {
    soundOn = !soundOn;
    if (soundOn) narradorJaFoiAtivado = true;

    if (!soundOn) {
      pararNarracaoAtual();
    }

    atualizarBotaoSom();

    if (soundOn) narrarViewAtualAoAtivarSom();
  });
}
