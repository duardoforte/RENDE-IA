import sqlite3

def analisar_melhores_investimentos():
    print("🧠 Iniciando o Cérebro de Análise...\n")
    
    # 1. Conecta na "despensa" (nosso banco SQLite)
    try:
        conexao = sqlite3.connect("tesouro_direto.db")
        cursor = conexao.cursor()
    except Exception as e:
        print(f"Erro ao conectar no banco: {e}")
        return

    # --- PERGUNTA 1: Qual o título Prefixado com a maior taxa? ---
    cursor.execute('''
        SELECT nome, taxa_juros, vencimento, preco_unitario 
        FROM titulos 
        WHERE indexador = 'Prefixado' 
        ORDER BY taxa_juros DESC 
        LIMIT 1
    ''')
    melhor_prefixado = cursor.fetchone()

    # --- PERGUNTA 2: Qual o melhor título para se proteger da inflação (IPCA)? ---
    cursor.execute('''
        SELECT nome, taxa_juros, vencimento, preco_unitario 
        FROM titulos 
        WHERE indexador = 'IPCA' 
        ORDER BY taxa_juros DESC 
        LIMIT 1
    ''')
    melhor_ipca = cursor.fetchone()

    # --- PERGUNTA 3: Quais títulos vencem rápido (antes de 2030)? ---
    cursor.execute('''
        SELECT nome, indexador, taxa_juros, vencimento, preco_unitario 
        FROM titulos 
        WHERE CAST(SUBSTR(vencimento, 7, 4) AS INTEGER) < 2030
        ORDER BY taxa_juros DESC
    ''')
    titulos_curto_prazo = cursor.fetchall() 

    conexao.close()

    # --- EXIBINDO OS RESULTADOS DA IA ---
    print("🏆 --- RECOMENDAÇÕES DO DIA --- 🏆\n")
    
    if melhor_prefixado:
        print("🥇 MAIOR TAXA GARANTIDA (PREFIXADO):")
        print(f"   Título: {melhor_prefixado[0]}")
        print(f"   Taxa: {melhor_prefixado[1]}% ao ano | Preço: R$ {melhor_prefixado[3]}")
        print(f"   Vencimento: {melhor_prefixado[2]}\n")
        
    if melhor_ipca:
        print("🛡️ MELHOR PROTEÇÃO CONTRA INFLAÇÃO (IPCA+):")
        print(f"   Título: {melhor_ipca[0]}")
        print(f"   Taxa: IPCA + {melhor_ipca[1]}% ao ano | Preço: R$ {melhor_ipca[3]}")
        print(f"   Vencimento: {melhor_ipca[2]}\n")
        
    if titulos_curto_prazo:
        print("⏱️ TÍTULOS DE CURTO PRAZO (Vencem antes de 2030):")
        for titulo in titulos_curto_prazo:
            nome = titulo[0]
            indexador = titulo[1]
            taxa = titulo[2]
            vencimento = titulo[3]
            preco = titulo[4]
            
            print(f"   Título: {nome}")
            # Se for Prefixado, não repete a palavra no print
            if indexador == 'Prefixado':
                print(f"   Taxa: {taxa}% ao ano | Preço: R$ {preco}")
            else:
                print(f"   Taxa: {indexador} + {taxa}% ao ano | Preço: R$ {preco}")
            print(f"   Vencimento: {vencimento}\n")

if __name__ == "__main__":
    analisar_melhores_investimentos()