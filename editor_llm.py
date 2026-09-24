#!/usr/bin/env python3

import argparse
import json
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ollama import chat


INPUT_FILE = Path("output/candidates.json")
OUTPUT_FILE = Path("output/stories.json")

DEFAULT_MODEL = "qwen2.5:1.5b"

FILIPE_SOURCE = "filipe deschamps newsletter"
THE_NEWS_SOURCE = "the news"

FILIPE_TECH_SECTION = "tecnologia"
FILIPE_TECH_STORIES = 4
FILIPE_TECH_CANDIDATES = 10

STORIES_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "minItems": 1,
            "maxItems": FILIPE_TECH_STORIES,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": (
                            "ID exato de um candidato recebido. "
                            "Copie sem alterar."
                        ),
                    },
                },
                "required": [
                    "candidate_id",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "stories",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = f"""
Você é um seletor editorial de tecnologia de um jornal pessoal de Yuri.

Você receberá exclusivamente candidatos reais da fonte Filipe Deschamps
Newsletter, todos na seção Tecnologia.

Sua única tarefa é escolher exatamente {FILIPE_TECH_STORIES} IDs para a edição.

REGRAS:
1. Retorne exatamente {FILIPE_TECH_STORIES} candidate_id, sem repetir IDs.
2. Copie cada candidate_id exatamente como recebido.
3. Nunca invente, altere ou complete um ID.
4. Não selecione publicidade, conteúdo patrocinado, produto, serviço,
   cupom, marketing, recomendação ou publieditorial.
5. Priorize Linux, programação, sistemas, hardware, RISC-V, segurança,
   IA, pesquisa, arquitetura de computadores e software livre.
6. Não escreva títulos, resumos, explicações, ranking ou texto extra.
7. Retorne somente JSON compatível com o schema.
""".strip()


def normalize_label(text):
    """
    Normaliza texto para comparações internas.

    Exemplos:
    - 'Filipe Deschamps\\xa0Newsletter' -> 'filipe deschamps newsletter'
    - 'the news ☕' -> 'the news'
    - 'CIÊNCIA' -> 'ciencia'
    - 'ESPECIAL ELEIÇÕES 2026' -> 'especial eleicoes 2026'
    """
    normalized = unicodedata.normalize(
        "NFKD",
        str(text),
    )

    clean = "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
        and (char.isalnum() or char.isspace())
    )

    return " ".join(
        clean.casefold().split()
    )


def is_filipe_technology(candidate):
    """
    Retorna True somente para candidatos de Tecnologia
    da newsletter Filipe Deschamps.
    """
    return (
        normalize_label(candidate.get("source", ""))
        == FILIPE_SOURCE
        and normalize_label(candidate.get("section", ""))
        == FILIPE_TECH_SECTION
    )


def is_the_news(candidate):
    """
    Retorna True para candidatos da newsletter The News.

    O emoji de café é removido por normalize_label(), então:
    'the news ☕' passa a ser comparado como 'the news'.
    """
    return (
        normalize_label(candidate.get("source", ""))
        == THE_NEWS_SOURCE
    )

def is_single_word_the_news_section(candidate):
    """
    Retorna True apenas para seções do The News com uma única palavra.

    A normalização remove acentos, emojis e espaços duplicados antes
    da contagem.
    """
    section = normalize_label(
        candidate.get("section", "")
    )

    return len(section.split()) == 1

def prepare_filipe_candidates(data):
    """
    Prepara somente os candidatos técnicos do Filipe para a LLM.

    The News não é enviado à IA: suas matérias entram diretamente
    em stories.json, preservando títulos e textos originais.
    """
    all_candidates = data.get("candidates", [])

    filipe_tech = [
        candidate
        for candidate in all_candidates
        if is_filipe_technology(candidate)
    ]

    prepared = []

    for candidate in filipe_tech[:FILIPE_TECH_CANDIDATES]:
        prepared.append(
            {
                "id": candidate.get("id", ""),
                "source": candidate.get("source", ""),
                "section": candidate.get("section", ""),
                "title": candidate.get("title", ""),
                "text": candidate.get("text", ""),
            }
        )

    return prepared


def get_the_news_candidates(data):
    """
    Retorna todas as matérias do The News que devem entrar na edição.

    Nenhuma seção precisa ser cadastrada ou ativada manualmente.
    Qualquer tópico novo entra automaticamente, desde que:
    - a fonte seja The News;
    - a seção não seja BIG STORY;
    - a seção não seja ESPECIAL ELEIÇÕES 2026;
    - exista título ou texto.
    """
    all_candidates = data.get("candidates", [])

    selected = []

    for candidate in all_candidates:
        if not is_the_news(candidate):
            continue

        if not is_single_word_the_news_section(candidate):
            print(
                "Ignorada: seção do The News não possui uma única palavra: "
                f"{candidate.get('section', '')} "
                f"({candidate.get('id', '')})"
            )
            continue

        if not candidate.get("id"):
            print("Ignorada: candidato The News sem ID.")
            continue

        if not candidate.get("title") and not candidate.get("text"):
            print(
                "Ignorada: candidato The News sem título e sem texto: "
                f"{candidate.get('id', '')}"
            )
            continue

        selected.append(candidate)

    return selected


def make_story(candidate, rank, fallback=False):
    """
    Cria uma matéria usando dados originais do candidato.

    A LLM escolhe somente IDs. Título, texto, seção, fonte, URL de imagem
    e legenda são copiados diretamente de candidates.json.
    """
    source_text = candidate.get("text", "")

    return {
        "candidate_id": candidate.get("id", ""),
        "section": candidate.get("section", ""),
        "title": candidate.get("title", ""),
        "summary": source_text,
        "body": source_text,
        "source": candidate.get("source", ""),
        "original_title": candidate.get("title", ""),
        "source_text": source_text,
        "image_url": candidate.get("image_url", ""),
        "image_caption": candidate.get("image_caption", ""),
        "fallback": fallback,
        "rank": rank,
    }


