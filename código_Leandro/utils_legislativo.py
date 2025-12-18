import re
import unicodedata

# Lista Expandida de Stopwords Legislativas
STOPWORDS_LEGISLATIVAS = [
    # Ações Burocráticas
    "dispõe sobre", "dispoe sobre", "trata de", "institui o", "institui a",
    "cria o", "cria a", "estabelece", "normas gerais", "providências",
    "dá outras providências", "da outras providencias", "para os fins",
    "nos termos", "com a finalidade de", "visando a", "a fim de",
    "para dispor sobre", "para prever", "para estender", "para aperfeiçoar",
    
    # Estruturas de Alteração
    "altera a lei", "altera o decreto", "altera os", "altera as",
    "acrescenta", "insere", "modifica", "revoga", "redação dada",
    "redacao dada", "nova redação", "suprime", "veda a", "veda o",
    
    # Referências a Textos Legais (Stopwords Simples)
    "projeto de lei", "pl", "medida provisória", "mpv", "pec",
    "código penal", "código civil", "estatuto", "constituição federal",
    "decreto-lei", "decreto lei", "lei brasileira", "lei de",
    
    # Partes da Lei (Stopwords Simples)
    "caput", "parágrafo único", "paragrafo unico", "inciso", "alínea", 
    "alinea", "item", "dispositivo", "anexo"
]

def limpar_padroes_regex(texto):
    """
    Remove padrões complexos como datas e números de leis usando Regex.
    """
    # 1. Remove referências a leis com números (ex: "Lei nº 12.345", "Lei 12.345")
    texto = re.sub(r'(lei|decreto|medida provisória|resolução|portaria)\s+(n[ºo°]\s*)?[\d\.]+', ' ', texto, flags=re.IGNORECASE)
    
    # 2. Remove datas completas (ex: "de 23 de abril de 2014", "de 7 de dezembro")
    texto = re.sub(r'\bde\s+\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}\b', ' ', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bde\s+\d{1,2}\s+de\s+[a-zç]+\b', ' ', texto, flags=re.IGNORECASE)
    
    # 3. Remove referências a Artigos e Parágrafos (ex: "art. 5º", "§ 2º", "art 10")
    texto = re.sub(r'\bart[\.\s]\s*\d+[ºo°]?', ' ', texto, flags=re.IGNORECASE) # Artigos
    texto = re.sub(r'§\s*\d+[ºo°]?', ' ', texto) # Símbolo de parágrafo
    
    # 4. Remove numeração romana de Incisos (ex: "inciso IV", "inciso X")
    texto = re.sub(r'\binciso\s+[ivxlcdm]+\b', ' ', texto, flags=re.IGNORECASE)
    
    return texto

def limpar_ementa_para_vetorizacao(texto):
    if not texto: return ""
    
    # 1. Normalização Básica (Caixa baixa e acentos)
    texto = texto.lower()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    
    # 2. Limpeza de Padrões (Datas e Números) - NOVO!
    texto = limpar_padroes_regex(texto)
    
    # 3. Limpeza de Stopwords (Lista Fixa)
    for termo in STOPWORDS_LEGISLATIVAS:
        # Remove o termo se ele estiver no texto
        texto = texto.replace(termo, " ")
        
    # 4. Limpeza final de pontuação e espaços extras
    texto = re.sub(r'[^\w\s]', ' ', texto) # Remove pontuação restante
    texto = re.sub(r'\s+', ' ', texto).strip() # Remove espaços duplos
    
    return texto

def limpar_texto_basico(texto):
    """Função leve usada apenas para limpeza simples (busca BM25)."""
    if not texto: return ""
    texto = texto.lower()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return texto