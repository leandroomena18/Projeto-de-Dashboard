# gerador_keywords.py (ATUALIZADO)
import json
import pickle
import time
from sentence_transformers import SentenceTransformer
from utils_legislativo import limpar_texto_basico # Importa do nosso novo arquivo

# --- CONFIGURAÇÕES ---
NOME_ARQUIVO_BANCO_DADOS = "camara_db_completo_cache.json"
NOME_ARQUIVO_PKL_SAIDA = "keywords_embeddings.pkl"
MODELO_NOME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Palavras que aparecem no campo 'keywords' da Câmara mas não ajudam
BLACKLIST_KEYWORDS = {"projeto", "lei", "sobre", "alteracao", "criacao", "instituicao", "federal", "nacional"}

def carregar_banco_dados(nome_arquivo):
    try:
        with open(nome_arquivo, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: return None

def extrair_keywords(dados):
    print("Extraindo e limpando keywords...")
    unique_keywords = set()
    for projeto in dados:
        # Tenta pegar 'keywords' ou 'indexacao'
        texto = projeto.get('keywords') or projeto.get('indexacao')
        if texto:
            termos = texto.replace(';', ',').split(',')
            for termo in termos:
                t_limpo = limpar_texto_basico(termo).upper() # Mantemos Upper para padronizar
                # Só aceita se for maior que 3 letras e não for proibida
                if len(t_limpo) > 3 and t_limpo.lower() not in BLACKLIST_KEYWORDS:
                    unique_keywords.add(t_limpo)
    return sorted(list(unique_keywords))

def vetorizar_e_salvar(lista_keywords):
    print(f"Carregando modelo {MODELO_NOME}...")
    model = SentenceTransformer(MODELO_NOME)
    
    print(f"Vetorizando {len(lista_keywords)} tags...")
    embeddings = model.encode(lista_keywords, batch_size=64, show_progress_bar=True, convert_to_tensor=True)
    
    dados_pkl = {"keywords_texto": lista_keywords, "keywords_vectors": embeddings.cpu()}
    
    with open(NOME_ARQUIVO_PKL_SAIDA, "wb") as f: pickle.dump(dados_pkl, f)
    print("Sucesso! Keywords vetorizadas.")

if __name__ == "__main__":
    dados = carregar_banco_dados(NOME_ARQUIVO_BANCO_DADOS)
    if dados:
        lista = extrair_keywords(dados)
        vetorizar_e_salvar(lista)