def validate_filipe_selection(llm_stories, filipe_candidates):
    """
    Valida os IDs escolhidos pela LLM e garante exatamente quatro matérias.

    Se a LLM retornar menos de quatro IDs válidos, completa a seleção
    com os primeiros candidatos técnicos ainda não usados.
    """
    candidates_by_id = {
        candidate.get("id", ""): candidate
        for candidate in filipe_candidates
        if candidate.get("id")
    }

    selected = []
    used_ids = set()

    for item in llm_stories:
        candidate_id = item.get("candidate_id", "")

        if candidate_id not in candidates_by_id:
            print(
                "Ignorada: candidate_id técnico inexistente: "
                f"{candidate_id!r}"
            )
            continue

        if candidate_id in used_ids:
            print(
                "Ignorada: candidate_id técnico repetido: "
                f"{candidate_id}"
            )
            continue

        if len(selected) >= FILIPE_TECH_STORIES:
            print(
                "Ignorada: quota de Tecnologia preenchida: "
                f"{candidate_id}"
            )
            continue

        selected.append(
            candidates_by_id[candidate_id]
        )

        used_ids.add(candidate_id)

    missing = FILIPE_TECH_STORIES - len(selected)

    if missing > 0:
        for candidate in filipe_candidates:
            candidate_id = candidate.get("id", "")

            if not candidate_id or candidate_id in used_ids:
                continue

            selected.append(candidate)
            used_ids.add(candidate_id)
            missing -= 1

            print(
                "Fallback local para Tecnologia: "
                f"{candidate_id}"
            )

            if missing == 0:
                break

    if missing > 0:
        print(
            "Aviso: não há candidatos técnicos suficientes. "
            f"Faltam: {missing}"
        )

    return selected


def order_the_news_candidates(candidates):
    """
    Agrupa e ordena candidaturas do The News pela ordem das seções
    no candidates.json.

    Assim, o arquivo final preserva a sequência editorial original
    de cada edição sem precisar conhecer os tópicos previamente.
    """
    grouped = defaultdict(list)
    section_order = []

    for candidate in candidates:
        normalized_section = normalize_label(
            candidate.get("section", "")
        )

        if normalized_section not in grouped:
            section_order.append(normalized_section)

        grouped[normalized_section].append(candidate)

    ordered = []

    for section in section_order:
        ordered.extend(grouped[section])

    return ordered


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Seleciona quatro notícias de Tecnologia do Filipe Deschamps "
            "e preserva todas as matérias válidas do The News."
        )
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "Modelo Ollama. "
            f"Padrão: {DEFAULT_MODEL}"
        ),
    )

    args = parser.parse_args()

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Não encontrei {INPUT_FILE}. "
            "Rode build_candidates.py primeiro."
        )

    input_data = json.loads(
        INPUT_FILE.read_text(
            encoding="utf-8",
        )
    )

    filipe_candidates = prepare_filipe_candidates(
        input_data
    )

    the_news_candidates = get_the_news_candidates(
        input_data
    )

    if len(filipe_candidates) < FILIPE_TECH_STORIES:
        raise RuntimeError(
            "Não há candidatos técnicos suficientes do Filipe Deschamps. "
            f"Necessários: {FILIPE_TECH_STORIES}; "
            f"disponíveis: {len(filipe_candidates)}."
        )

    prompt_data = {
        "edition_date": input_data.get(
            "edition_date",
            "",
        ),
        "candidates": filipe_candidates,
    }

    response = chat(
        model=args.model,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Selecione somente os candidatos abaixo.\n\n"
                    + json.dumps(
                        prompt_data,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ],
        format=STORIES_SCHEMA,
        options={
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 180,
            "num_thread": 4,
        },
        keep_alive=0,
    )

    try:
        llm_output = json.loads(
            response.message.content
        )
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "A LLM retornou JSON inválido. "
            f"Detalhes: {error}"
        ) from error

    selected_filipe = validate_filipe_selection(
        llm_output.get("stories", []),
        filipe_candidates,
    )

    ordered_the_news = order_the_news_candidates(
        the_news_candidates
    )

    stories = []

    for candidate in selected_filipe:
        stories.append(
            make_story(
                candidate,
                rank=len(stories) + 1,
                fallback=False,
            )
        )

    for candidate in ordered_the_news:
        stories.append(
            make_story(
                candidate,
                rank=len(stories) + 1,
                fallback=False,
            )
        )

    output_data = {
        "generated_at": datetime.now().isoformat(),
        "edition_date": input_data.get(
            "edition_date",
            "",
        ),
        "model": args.model,
        "filipe_candidate_count": len(
            filipe_candidates
        ),
        "the_news_candidate_count": len(
            the_news_candidates
        ),
        "story_count": len(stories),
        "stories": stories,
    }

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_FILE.write_text(
        json.dumps(
            output_data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "Candidatos técnicos enviados à LLM: "
        f"{len(filipe_candidates)}"
    )
    print(
        "Matérias válidas do The News: "
        f"{len(the_news_candidates)}"
    )
    print(f"Matérias totais: {len(stories)}")
    print(f"Arquivo criado: {OUTPUT_FILE}")
    print()

    for story in stories:
        print(
            f"{story['rank']:02d}. "
            f"[{story['section']}] "
            f"{story['candidate_id']} — "
            f"{story['title']}"
        )


if __name__ == "__main__":
    main()