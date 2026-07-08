import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# Screenshot resolvido para o diretório do script (independente do CWD do chamador)
_SCREENSHOT_PATH      = Path(__file__).parent / "erro_extracao.png"
_TIMEOUT_CLOUDFLARE_S = 30   # CF + render dinâmico podem demorar mais que selenium puro
_URL_TESOURO          = "https://www.tesourodireto.com.br/produtos/dados-sobre-titulos/rendimento-dos-titulos"


def _detectar_chrome_major() -> int | None:
    """
    Descobre a major version do Chrome instalado localmente.

    Necessário porque o undetected-chromedriver baixa por padrão o ChromeDriver
    mais recente, que pode estar à frente do binário do Chrome local e causar
    'SessionNotCreatedException: This version of ChromeDriver only supports
    Chrome version X'. Passando o resultado como version_main ao uc.Chrome(),
    forçamos o download do driver compatível com o Chrome do usuário.

    Retorna None se nenhum binário Chrome for encontrado — nesse caso deixamos
    o uc tentar a auto-detecção dele mesmo.
    """
    candidatos = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
    for binario in candidatos:
        caminho = shutil.which(binario)
        if not caminho:
            continue
        try:
            saida = subprocess.check_output([caminho, "--version"], stderr=subprocess.STDOUT, timeout=5)
            # Ex.: 'Google Chrome 140.0.7339.207' → captura 140
            match = re.search(r"\b(\d+)\.\d+\.\d+\.\d+", saida.decode("utf-8", errors="ignore"))
            if match:
                return int(match.group(1))
        except (subprocess.SubprocessError, OSError):
            continue
    return None


def _criar_navegador_furtivo() -> "tuple[uc.Chrome, object | None]":
    """
    Inicializa undetected-chromedriver com perfil reforçado contra o fingerprint
    da Cloudflare. Saliências:
      - viewport de desktop real (1366x768) — telas exóticas levantam suspeita
      - User-Agent desktop atualizado (a uc tenta sincronizar, mas reforçamos)
      - locale pt-BR (compatível com o público do Tesouro)
      - flags obrigatórias de Docker (--no-sandbox, --disable-dev-shm-usage)
      - tela virtual efêmera via pyvirtualdisplay (headful, contra a Cloudflare)
      - version_main detectada automaticamente para casar com o Chrome local
        (evita SessionNotCreatedException por mismatch de versão do driver)

    Retorna a tupla (navegador, display). O `display` (objeto pyvirtualdisplay ou
    None em modo headless) DEVE ser encerrado pelo chamador no finally, garantindo
    a remoção do lock da tela virtual a cada execução.
    """
    opcoes = uc.ChromeOptions()
    opcoes.add_argument("--window-size=1366,768")
    opcoes.add_argument("--lang=pt-BR")
    opcoes.add_argument("--disable-blink-features=AutomationControlled")
    opcoes.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )

    # ── Flags OBRIGATÓRIAS em container Docker (Linux, usuário root, sem GUI) ─────
    # --no-sandbox: o Chromium RECUSA iniciar como root sem esta flag e morre no
    #   startup. É a causa do "SessionNotCreatedException: chrome not reachable" —
    #   o driver sobe, manda o browser iniciar, mas o processo do Chromium sai na
    #   hora e ninguém escuta na porta de debug.
    # --disable-dev-shm-usage: usa /tmp em vez de /dev/shm para as páginas do
    #   renderer, evitando "tab crashed" quando o /dev/shm é pequeno. Mantemos por
    #   segurança mesmo com shm_size=1gb no compose.
    # --disable-gpu: sem GPU no servidor; evita ruído/erros do pipeline gráfico.
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-gpu")
    # Sem GPU no servidor, evita o Chromium tentar (e falhar) a inicialização de
    # EGL/ANGLE e cair no rasterizador de software com erro.
    opcoes.add_argument("--disable-software-rasterizer")

    chrome_major = _detectar_chrome_major()
    if chrome_major:
        print(f"   Chrome local detectado: versão {chrome_major} (alinhando ChromeDriver)")
    else:
        print("   Chrome local não detectado — uc fará auto-detecção")

    # ── Tela virtual EFÊMERA via pyvirtualdisplay ───────────────────────────────
    # Em vez de depender de um `Xvfb :99` global (que deixa /tmp/.X99-lock zumbi e
    # provoca "Server is already active for display 99"), o próprio Python abre uma
    # tela virtual com número LIVRE a cada execução. O chamador (extrair_dados_brutos)
    # a encerra no finally com display.stop(), removendo o lock automaticamente —
    # em caso de sucesso OU de falha.
    #
    # Headful sob essa tela é INTENCIONAL: o desafio da Cloudflare reprova navegador
    # headless mesmo com undetected-chromedriver. Só usamos headless=new como ÚLTIMO
    # recurso, via RENDE_IA_SCRAPER_HEADLESS=true (aí a tela virtual é dispensada).
    headless = str(os.getenv("RENDE_IA_SCRAPER_HEADLESS", "false")).strip().lower() in {
        "1", "true", "yes", "sim", "on",
    }

    display = None
    if headless:
        opcoes.add_argument("--headless=new")
        print("   Modo headless=new ativo (RENDE_IA_SCRAPER_HEADLESS=true) — atenção ao risco de bloqueio da Cloudflare")
    else:
        # Abre a tela ANTES do uc.Chrome: pyvirtualdisplay define os.environ['DISPLAY']
        # para o número recém-alocado, que o Chromium herda ao subir. Import local
        # para não exigir a lib quando rodando em modo headless puro.
        from pyvirtualdisplay import Display
        display = Display(visible=False, size=(1366, 768))
        display.start()
        print(f"   Tela virtual efêmera iniciada via pyvirtualdisplay (DISPLAY={os.environ.get('DISPLAY')})")

    # ── Binários do sistema (apt) em vez de download do uc ───────────────────────
    # Usa o Chromium + chromedriver instalados pelo Dockerfile, que o Debian mantém
    # em versões CASADAS. Passá-los explicitamente evita o undetected-chromedriver
    # baixar da internet um chromedriver "patched" que não bate com o build do
    # Chromium — descasamento que aparece como "chrome not reachable" mesmo com a
    # tela virtual e o --no-sandbox corretos. `version_main` só é usado como último
    # recurso (quando o chromedriver do sistema não é encontrado).
    chromium_bin = shutil.which("chromium") or shutil.which("chromium-browser")
    chromedriver_bin = shutil.which("chromedriver")
    print(f"   Binários do sistema → chromium={chromium_bin} | chromedriver={chromedriver_bin}")

    # use_subprocess=True isola o driver em processo separado (limpeza mais segura
    # no Linux quando o script crasha entre as fases de CF e parsing).
    try:
        navegador = uc.Chrome(
            options=opcoes,
            headless=headless,
            use_subprocess=True,
            browser_executable_path=chromium_bin,
            driver_executable_path=chromedriver_bin,
            # Só força version_main se NÃO houver chromedriver do sistema (aí o uc
            # baixa o dele e precisa saber a major para casar com o Chromium).
            version_main=None if chromedriver_bin else chrome_major,
        )
    except Exception:
        # Navegador falhou ao subir: encerra a tela aqui para não vazar um Xvfb
        # órfão (o finally do chamador só cobre o caso em que o navegador nasceu).
        if display is not None:
            try:
                display.stop()
            except Exception:
                pass
        raise

    # Devolve a tela junto: o chamador a mantém viva enquanto usa o navegador e a
    # encerra no finally, garantindo a limpeza do lock mesmo em caso de erro.
    return navegador, display


