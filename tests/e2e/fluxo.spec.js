// @ts-check
const { test, expect } = require("@playwright/test");
const { respostaOk, respostaAlerta, respostaFallback } = require("./fixtures");

const PAGINA = "/principal.html"; // root '/' hoje retorna 404 (ver relatório de QA)

// Preenche os 5 passos do formulário e dispara a análise.
async function preencherFluxo(page) {
  await page.click("#btnStartAnalysis");
  await page.fill("#inputStep1", "10000");
  await page.click("#btnStep1");
  await page.fill("#inputStep2", "300");
  await page.click("#btnStep2");
  await page.click('#chipsStep3 .chip[data-value="reserva"]');
  await page.click("#btnStep3");
  await page.fill("#tempo_investimento", "8");
  await page.click('#unitToggle .unit-toggle-btn[data-unit="anos"]');
  await page.click("#btnStep4");
  await page.click('#chipsStep5 .chip[data-value="iniciante"]');
  await page.click("#btnStep5");
}

test.describe("RENDE-IA fluxo end-to-end (backend mockado)", () => {
  let consoleErrors;

  test.beforeEach(async ({ page }) => {
    consoleErrors = [];
    page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
  });

  test("landing carrega e mostra CTA", async ({ page }) => {
    await page.goto(PAGINA);
    await expect(page.locator("#btnStartAnalysis")).toBeVisible();
    await expect(page.locator(".logo").first()).toContainText(/Rende/i);
  });

  test("fluxo completo → relatório + gráfico, sem alerta", async ({ page }) => {
    await page.route("**/api/analise", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(respostaOk) })
    );
    await page.goto(PAGINA);
    await preencherFluxo(page);

    await expect(page.locator("#view-results")).toHaveClass(/view--visible/);
    await expect(page.locator("#relatorioContent")).toContainText("RANKING DE OPORTUNIDADES");
    await expect(page.locator("#relatorioContent")).toContainText("Tesouro Prefixado 2029");
    await expect(page.locator("#perfilTexto")).toContainText("Perfil Conservador");
    // gráfico Chart.js desenhou no canvas
    await expect(page.locator("#graficoProjecao")).toBeVisible();
    // título vencedor exibido
    await expect(page.locator("#tituloVencedor")).toContainText("Tesouro Prefixado 2029");
    // NÃO deve vazar confiança do modelo na tela
    await expect(page.locator("#relatorioContent")).not.toContainText(/confian|90\.3/i);
    expect(consoleErrors, consoleErrors.join("\n")).toHaveLength(0);
  });

  test("alerta de limite exibe toast e permite fechar", async ({ page }) => {
    await page.route("**/api/analise", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(respostaAlerta) })
    );
    await page.goto(PAGINA);
    await preencherFluxo(page);

    const toast = page.locator("#toastStack .toast");
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(/vencimento máximo|Tesouro Direto/i);
    await toast.locator(".toast-close").click();
    await expect(toast).toHaveCount(0);
  });

  test("fallback da IA (429/quota) renderiza TODAS as seções, sem erro técnico", async ({ page }) => {
    await page.route("**/api/analise", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(respostaFallback) })
    );
    await page.goto(PAGINA);
    await preencherFluxo(page);

    const relatorio = page.locator("#relatorioContent");
    await expect(page.locator("#view-results")).toHaveClass(/view--visible/);
    // As 5 seções aparecem mesmo sem a IA
    for (const secao of ["ANÁLISE MACROECONÔMICA", "RISCOS", "ESTRATÉGIA", "RANKING DE OPORTUNIDADES", "GLOSSÁRIO"]) {
      await expect(relatorio).toContainText(secao);
    }
    // Mensagem amigável presente; erro técnico do Gemini AUSENTE
    await expect(relatorio).toContainText(/temporariamente indisponível/i);
    await expect(relatorio).not.toContainText(/429|quota|RESOURCE_EXHAUSTED|googleapis/i);
    // Gráfico continua funcionando
    await expect(page.locator("#graficoProjecao")).toBeVisible();
    expect(consoleErrors, consoleErrors.join("\n")).toHaveLength(0);
  });

  test("erro de backend não quebra o app (volta ao passo 5)", async ({ page }) => {
    await page.route("**/api/analise", (route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Banco vazio" }) })
    );
    page.on("dialog", (d) => d.accept()); // o app usa alert()
    await page.goto(PAGINA);
    await preencherFluxo(page);
    await expect(page.locator("#view-step-5")).toHaveClass(/view--visible/);
  });
});
