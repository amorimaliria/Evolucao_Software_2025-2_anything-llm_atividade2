# 
# Este script utiliza a API do GitHub Actions para coletar dados históricos de execuções
# de workflow e calcular métricas de estabilidade do pipeline.
# 

import requests  # Biblioteca para fazer requisições HTTP à API do GitHub
from collections import defaultdict  # Estrutura de dados para agrupar resultados por commit


# --- CONFIGURAÇÕES DO REPOSITÓRIO E AUTENTICAÇÃO ---
REPO = "Mintplex-Labs/anything-llm"  # Repositório alvo da análise
WORKFLOW_FILE = "run-tests.yaml"  # Nome do arquivo de workflow a ser analisado

# Token de autenticação do GitHub (necessário para evitar limite de 60 requisições/hora)
# IMPORTANTE: Em produção, este token deveria estar em variável de ambiente por segurança
GITHUB_TOKEN = "" 

# Configuração de paginação: quantas páginas buscar da API
# Cada página retorna até 100 execuções de workflow
# 10 páginas × 100 = até 1000 execuções analisadas
MAX_PAGES = 10


def check_flakiness_paginated():
    """
    Função principal que coleta dados paginados da API do GitHub Actions.
    
    Processo:
    1. Configura autenticação (se token disponível)
    2. Faz requisições paginadas para obter histórico de execuções
    3. Acumula todos os resultados em uma lista
    4. Chama função de análise para processar os dados
    
    A paginação é necessária porque a API do GitHub limita respostas a 100 itens por vez.
    """
    # Prepara cabeçalhos HTTP para autenticação
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    all_runs = []  # Lista para acumular todas as execuções de workflow coletadas
    
    print(f"Iniciando coleta de dados para: {REPO} (Workflow: {WORKFLOW_FILE})")
    print("Isso pode levar alguns segundos...\n")

    # Loop de paginação: itera através das páginas de resultados da API
    for page in range(1, MAX_PAGES + 1):
        print(f"Baixando página {page}...", end="\r")  # \r sobrescreve a linha (feedback visual)
        
        # Monta URL da API do GitHub Actions
        # Filtra por evento 'pull_request' para focar em PRs (contexto comum de testes)
        url = (
            f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs"
            f"?event=pull_request&per_page=100&page={page}"
        )
        
        try:
            # Faz requisição GET à API do GitHub
            response = requests.get(url, headers=headers)
            
            # Verifica se a requisição foi bem-sucedida (HTTP 200)
            if response.status_code != 200:
                print(f"\nErro na página {page}: {response.status_code}")
                if response.status_code == 403:
                    # HTTP 403 geralmente indica limite de taxa da API atingido
                    print("DICA: Limite da API atingido. Use um Token ou espere 1 hora.")
                break

            # Converte resposta JSON em dicionário Python
            data = response.json()
            runs = data.get("workflow_runs", [])  # Extrai lista de execuções
            
            # Se não há mais dados, chegamos ao fim
            if not runs:
                print(f"\nNenhum registro encontrado na página {page}. Encerrando.")
                break
                
            all_runs.extend(runs)  # Adiciona execuções desta página à lista total
            
            # Otimização: se página tem menos de 100 itens, é a última página
            if len(runs) < 100:
                break
                
        except Exception as e:
            # Captura erros de conexão, timeout, etc.
            print(f"\nErro de conexão: {e}")
            break

    print(f"\n\nTotal de execuções coletadas: {len(all_runs)}")
    analyze_data(all_runs)  # Passa dados coletados para análise


def analyze_data(runs):
    # defaultdict(set) cria automaticamente um conjunto vazio para novas chaves
    # Estrutura: {commit_sha: {conjunto de conclusões possíveis}}
    # Exemplo: {'abc123': {'success', 'failure'}} indica comportamento flaky
    status_per_commit = defaultdict(set)
    
    # Agrupa resultados por commit SHA (identificador único do código)
    for run in runs:
        commit_sha = run['head_sha']  # Hash do commit que foi testado
        conclusion = run['conclusion']  # Resultado: 'success', 'failure', 'cancelled', etc
        
        if conclusion:  # Ignora execuções ainda em andamento (conclusion = None)
            status_per_commit[commit_sha].add(conclusion)

    # === IDENTIFICAÇÃO DE COMMITS FLAKY ===
    flaky_count = 0  # Contador de commits com comportamento instável
    total_commits = len(status_per_commit)  # Total de commits únicos analisados
    flaky_examples = []  # Lista de exemplos para citação no relatório

    for sha, statuses in status_per_commit.items():
        # CRITÉRIO DE FLAKINESS: O mesmo código teve tanto falha quanto sucesso
        # Isso prova que o teste não é determinístico
        if 'failure' in statuses and 'success' in statuses:
            flaky_count += 1
            # Coleta até 5 exemplos de SHAs flaky para evidência no trabalho
            if len(flaky_examples) < 5:
                flaky_examples.append(sha[:7])  # Usa apenas 7 primeiros caracteres (padrão Git)

    # === GERAÇÃO DO RELATÓRIO ===
    print("-" * 40)
    print("RELATÓRIO DE CONFIABILIDADE (FLAKINESS)")
    print("-" * 40)
    print(f"Commits Únicos Analisados: {total_commits}")
    print(f"Commits com comportamento Instável: {flaky_count}")
    
    if total_commits > 0:
        # Calcula taxa de instabilidade (métrica chave para o trabalho)
        taxa = (flaky_count / total_commits) * 100
        print(f"Taxa de Instabilidade: {taxa:.2f}%")
        
        # Interpreta os resultados no contexto de Evolução de Software
        print("\nCONCLUSÃO SUGERIDA PARA O TRABALHO:")
        if taxa > 10:
            # Taxa alta indica problema crítico de qualidade do processo
            print(f"[ALTA] A taxa de {taxa:.1f}% é crítica. O pipeline é um gargalo severo.")
            print("IMPACTO: Desenvolvedores provavelmente gastam tempo significativo re-executando testes.")
        elif taxa > 1:
            # Taxa média confirma presença de testes flaky (comum em projetos reais)
            print(f"[MÉDIA] A taxa de {taxa:.1f}% confirma a existência de testes 'flaky'.")
            print("Isso prova que desenvolvedores frequentemente re-executam jobs para passar.")
            print("RECOMENDAÇÃO: Isolar e corrigir testes instáveis como prioridade de manutenção.")
        else:
            # Taxa baixa sugere que gargalos estão em outras áreas
            print("[BAIXA] O sistema parece estável.")
    
    # Fornece evidências concretas (SHAs) para citação no relatório acadêmico
    if flaky_examples:
        print(f"\nExemplos de SHAs instáveis (cite no relatório): {', '.join(flaky_examples)}")
        print("Estes commits podem ser investigados no GitHub para análise detalhada dos logs.")


# Ponto de entrada do script
# Executa apenas quando o arquivo é rodado diretamente (não quando importado)
if __name__ == "__main__":
    check_flakiness_paginated()
