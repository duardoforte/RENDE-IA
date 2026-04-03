import pandas as pd

print("Consultando o Banco Central do Brasil...\n")

url_csv = "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"

try:
    # 1. Carrega os dados
    tabela = pd.read_csv(url_csv, sep=';', decimal=',')
    
    # 2. Converte a coluna de data para o formato correto e acha o último dia útil
    tabela['Data Base'] = pd.to_datetime(tabela['Data Base'], format='%d/%m/%Y')
    data_mais_recente = tabela['Data Base'].max()
    
    # 3. FILTRO 1: Pega só os dados do dia mais recente
    titulos_hoje = tabela[tabela['Data Base'] == data_mais_recente].copy()
    
    # 4. FILTRO 2: O Pulo do Gato! Pega só o que tem Taxa de Compra > 0
    # Isso elimina todos os títulos "fantasmas" que são apenas para resgate
    vitrine_oficial = titulos_hoje[titulos_hoje['Taxa Compra Manha'] > 0]
    
    print(f"--- VITRINE DE TÍTULOS DISPONÍVEIS PARA COMPRA ({data_mais_recente.strftime('%d/%m/%Y')}) ---\n")
    
    # 5. Imprime a lista limpa
    for index, linha in vitrine_oficial.iterrows():
        nome = linha['Tipo Titulo']
        vencimento = linha['Data Vencimento']
        taxa = linha['Taxa Compra Manha']
        preco = linha['PU Compra Manha']
        
        print(f"[{nome} - {vencimento}] Taxa: {taxa}% a.a. | Preço: R$ {preco}")

except Exception as e:
    print(f"Erro ao processar o CSV: {e}")