import sqlite3
from google import genai # <--- AQUI MUDOU: Biblioteca Nova!

# 1. Configurando a chave de acesso da IA com a nova biblioteca
CHAVE_API = "AIzaSyAjyXsn1XF7uOjd_PYEtIvj2TBmehSLgnM" 
client = genai.Client(api_key=CHAVE_API) # <--- AQUI MUDOU: Novo formato de conexão

def coletar_dados_para_ia():
    """Lê o banco de dados e monta um resumo em texto para mandar para a IA."""
    try:
        conexao = sqlite3.connect("tesouro_direto.db")
        cursor = conexao.cursor()
        
        # Pega todos os títulos salvos
        cursor.execute("SELECT nome, indexador, taxa_juros, preco_unitario, vencimento FROM titulos")
        todos_titulos = cursor.fetchall()
        conexao.close()
        
        if not todos_titulos:
            return None
            
        # Transforma os dados do banco em um texto simples para a IA ler
        resumo_dados = "DADOS DO TESOURO DIRETO DE HOJE:\n"
        for t in todos_titulos:
            resumo_dados += f"- {t[0]}: Indexador {t[1]}, Taxa {t[2]}%, Preço R${t[3]}, Vence em {t[4]}\n"
            
        return resumo_dados
        
    except Exception as e:
        print(f"Erro ao ler o banco: {e}")
        return None

def gerar_relatorio_financeiro(perfil_investidor=None):
    print("🤖 Consultor IA acordando e lendo seus dados do banco...")
    
    dados_mercado = coletar_dados_para_ia()
    
    if not dados_mercado:
        print("Nenhum dado encontrado. Tem certeza que o banco_dados.py rodou hoje?")
        return

    # Perfil padrão caso não seja informado
    if not perfil_investidor:
        perfil_investidor = {
            "valor": 10000,
            "prazo": "longo prazo (acima de 5 anos)",
            "objetivo": "aposentadoria",
            "tolerancia_risco": "conservador"
        }
    valor_br = f"{perfil_investidor['valor']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    prompt = f"""
    Você é um consultor financeiro sênior com 20 anos de experiência no mercado brasileiro,
    especialista em renda fixa, Tesouro Direto, política monetária do BACEN e análise de cenário macroeconômico.

    Você está atendendo um cliente com o seguinte perfil:
    - Valor disponível para investir: R$ {valor_br}
    - Prazo de investimento: {perfil_investidor['prazo']}
    - Objetivo financeiro: {perfil_investidor['objetivo']}
    - Tolerância a risco: {perfil_investidor['tolerancia_risco']}

    Com base EXCLUSIVAMENTE nos dados abaixo (não invente taxas ou títulos):
    {dados_mercado}

    Escreva um relatório financeiro completo e estruturado em Markdown contendo:

    ## 1. 📊 ANÁLISE MACROECONÔMICA
       - Interprete o nível das taxas atuais (estão altas ou baixas historicamente?)
       - O que a curva de juros sugere sobre as expectativas do mercado?
       - Como o cenário atual afeta o investidor {perfil_investidor['tolerancia_risco']}?

    ## 2. 🏆 RANKING DE MELHORES OPORTUNIDADES
       - Liste os 3 melhores títulos para o perfil deste cliente
       - Para cada um: explique por que é indicado e qual o risco.
       - Títulos Prefixados: simule o retorno final aproximado para os R$ {valor_br}.
       - Títulos IPCA+/Selic: projete um cenário realista, mas alerte explicitamente que o valor final dependerá da flutuação dos indicadores até o vencimento.

    ## 3. ⚠️ RISCOS E PONTOS DE ATENÇÃO
       - Quais títulos EVITAR para este perfil e por quê?
       - Risco de marcação a mercado: explique de forma simples e direta.
       - O que acontece se o cliente precisar resgatar antes do vencimento?

    ## 4. 📌 ESTRATÉGIA RECOMENDADA
       - Monte uma estratégia de alocação usando os títulos disponíveis
       - Exemplo: "40% em X, 40% em Y, 20% em Z" com justificativa matemática e lógica.
       - Considere diversificação por indexador e prazo.

    ## 5. 💡 GLOSSÁRIO RÁPIDO
       - Explique em 1 linha: Prefixado, IPCA+, Selic, marcação a mercado.

    Use linguagem profissional mas acessível. Formate bem o texto com negritos em pontos-chave. Não use frases genéricas de coaching financeiro.
    """


    print("🧠 Analisando o mercado e escrevendo o relatório...\n")
    
    try:
        resposta = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        print("==================================================")
        print("        📊 RELATÓRIO FINANCEIRO DA IA 📊        ")
        print("==================================================\n")
        print(resposta.text)
        print("\n==================================================")
        
    except Exception as e:
        print(f"Erro de comunicação com a IA: {e}")


if __name__ == "__main__":
    # Você pode customizar o perfil aqui!
    meu_perfil = {
        "valor": 10000,
        "prazo": "longo prazo (acima de 5 anos)",
        "objetivo": "aposentadoria",
        "tolerancia_risco": "conservador"
    }
    gerar_relatorio_financeiro(perfil_investidor=meu_perfil)