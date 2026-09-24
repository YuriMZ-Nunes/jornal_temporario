#!/usr/bin/env python3
"""
Orquestrador do pipeline do Jornal do Yuri.
Executa os scripts sequencialmente na ordem necessária:
1. extract_newsletters.py
2. build_candidates.py
3. editor_llm.py
4. nasa_apod.py
5. gerar.py
"""

import argparse
import sys
import subprocess
import time
from pathlib import Path

# Configuração dos passos do pipeline
# Cada passo tem um nome, o arquivo correspondente, e uma descrição.
PIPELINE_STEPS = [
    {
        "name": "extrair",
        "script": "extract_newsletters.py",
        "desc": "Extrair newsletters do Gmail",
    },
    {
        "name": "candidatos",
        "script": "build_candidates.py",
        "desc": "Construir base de candidatos",
    },
    {
        "name": "editor",
        "script": "editor_llm.py",
        "desc": "Selecionar e resumir notícias via LLM",
    },
    {
        "name": "nasa",
        "script": "nasa_apod.py",
        "desc": "Baixar Astronomia do Dia da NASA",
    },
    {
        "name": "gerar",
        "script": "gerar.py",
        "desc": "Gerar o PDF do Jornal",
    },
]

def run_step(script_name: str, extra_args: list[str] | None = None) -> bool:
    """
    Executa um passo do pipeline usando o mesmo interpretador Python.
    """
    script_path = Path(script_name)
    if not script_path.exists():
        print(f"❌ Erro: O script '{script_name}' não foi encontrado no diretório atual.")
        return False

    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)

    print(f"\n========================================================")
    print(f"🚀 Executando: {' '.join(cmd)}")
    print(f"========================================================\n")

    try:
        # Permite que a saída e erros sejam exibidos diretamente no terminal em tempo real
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Falha ao executar '{script_name}' (Código de saída: {e.returncode})")
        return False
    except Exception as e:
        print(f"\n❌ Erro inesperado ao tentar rodar '{script_name}': {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Orquestrador sequencial para a geração do Jornal do Yuri."
    )
    
    parser.add_argument(
        "--edition",
        choices=["manha", "noite"],
        default="manha",
        help="Tipo da edição a gerar (passado para gerar.py). Padrão: manha",
    )
    
    parser.add_argument(
        "--model",
        help="Modelo Ollama a usar (passado para editor_llm.py). Se não fornecido, usa o padrão do script.",
    )

    args = parser.parse_args()

    start_time = time.time()
    
    print("========================================================")
    print("📰 INICIANDO PIPELINE DE GERAÇÃO DO JORNAL DO YURI 📰")
    print("========================================================")
    print(f"Configurações:")
    print(f" - Edição: {args.edition}")
    if args.model:
        print(f" - Modelo LLM: {args.model}")
    print("========================================================\n")

    for step in PIPELINE_STEPS:
        step_name = step["name"]
        script_name = step["script"]
        desc = step["desc"]

        print(f"➡️  Iniciando passo: {desc} ({script_name})...")
        
        # Determina argumentos adicionais específicos de cada passo
        extra_args = []
        if step_name == "editor" and args.model:
            extra_args = ["--model", args.model]
        elif step_name == "gerar" and args.edition:
            extra_args = ["--edition", args.edition]

        step_start = time.time()
        success = run_step(script_name, extra_args)
        step_duration = time.time() - step_start

        if not success:
            print(f"\n🛑 Pipeline interrompido devido a erro no passo: {desc} ({script_name}).")
            sys.exit(1)
            
        print(f"✅ Passo concluído com sucesso em {step_duration:.2f}s.\n")

    total_duration = time.time() - start_time
    print("========================================================")
    print(f"🎉 PIPELINE CONCLUÍDO COM SUCESSO EM {total_duration:.2f}s! 🎉")
    print("========================================================")

if __name__ == "__main__":
    main()
