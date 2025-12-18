# filtrador_hibrido_v7_final.py
# VERSÃO FINAL: Correção de Autores + Visualização de Tags no Console

import json
import csv
import os
import sys
import pickle
import numpy as np
import torch
from sentence_transformers import SentenceTransformer, util
from utils_legislativo import limpar_ementa_para_vetorizacao, limpar_texto_basico

# --- CONFIGURAÇÕES ---
CONSULTA_USUARIO = "Regulamentação inteligência artificial"
MODELO_NOME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Pesos
PESO_SEMANTICO = 0.5
PESO_KEYWORD = 0.5    
FILTRO_THRESHOLD = 0.5

# Arquivos
NOME_ARQUIVO_DB = "camara_db_completo_cache.json"
NOME_ARQUIVO_PKL = "keywords_embeddings.pkl" 
NOME_ARQUIVO_SAIDA = "resultado_final_padrao_camara.csv"
ARQUIVO_CACHE_EMB = "cache_ementas_paraphrase.npy"

def carregar_dados():
    if not os.path.exists(NOME_ARQUIVO_DB) or not os.path.exists(NOME_ARQUIVO_PKL):
        print("Erro: Arquivos de dados (DB ou PKL) não encontrados.")
        sys.exit()
    with open(NOME_ARQUIVO_DB, 'r', encoding='utf-8') as f: db = json.load(f)
    with open(NOME_ARQUIVO_PKL, 'rb') as f: kw = pickle.load(f)
    return db, kw

def preparar_embeddings_ementas(db, model):
    if os.path.exists(ARQUIVO_CACHE_EMB):
        try:
            embs = np.load(ARQUIVO_CACHE_EMB)
            if len(embs) == len(db): 
                print("Cache de ementas carregado.")
                return embs
        except: pass
    
    print("Gerando novos embeddings (Isso pode demorar uns minutos)...")
    textos_limpos = [limpar_ementa_para_vetorizacao(p.get('ementa', '')) for p in db]
    embeddings = model.encode(textos_limpos, batch_size=32, show_progress_bar=True)
    np.save(ARQUIVO_CACHE_EMB, embeddings)
    return embeddings

def extrair_metadados_corrigido(p):
    """
    Extrai dados usando as chaves identificadas no diagnóstico (v7).
    """
    # 1. AUTORES E PARTIDO
    autor_principal = p.get('autor_principal_nome')
    partido_principal = p.get('autor_principal_partido')
    coautores = p.get('coautores_nomes')
    
    lista_autores = []
    if autor_principal:
        lista_autores.append(str(autor_principal))
        
    if coautores:
        if isinstance(coautores, list):
            lista_autores.extend([str(c) for c in coautores])
        elif isinstance(coautores, str):
            lista_autores.append(coautores)
            
    # Remove duplicatas mantendo a ordem
    autores_finais = list(dict.fromkeys(lista_autores))
    
    # 2. STATUS (A chave correta identificada foi 'statusProposicao')
    status = p.get('statusProposicao')
    ultimo_estado = ""
    data_ultimo = ""
    situacao = ""
    
    if isinstance(status, dict):
        ultimo_estado = status.get('descricaoTramitacao', '') or status.get('despacho', '')
        data_ultimo = status.get('dataHora', '') or status.get('data', '')
        situacao = status.get('descricaoSituacao', '')
    
    return {
        "autores": ", ".join(autores_finais) if autores_finais else "Não informado",
        "partido": str(partido_principal) if partido_principal else "",
        "ultimo_estado": ultimo_estado,
        "data_ultimo": data_ultimo,
        "situacao": situacao
    }

def buscar_hibrido(consulta, model, embs, db, kw_data):
    consulta_limpa = limpar_ementa_para_vetorizacao(consulta)
    print(f"Buscando por: '{consulta}'")
    
    emb_query = model.encode(consulta_limpa, convert_to_tensor=True)
    
    # --- IDENTIFICAÇÃO DE TAGS (BOOST) ---
    scores_kw = util.cos_sim(emb_query, kw_data['keywords_vectors'])[0]
    top_kw = torch.topk(scores_kw, k=40
    
    
    
    
    
    
    
    
    )
    
    tags_alvo_lista = []
    print("\nTags identificadas para o tema:") # Título no console
    
    for sc, idx in zip(top_kw.values, top_kw.indices):
        if float(sc) > 0.70:
            tag_encontrada = kw_data['keywords_texto'][idx]
            tags_alvo_lista.append(tag_encontrada)
            # Mostra cada tag encontrada
            print(f" -> {tag_encontrada} ({float(sc):.2f})")

    # --- CÁLCULO SEMÂNTICO ---
    if isinstance(embs, np.ndarray): embs_tensor = torch.from_numpy(embs)
    else: embs_tensor = embs
    sim_scores = util.cos_sim(emb_query, embs_tensor)[0].numpy()
    
    resultados = []
    
    for i, p in enumerate(db):
        score_sem = float(sim_scores[i])
        score_boost = 0.0
        
        if tags_alvo_lista:
            raw_tags = (p.get('keywords') or '') + ' ' + (p.get('indexacao') or '')
            p_tags_upper = limpar_texto_basico(raw_tags).upper()
            for tag in tags_alvo_lista:
                if tag in p_tags_upper:
                    score_boost = 1.0
                    break
        
        final = (score_sem * PESO_SEMANTICO) + (score_boost * PESO_KEYWORD)
        
        if final >= FILTRO_THRESHOLD:
            # Extrai metadados com a função corrigida
            meta = extrair_metadados_corrigido(p)
            
            resultados.append({
                "Norma": f"{p.get('siglaTipo')} {p.get('numero')}/{p.get('ano')}",
                "Similaridade Semantica": f"{final:.4f}".replace('.', ','),
                "Descricao da Sigla": p.get('descricaoTipo', p.get('siglaTipo', '')),
                "Data de Apresentacao": p.get('dataApresentacao', '')[:10],
                "Autor": meta['autores'],
                "Partido": meta['partido'],
                "Ementa": p.get('ementa', '').strip(),
                "Link Documento PDF": p.get('urlInteiroTeor', ''),
                "Link Página Web": p.get('url_pagina_web_oficial', ''),
                "Indexacao": p.get('keywords', p.get('indexacao', '')),
                "Último Estado": meta['ultimo_estado'],
                "Data Último Estado": meta['data_ultimo'][:10],
                "Situação": meta['situacao'],
                "raw_score": final
            })
            
    return sorted(resultados, key=lambda x: x['raw_score'], reverse=True)

def salvar_csv(dados):
    if not dados: return
    colunas = [
        "Norma", "Similaridade Semantica", "Descricao da Sigla", 
        "Data de Apresentacao", "Autor", "Partido", "Ementa", 
        "Link Documento PDF", "Link Página Web", "Indexacao", 
        "Último Estado", "Data Último Estado", "Situação"
    ]
    with open(NOME_ARQUIVO_SAIDA, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=colunas, extrasaction='ignore', delimiter=';')
        writer.writeheader()
        writer.writerows(dados)
    print(f"\nArquivo salvo: {NOME_ARQUIVO_SAIDA} com {len(dados)} resultados.")

if __name__ == "__main__":
    db, kw = carregar_dados()
    print(f"Carregando modelo {MODELO_NOME}...")
    model = SentenceTransformer(MODELO_NOME)
    embs = preparar_embeddings_ementas(db, model)
    res = buscar_hibrido(CONSULTA_USUARIO, model, embs, db, kw)
    salvar_csv(res)