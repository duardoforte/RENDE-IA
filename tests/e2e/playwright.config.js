// @ts-check
const { defineConfig, devices } = require("@playwright/test");

/**
 * O backend FastAPI precisa estar rodando (serve o frontend estático).
 * Como o arquivo se chama principal.html (e não index.html), apontamos o
 * baseURL para ele diretamente. Os testes interceptam /api/analise — não
 * dependem do Gemini nem de chave de API.
 *
 * Suba o backend antes:  venv/bin/python app.py
 */
module.exports = defineConfig({
  testDir: ".",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
});