def extrair_dados_brutos():
    """
    Abre o navegador furtivo, atravessa o Cloudflare, lê a tabela de
    rentabilidade do Tesouro Direto e devolve as linhas úteis em uma lista.

    Em caso de falha, salva 'erro_extracao.png' ao lado do script para diagnóstico
    visual — é o que distingue CAPTCHA da Cloudflare de mudança de DOM no site.
    """
    print("Iniciando o navegador no modo furtivo (undetected-chromedriver)...")
    navegador, display = _criar_navegador_furtivo()

    try:
        print(f"Acessando a página e aguardando o Cloudflare (timeout {_TIMEOUT_CLOUDFLARE_S}s)...")
        navegador.get(_URL_TESOURO)

        # Aguarda o contêiner principal — se a CF estiver bloqueando, este wait estoura
        WebDriverWait(navegador, _TIMEOUT_CLOUDFLARE_S).until(
            EC.presence_of_element_located((By.CLASS_NAME, "rentabilidade-container"))
        )
        # Respiro extra para a tabela hidratar (Angular/Vue terminam o render assíncrono)
        time.sleep(3)

        print("--- DADOS EXTRAÍDOS DA TELA ---")
        container = navegador.find_element(By.CLASS_NAME, "rentabilidade-container")
        texto_bruto = container.text

        linhas = texto_bruto.split("\n")
        palavras_ignoradas = {"Simular", "Investir", "Resgatar"}
        linhas_uteis = [
            linha.strip()
            for linha in linhas
            if linha.strip() and linha.strip() not in palavras_ignoradas
        ]
        return linhas_uteis

    except Exception as e:
        # ── DEBUG VISUAL — passo INEGOCIÁVEL antes do quit() ───────────────────
        # Imprime o erro real (tipo + mensagem) para sair da névoa do Stacktrace
        print(f"\n❌ Erro Real: {type(e).__name__} - {e}")

        # Tenta salvar a tela atual para revelar a natureza do bloqueio.
        # O save_screenshot pode falhar se a sessão já estiver morta (driver crash);
        # protegemos com try interno para não mascarar o erro original.
        try:
            navegador.save_screenshot(str(_SCREENSHOT_PATH))
            print(f"📸 Screenshot salvo em: {_SCREENSHOT_PATH}")
            print("   → Abra o PNG:")
            print("     • CAPTCHA visível       → Cloudflare bloqueou (reforce stealth ou use proxy residencial).")
            print("     • Página carregada OK   → o seletor '.rentabilidade-container' mudou (inspecione o DOM novo).")
            print("     • Tela em branco/erro   → falha de rede ou o site está fora do ar.")
        except Exception as ss_err:
            print(f"   (não foi possível salvar o screenshot: {type(ss_err).__name__} - {ss_err})")

        return []

    finally:
        # quit() pode lançar se o subprocesso já caiu — não deixar vazar erro de cleanup
        try:
            navegador.quit()
        except Exception:
            pass
        # Encerra a tela virtual e remove o lock (/tmp/.X*-lock) SEMPRE — é isto que
        # evita os arquivos zumbis e o "Server is already active for display".
        if display is not None:
            try:
                display.stop()
                print("Tela virtual encerrada e lock liberado.")
            except Exception as disp_err:
                print(f"   (falha ao encerrar a tela virtual: {type(disp_err).__name__} - {disp_err})")
        print("Navegador fechado com segurança.\n")


# Bloco de teste manual: rode `python minha_api.py` para validar o scraping isoladamente.
if __name__ == "__main__":
    dados_teste = extrair_dados_brutos()
    print(f"O robô conseguiu capturar {len(dados_teste)} linhas úteis.")
