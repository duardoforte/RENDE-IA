import re
from minha_api import extrair_dados_brutos # Aqui o Organizador chama o Entregador!

def fatiar_texto(texto_valores):
    """Transforma a string bruta em dicionário tipado."""
    padrao = r"^(.*?)\s*([\d,]+)%\s*R\$\s*([\d.,]+)\s*R\$\s*([\d.,]+)\s*(\d{2}/\d{2}/\d{4})$"
    resultado = re.search(padrao, texto_valores.strip())
    
    if resultado:
        def limpar_numero(texto):
            return float(texto.replace(".", "").replace(",", "."))
        
        indexador = resultado.group(1).replace("+", "").strip()
        if indexador == "":
            indexador = "Prefixado"
            
        return {
            "indexador": indexador,
            "taxa_juros": limpar_numero(resultado.group(2)),
            "investimento_minimo": limpar_numero(resultado.group(3)),
            "preco_unitario": limpar_numero(resultado.group(4)),
            "vencimento": resultado.group(5)
        }
    return None

def processar_titulos():
    print("Chamando o robô (minha_api) para pegar os dados do site...\n")
    linhas_uteis = extrair_dados_brutos()
    
    if not linhas_uteis:
        print("Nenhum dado recebido.")
        return []

    lista_estruturada = []
    i = 0
    
    print("\n--- PROCESSANDO E ESTRUTURANDO OS DADOS ---")
    while i < len(linhas_uteis) - 1:
        linha_atual = linhas_uteis[i]
        
        if linha_atual.startswith("Tesouro"):
            nome_titulo = linha_atual
            
            # Tratamento para juros semestrais
            if i + 1 < len(linhas_uteis) and linhas_uteis[i+1] == "Juros semestrais":
                nome_titulo = f"{nome_titulo} (Juros semestrais)"
                dados_titulo = linhas_uteis[i+2]
                i += 3
            else:
                dados_titulo = linhas_uteis[i+1]
                i += 2
                
            dados_limpos = fatiar_texto(dados_titulo)
            
            if dados_limpos:
                dados_limpos["nome"] = nome_titulo
                lista_estruturada.append(dados_limpos)
                
                # Imprimindo na tela para você ver o resultado perfeito!
                print(f"\n📌 Título: {nome_titulo}")
                print(f"   Rentabilidade: {dados_limpos['indexador']} + {dados_limpos['taxa_juros']}% | Preço: R${dados_limpos['preco_unitario']} | Vence em: {dados_limpos['vencimento']}")
        else:
            i += 1
            
    return lista_estruturada

if __name__ == "__main__":
    dados_finais = processar_titulos()
    print(f"\n✅ Sucesso! Total de {len(dados_finais)} títulos prontos para a IA ou Banco de Dados.")