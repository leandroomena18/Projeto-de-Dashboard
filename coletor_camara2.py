import requests
import json
import os
import time
import glob
from datetime import datetime, timedelta
import threading
import concurrent.futures
import config
from utils_legislativo import obter_legislatura

CAMARA_BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
TIPOS_DOCUMENTO = ["PL", "PLP", "PEC"]

# Aponta para a nova pasta de dados estruturada
ARQUIVO_CACHE_PARTIDOS = os.path.join(config.PASTA_DADOS, "cache_partidos.json")
MAX_WORKERS = 10 
thread_local = threading.local()
cache_lock = threading.Lock()

def get_session():
    """
    Retorna uma sessão HTTP específica da thread atual.

    Por que isso existe?

    - requests.Session() reaproveita conexões TCP (connection pooling).
    - Criar uma nova sessão a cada requisição é custoso.
    - Como estamos usando múltiplas threads, não é seguro compartilhar
      uma única Session global entre elas.

    Solução adotada:
    - Cada thread possui sua própria sessão (thread-local storage).
    - Isso evita conflitos e melhora performance.

    thread_local é um objeto especial onde cada thread tem seu
    próprio espaço de atributos.
    """
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
    return thread_local.session

def obter_lista_ids(base_url, data_inicio_global, data_fim_global, tipos):
    """
    Objetivo:
        Buscar TODOS os IDs de proposições no intervalo de datas especificado,
        filtrando pelos tipos desejados (PL, PLP, PEC, etc).

    Estratégia:

    1) Divide o intervalo total em blocos menores de 90 dias.
       Isso evita:
           - Respostas muito grandes
           - Timeout
           - Problemas de paginação excessiva

    2) Para cada bloco de datas:
           - Faz requisição paginada à API
           - Coleta apenas os IDs (não detalhes completos)
           - Armazena em um set para evitar duplicatas

    3) Retorna lista final de IDs únicos.

    Essa função NÃO busca detalhes.
    Ela apenas constrói a lista base para o processamento posterior.
    """

    print(f"A procurar IDs (A filtrar estritamente pela Data de Apresentação)...")
    # Usamos set para evitar duplicatas automaticamente.
    ids_encontrados = set()
    # Sessão simples (não precisa ser thread-local aqui,
    # pois essa função roda de forma sequencial).
    session = requests.Session()
    # Dividimos em blocos de 90 dias para controlar volume.
    passo_dias = timedelta(days=90) 
    data_atual = data_inicio_global

    # Percorre o intervalo de datas
    while data_atual <= data_fim_global:
        data_proxima = min(data_atual + passo_dias, data_fim_global)
        print(f"-> A varrer período: {data_atual.strftime('%Y-%m-%d')} até {data_proxima.strftime('%Y-%m-%d')}")
        
        url = f"{base_url}/proposicoes"


        # Parâmetros da API:
        # - dataApresentacaoInicio/Fim: filtro por data
        # - siglaTipo: tipos de proposição
        # - itens=100: máximo por página
        # - ordenação crescente por ID (estável para paginação)
        # A MUDANÇA ESTÁ AQUI: dataApresentacaoInicio e dataApresentacaoFim
        params = {
            "dataApresentacaoInicio": data_atual.strftime("%Y-%m-%d"), 
            "dataApresentacaoFim": data_proxima.strftime("%Y-%m-%d"), 
            "siglaTipo": tipos, 
            "itens": 100, 
            "ordem": "ASC", 
            "ordenarPor": "id"
        }

        # Loop de paginação
        while url:
            try:
                r = session.get(url, params=params, timeout=15)
                # Se API sinalizar rate limit (429),
                # aguardamos e tentamos novamente.
                if r.status_code == 429:
                    time.sleep(5)
                    continue
                r.raise_for_status()
                dados = r.json()

                # Coleta apenas os IDs
                for p in dados.get('dados', []): ids_encontrados.add(p['id'])

                # Verifica se há link para próxima página
                links = dados.get('links', [])
                url = next((link['href'] for link in links if link['rel'] == 'next'), None)

                # Após primeira página, params já estão embutidos na URL.
                params = None
            except Exception as e:
                # Se houver erro, abandona esse bloco de datas.
                break
        # Avança para o próximo intervalo de 90 dias
        data_atual = data_proxima + timedelta(days=1)
    session.close()
    return list(ids_encontrados)

