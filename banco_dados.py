import sqlite3
# O Banco de dados chama o Chef (processador), que por sua vez chama o Entregador (minha_api)
from processador import processar_titulos

def salvar_no_banco(dados):
    """
    Cria o banco de dados e salva a lista de dicionários em uma tabela SQL.
    """
    # 1. Conecta (ou cria se não existir) o arquivo do banco de dados
    conexao = sqlite3.connect("tesouro_direto.db")
    cursor = conexao.cursor()

    # 2. Cria a prateleira (tabela) com as tipagens corretas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS titulos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            indexador TEXT,
            taxa_juros REAL,
            investimento_minimo REAL,
            preco_unitario REAL,
            vencimento TEXT,
            data_extracao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 3. Limpa os dados antigos da tabela (opcional, para termos sempre a vitrine do dia atualizada)
    cursor.execute('DELETE FROM titulos')

    # 4. Guarda item por item na prateleira
    for titulo in dados:
        cursor.execute('''
            INSERT INTO titulos (nome, indexador, taxa_juros, investimento_minimo, preco_unitario, vencimento)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            titulo['nome'], 
            titulo['indexador'], 
            titulo['taxa_juros'], 
            titulo['investimento_minimo'], 
            titulo['preco_unitario'], 
            titulo['vencimento']
        ))

    # 5. Salva de verdade (commit) e tranca a porta
    conexao.commit()
    conexao.close()
    
    print(f"\n💾 SUCESSO! {len(dados)} títulos foram salvos no arquivo 'tesouro_direto.db'.")
    print("Sua IA já pode acessar este banco de dados e fazer análises milionárias!")

# Se você rodar este arquivo diretamente, ele aciona a esteira inteira!
if __name__ == "__main__":
    print("--- INICIANDO ESTEIRA COMPLETA DE DADOS ---")
    dados_limpos = processar_titulos()
    
    if dados_limpos:
        salvar_no_banco(dados_limpos)