# =============================================================================
# SCRIPT 1: COLETOR FINAL (SESSION + CACHE DE DEPUTADOS + AUTOR PRINCIPAL)
# 
# 1. Baixa lista de IDs por data.
# 2. Busca detalhes do projeto.
# 3. Verifica se o autor já está no cache para não buscar o partido 2 vezes.
# 4. CORREÇÃO: Constrói o link oficial da Câmara.
# =============================================================================

import requests
import json
import os
import time
from datetime import datetime, timedelta
import sys

# --- CONFIGURAÇÕES ---
CAMARA_BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"

# Mude aqui o período desejado
DATA_INICIO_COLETA = datetime(2015, 1, 1) 
DATA_FIM_COLETA = datetime.now()
TIPOS_DOCUMENTO = ["PL", "PLP", "PEC"]

# Arquivos
NOME_ARQUIVO_BANCO_DADOS = "camara_db_completo_cache.json"
NOME_ARQUIVO_CACHE_IDS = "temp_lista_ids.json"

# Se mudar a data, mude para False ou apague o arquivo temp_lista_ids.json
USAR_CACHE_LISTA_IDS = True 

# --- FUNÇÕES ---

def salvar_json(dados, nome_arquivo):
    try:
        with open(nome_arquivo, 'w', encoding='utf-8') as f:
            json.dump(dados, f, indent=4, ensure_ascii=False)
        print(f"\n[IO] Dados salvos em: '{nome_arquivo}'")
    except Exception as e:
        print(f"[ERRO] Falha ao salvar: {e}")

def carregar_json(nome_arquivo):
    if not os.path.exists(nome_arquivo):
        return None
    try:
        with open(nome_arquivo, 'r', encoding='utf-8') as f:
            print(f"[CACHE] Carregando lista de IDs salva: '{nome_arquivo}'...")
            return json.load(f)
    except Exception as e:
        return None

def obter_lista_ids(base_url, dt_inicio, dt_fim, tipos):
    session = requests.Session()
    proposicoes = []
    curr = dt_inicio
    
    print(f"\n--- ETAPA 1: Buscando IDs de Projetos ---")

    while curr < dt_fim:
        # Pega blocos de 3 meses
        next_date = curr + timedelta(days=90)
        if next_date > dt_fim: next_date = dt_fim
        
        dt_ini_str = curr.strftime("%Y-%m-%d")
        dt_fim_str = next_date.strftime("%Y-%m-%d")
        
        print(f" -> Período: {dt_ini_str} a {dt_fim_str}")
        
        url = f"{base_url}/proposicoes"
        params = {
            "dataApresentacaoInicio": dt_ini_str,
            "dataApresentacaoFim": dt_fim_str,
            "siglaTipo": ",".join(tipos),
            "itens": 100, "ordem": "ASC", "ordenarPor": "id"
        }
        
        # Paginação
        while url:
            try:
                r = session.get(url, params=params, timeout=15)
                r.raise_for_status()
                data = r.json()
                proposicoes.extend(data.get('dados', []))
                
                next_link = None
                for link in data.get('links', []):
                    if link.get('rel') == 'next':
                        next_link = link.get('href')
                        break
                url = next_link
                params = None
                time.sleep(0.05) # Pausa leve
            except Exception as e:
                print(f"    Erro: {e}")
                break
        
        curr = next_date + timedelta(days=1)
    
    session.close()
    unicos = {p['id']: p for p in proposicoes}.values()
    print(f" -> Total de projetos encontrados: {len(unicos)}")
    return list(unicos)

def obter_detalhes_com_cache_partidario(lista_basica, base_url):
    session = requests.Session()
    proposicoes_detalhadas = []
    total = len(lista_basica)
    
    # Guarda { "http.../deputados/1234": "PL" }
    cache_partidos = {} 
    
    print(f"\n--- ETAPA 2: Detalhes + Cache de Partidos ---")
    
    for i, item in enumerate(lista_basica):
        prop_id = item['id']
        
        if (i + 1) % 50 == 0:
            print(f"  Progresso: {i + 1}/{total} | Deputados no Cache: {len(cache_partidos)}")
            
        try:
            # 1. Pega Projeto
            r = session.get(f"{base_url}/proposicoes/{prop_id}", timeout=10)
            if r.status_code != 200: continue
            
            dados = r.json().get('dados', {})
            
            # --- CONSTRUÇÃO DO LINK DA PÁGINA WEB OFICIAL (CORREÇÃO) ---
            # Adiciona o link direto para a ficha de tramitação ao objeto 'dados'
            id_proposicao_no_dados = dados.get('id')
            if id_proposicao_no_dados:
                 url_pagina_web_oficial = f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={id_proposicao_no_dados}"
                 dados['url_pagina_web_oficial'] = url_pagina_web_oficial
            # -----------------------------------------------------------

            uri_autores = dados.get('uriAutores')
            
            autor_nome = "Desconhecido"
            autor_partido = "S/P"
            coautores = []
            
            # 2. Pega Autores
            if uri_autores:
                try:
                    r_aut = session.get(uri_autores, timeout=10)
                    lista_autores = r_aut.json().get('dados', [])
                    
                    if lista_autores:
                        # --- Autor Principal (Índice 0) ---
                        principal = lista_autores[0]
                        autor_nome = principal.get('nome')
                        uri_deputado = principal.get('uri')
                        
                        # --- LÓGICA DE CACHE ---
                        if uri_deputado:
                            if uri_deputado in cache_partidos:
                                # Já temos esse deputado no cache? Usa direto!
                                autor_partido = cache_partidos[uri_deputado]
                            else:
                                # Não temos? Vai na API buscar.
                                try:
                                    r_dep = session.get(uri_deputado, timeout=5)
                                    if r_dep.status_code == 200:
                                        d_dep = r_dep.json().get('dados', {})
                                        autor_partido = d_dep.get('ultimoStatus', {}).get('siglaPartido', 'S/P')
                                        
                                        # SALVA NO CACHE AGORA
                                        cache_partidos[uri_deputado] = autor_partido
                                        # Só faz sleep se realmente acessou a API
                                        time.sleep(0.1) 
                                except:
                                    pass
                        
                        # --- Coautores (Só nomes) ---
                        if len(lista_autores) > 1:
                            coautores = [a.get('nome') for a in lista_autores[1:]]

                except Exception:
                    pass

            dados['autor_principal_nome'] = autor_nome
            dados['autor_principal_partido'] = autor_partido
            dados['coautores_nomes'] = coautores
            
            proposicoes_detalhadas.append(dados)

        except Exception as e:
            print(f"  Erro ID {prop_id}: {e}")
            session.close()
            session = requests.Session()
            time.sleep(1)
            
    session.close()
    return proposicoes_detalhadas

# --- EXECUÇÃO ---

if __name__ == "__main__":
    ids = []
    
    if USAR_CACHE_LISTA_IDS:
        ids = carregar_json(NOME_ARQUIVO_CACHE_IDS)
        if ids: print(" -> Usando lista de IDs salva (Se alterou datas, apague este arquivo!)")
    
    if not ids:
        ids = obter_lista_ids(CAMARA_BASE_URL, DATA_INICIO_COLETA, DATA_FIM_COLETA, TIPOS_DOCUMENTO)
        salvar_json(ids, NOME_ARQUIVO_CACHE_IDS)
    
    final = obter_detalhes_com_cache_partidario(ids, CAMARA_BASE_URL)
    
    if final:
        salvar_json(final, NOME_ARQUIVO_BANCO_DADOS)
        print("Finalizado com sucesso.")