def processar_uma_proposicao(prop_id, cache_autores):
    """
    Objetivo:
        Buscar detalhes completos de uma proposição
        e enriquecê-la com:
            - URL pública oficial
            - Autor principal
            - Partido do autor principal
            - Lista de coautores

    Entrada:
        - prop_id: ID da proposição
        - cache_autores: dict compartilhado entre threads
          que mapeia:
              { uri_deputado: sigla_partido }

    Retorno:
        - dict com dados completos enriquecidos
        - ou None se falhar
    """

    # Obtém sessão específica da thread
    session = get_session()
    url_detalhe = f"{CAMARA_BASE_URL}/proposicoes/{prop_id}"

    # Tentamos até 3 vezes em caso de erro
    for _ in range(3):
        try:
            # Pega a resposta da requisicao de proposição detalhada da API
            r = session.get(url_detalhe, timeout=10)

            # Tratamento de rate limit
            if r.status_code == 429:
                time.sleep(2)
                continue
            if r.status_code != 200: return None

            # Extrai dados principais
            dados = r.json().get('dados', {})

            # Monta URL oficial pública da proposição
            uri_str = dados.get('uri', '')
            dados['url_pagina_web_oficial'] = f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={uri_str.rstrip('/').split('/')[-1]}" if uri_str else ""

            # Valores padrão
            autor_nome, autor_partido, coautores = "Desconhecido", "N/A", []

            uri_autores = dados.get('uriAutores')

            if uri_autores:
                r_aut = session.get(uri_autores, timeout=10)
                if r_aut.status_code == 200:
                    lista_autores = r_aut.json().get('dados', [])
                    if lista_autores:
                        # Primeiro autor é considerado principal
                        autor_principal = lista_autores[0]
                        autor_nome = autor_principal.get('nome', 'Desconhecido')

                        uri_deputado = autor_principal.get('uri')

                        # Só buscamos partido se for deputado
                        if uri_deputado and 'deputados' in uri_deputado:
                            # Verifica no cache com lock
                            with cache_lock: tem_no_cache = uri_deputado in cache_autores
                            if tem_no_cache: autor_partido = cache_autores[uri_deputado]
                            else:
                                # Busca detalhes do deputado
                                r_dep = session.get(uri_deputado, timeout=10)
                                if r_dep.status_code == 200:
                                    autor_partido = r_dep.json().get('dados', {}).get('ultimoStatus', {}).get('siglaPartido', 'N/A')
                                    # Atualiza cache com lock
                                    with cache_lock: cache_autores[uri_deputado] = autor_partido
                        # Demais autores viram coautores
                        if len(lista_autores) > 1: coautores = [a.get('nome') for a in lista_autores[1:]]

            # Enriquecimento final do objeto
            dados['autor_principal_nome'] = autor_nome
            dados['autor_principal_partido'] = autor_partido
            dados['coautores_nomes'] = coautores
            return dados
        # Em caso de erro inesperado, espera e tenta novamente
        except: time.sleep(1)
    return None

