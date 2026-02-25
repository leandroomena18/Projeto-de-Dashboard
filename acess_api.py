import sys
import os
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def executar_script(nome_script):
    caminho = os.path.join(BASE_DIR, nome_script)
    print(f"\n>>> Executando {nome_script}...")
    try:
        subprocess.run([sys.executable, caminho], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERRO] Falha em {nome_script}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("--- INICIANDO PIPELINE DE DADOS EM BLOCOS (SHARDING) ---")
    
    executar_script("coletor_camara2.py")
    executar_script("gerador_keywords.py")
    executar_script("filtrador_hibrido_v3_final.py")
    
    print("\n--- IA CONCLUÍDA: DADOS PRONTOS PARA O BANCO SQL ---")