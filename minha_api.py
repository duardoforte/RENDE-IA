from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

def extrair_dados_brutos():
    """
    Função que abre o navegador furtivo, passa pelo Cloudflare, 
    lê a tabela do Tesouro e devolve uma lista com as linhas úteis.
    """
    print("Iniciando o navegador no modo furtivo (Anti-Ban)...")

    opcoes = webdriver.ChromeOptions()

    # 1. REMOVE A MARCA DE ROBÔ DO CHROME
    opcoes.add_argument("--disable-blink-features=AutomationControlled")
    opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])
    opcoes.add_experimental_option('useAutomationExtension', False)

    # 2. SEU DISFARCE (User-Agent)
    opcoes.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    servico = Service(ChromeDriverManager().install())
    navegador = webdriver.Chrome(service=servico, options=opcoes)

    # 3. HACK DE JAVASCRIPT
    navegador.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    try:
        url = "https://www.tesourodireto.com.br/produtos/dados-sobre-titulos/rendimento-dos-titulos"
        print("Acessando a página e aguardando o Cloudflare...")
        navegador.get(url)
        
        # Aguarda o contêiner aparecer
        WebDriverWait(navegador, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "rentabilidade-container"))
        )
        time.sleep(3)
        
        print("--- DADOS EXTRAÍDOS DA TELA ---")
        
        # Extrai o texto puro
        container = navegador.find_element(By.CLASS_NAME, "rentabilidade-container")
        texto_bruto = container.text
        
        # Quebra em linhas
        linhas = texto_bruto.split('\n')
        
        # Remove o lixo (agora incluindo "Juros semestrais" para limpar a lista)
        palavras_ignoradas = ["Simular", "Investir", "Resgatar"]
        
        linhas_uteis = [linha.strip() for linha in linhas if linha.strip() not in palavras_ignoradas and linha.strip() != ""]
        
        # A MÁGICA ESTÁ AQUI: O robô DEVOLVE a lista para quem chamou ele!
        return linhas_uteis

    except Exception as e:
        print(f"\nOcorreu um erro na extração: {e}")
        # Se der erro, devolve uma lista vazia
        return []

    finally:
        navegador.quit()
        print("Navegador fechado com segurança.\n")

# Esse bloquinho final serve apenas para você testar o arquivo sozinho, se quiser.
# Se outro arquivo importar este, esse teste não vai rodar sozinho.
if __name__ == "__main__":
    dados_teste = extrair_dados_brutos()
    print(f"O robô conseguiu capturar {len(dados_teste)} linhas úteis.")