def obter_detalhes_e_separar(lista_ids):
    """
    FUNÇÃO PRINCIPAL DE EXTRAÇÃO E PARTICIONAMENTO.

    Responsabilidades:
    1) Processar cada ID de proposição em paralelo (multithread).
    2) Enriquecer cada proposição (via processar_uma_proposicao).
    3) Separar os resultados por legislatura (sharding lógico).
    4) Persistir os dados particionados em arquivos JSON.
    5) Atualizar o cache local de partidos.

    Entrada:
        - lista_ids: lista de IDs de proposições previamente coletadas.

    Saída:
        - Arquivos JSON particionados por legislatura.
        - Arquivo de cache de partidos atualizado.
    """

    print(f"\nExtração MULTITHREAD de {len(lista_ids)} projetos...")

    # Cache em memória que armazena:
    # { uri_deputado: sigla_partido }
    # Isso evita múltiplas chamadas à API para o mesmo deputado.
    cache_autores = {}

    # Se já existe cache salvo em disco, carregamos
    # para evitar repetir requisições já feitas em execuções anteriores.
    if os.path.exists(ARQUIVO_CACHE_PARTIDOS):
        with open(ARQUIVO_CACHE_PARTIDOS, 'r', encoding='utf-8') as f: cache_autores = json.load(f)


    # Estrutura final onde vamos armazenar os projetos
    # organizados por legislatura:
    #
    # Exemplo:
    # {
    #   "leg56": [ {projeto1}, {projeto2}, ... ],
    #   "leg57": [ {projetoX}, ... ]
    # }
    bancos_separados = {}

    # Variáveis para monitoramento de progresso
    total, processados, start_time = len(lista_ids), 0, time.time()

    # Criamos um pool de threads para processar múltiplas proposições
    # simultaneamente. Isso acelera bastante pois o gargalo aqui é I/O (HTTP)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Para cada ID, submetemos uma tarefa ao pool:
        # Cada tarefa executa processar_uma_proposicao(pid, cache_autores)
        #
        # O resultado é um objeto Future.
        # Guardamos um dicionário:
        #   future -> pid
        # Isso permite rastrear qual tarefa corresponde a qual ID.
        futuros = {executor.submit(processar_uma_proposicao, pid, cache_autores): pid for pid in lista_ids}

        # as_completed() retorna os futures conforme eles terminam,
        # não importa a ordem de envio.
        # Isso permite processar resultados assim que ficam prontos.
        for futuro in concurrent.futures.as_completed(futuros):
            processados += 1

            # Obtém o resultado da thread.
            # Pode ser:
            #   - dict com dados enriquecidos
            #   - None (caso falha na requisição)
            res = futuro.result()
            if res:
                # Determina a legislatura a partir do ano da proposição.
                # Essa função define em qual "shard lógico" o projeto será salvo.
                leg = obter_legislatura(res.get('ano', 0))

                # Se ainda não existe uma lista para essa legislatura,
                # criamos dinamicamente.
                if leg not in bancos_separados: bancos_separados[leg] = []

                # Adicionamos o projeto enriquecido
                # na lista correspondente à sua legislatura.
                bancos_separados[leg].append(res)

            # A cada 100 projetos (ou no final),
            # exibimos métricas de desempenho.
            if processados % 100 == 0 or processados == total:
                vel = processados / (time.time() - start_time)
                eta = (total - processados) / vel / 60 if vel > 0 else 0
                print(f"[{processados}/{total}] Vel: {vel:.1f} p/s | ETA: {eta:.1f} min")

    # Após finalizar todas as threads,
    # salvamos o cache atualizado de partidos em disco.
    # Isso permite reaproveitamento em execuções futuras.
    with open(ARQUIVO_CACHE_PARTIDOS, 'w', encoding='utf-8') as f: json.dump(cache_autores, f, ensure_ascii=False)

    # Agora persistimos os dados particionados.
    # Cada legislatura vira um arquivo JSON independente.
    for leg, projetos in bancos_separados.items():
        # Guarda os dados corretamente particionados
        # Nome do arquivo segue o padrão:
        # camara_db_leg56.json
        nome_arquivo = os.path.join(config.PASTA_DADOS, f"camara_db_{leg}.json")

        # Salvamos a lista completa daquela legislatura.
        # indent=4 facilita leitura humana.
        with open(nome_arquivo, 'w', encoding='utf-8') as f:
            json.dump(projetos, f, indent=4, ensure_ascii=False)
        print(f"-> Guardado: {nome_arquivo} ({len(projetos)} projetos)")

if __name__ == "__main__":
    """
    BLOCO DE EXECUÇÃO PRINCIPAL DO SCRIPT.

    Esse bloco só roda quando o arquivo é executado diretamente:
        python coletor_camara.py

    Se o arquivo for importado como módulo em outro script,
    esse bloco NÃO é executado.

    Responsabilidades da main:
        1) Garantir que a pasta de dados exista.
        2) Verificar se já existem arquivos de cache (bancos particionados).
        3) Se existir cache → evita nova coleta.
        4) Se não existir → executa pipeline completo:
               - coleta IDs
               - extrai detalhes
               - particiona por legislatura
    """

    # Garante que a pasta onde os arquivos JSON serão salvos exista.
    # Se não existir, cria automaticamente.
    if not os.path.exists(config.PASTA_DADOS): os.makedirs(config.PASTA_DADOS)

    # Define padrão para verificar se já existem arquivos
    # do tipo: camara_db_leg55.json, camara_db_leg56.json etc.
    #
    # Isso é usado como mecanismo simples de cache global.
    padrao_busca = os.path.join(config.PASTA_DADOS, "camara_db_leg*.json")
    # glob retorna todos os arquivos que combinam com o padrão
    arquivos_cache = glob.glob(padrao_busca)

    # Se já houver arquivos salvos anteriormente,
    # o sistema entende que os dados já foram coletados.
    if len(arquivos_cache) > 0:
        print(f"\n[CACHE] Encontrados {len(arquivos_cache)} ficheiros na pasta {config.PASTA_DADOS}.")
        print("[CACHE] A saltar a recolha. Apague os ficheiros se quiser forçar o descarregamento de dados novos.")
    else:
        # Se não houver cache, iniciamos a coleta completa.

        # 1) Busca todos os IDs de proposições
        #    dentro do intervalo definido no config.
        #
        # Parâmetros importantes:
        # - CAMARA_BASE_URL: endpoint da API
        # - DATA_INICIO_COLETA: definido no config
        # - datetime.now(): coleta até hoje
        # - TIPOS_DOCUMENTO: PL, PLP, PEC
        ids = obter_lista_ids(CAMARA_BASE_URL, config.DATA_INICIO_COLETA, datetime.now(), TIPOS_DOCUMENTO)
        # 2) Se houver IDs encontrados,
        #    executa extração detalhada e particionamento.
        if ids: obter_detalhes_e_separar(ids)