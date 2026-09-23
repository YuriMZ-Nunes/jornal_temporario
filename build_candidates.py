#!/usr/bin/env python3

import json
import re
from pathlib import Path


INPUT_FILE = Path("output/newsletter_input.json")
OUTPUT_FILE = Path("output/candidates.json")


IMAGE_PATTERN = re.compile(
    r"""
    ^\s*
    Ver\ imagem:
    \s*
    \(
        (?P<url>https?://[^)\s]+)
    \)
    \s*
    (?:\n|\r\n)?
    \s*
    Caption:
    \s*
    (?P<caption>.*?)
    (?=
        \n\s*\n
        |
        \Z
    )
    """,
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE,
)


def clean_inline(text):
    """
    Remove Markdown e normaliza espaços para uso em título e texto.
    """
    text = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        text,
    )

    text = re.sub(
        r"[*_`#=~]+",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip(" -–—")


def is_noise(text):
    """
    Identifica chamadas comerciais, rodapés e conteúdos que não são notícia.
    """
    low = text.casefold()

    blocked = [
        "link patrocinado",
        "apresentado por",
        "publicidade",
        "quer impulsionar sua marca",
        "clique aqui se quiser ver a sua marca",
        "compartilhar essa notícia",
        "compartilhe essa notícia",
        "cancelar inscrição",
        "unsubscribe",
        "streak",
        "podcast",
    ]

    return any(
        item in low
        for item in blocked
    )


def extract_image_from_block(block):
    """
    Extrai a primeira imagem editorial e a legenda de um bloco do The News.

    Exemplo reconhecido:

    Ver imagem: (https://media.beehiiv.com/.../image.png)
    Caption: (Imagem: Ricardo Stuckert | Reprodução)

    Retorna uma tupla:
        (image_url, image_caption, text_without_image_lines)
    """
    match = IMAGE_PATTERN.search(block)

    if not match:
        return "", "", block

    image_url = match.group("url").strip()

    image_caption = clean_inline(
        match.group("caption")
    )

    clean_block = (
        block[:match.start()]
        + block[match.end():]
    )

    return (
        image_url,
        image_caption,
        clean_block,
    )


def remove_image_link_block(text):
    """
    Remove blocos opcionais usados por algumas newsletters:

    Seguir link da imagem: (https://...)
    Caption: ...
    """
    pattern = re.compile(
        r"""
        ^\s*
        Seguir\ link\ da\ imagem:
        \s*
        \(
            https?://[^)\s]+
        \)
        \s*
        (?:\n|\r\n)?
        \s*
        Caption:
        \s*
        .*?
        (?=
            \n\s*\n
            |
            \Z
        )
        """,
        re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE,
    )

    return pattern.sub("", text)

def extract_filipe_candidates(newsletter, prefix):
    """
    Extrai candidatos da newsletter Filipe Deschamps.

    Nesta versão, image_url fica vazio porque a versão text/plain
    normalmente não expõe imagens editoriais do Filipe. Em uma próxima etapa,
    poderemos preencher esse campo com imagens obtidas de text/html ou MIME.
    """
    paragraphs = [
        clean_inline(part)
        for part in re.split(
            r"\n\s*\n",
            newsletter["text"],
        )
    ]

    candidates = []

    for paragraph in paragraphs:
        low = paragraph.casefold()

        if low.startswith("curiosidade para o dia"):
            continue

        if "link patrocinado" in low:
            continue

        if "a lerian" in low:
            continue

        if len(paragraph) < 120 or is_noise(paragraph):
            continue

        if ":" not in paragraph:
            continue

        title, body = paragraph.split(
            ":",
            1,
        )

        title = clean_inline(title)
        body = clean_inline(body)

        if (
            len(title) < 15
            or len(title) > 180
            or len(body) < 80
        ):
            continue

        candidates.append(
            {
                "id": f"{prefix}-{len(candidates) + 1:02d}",
                "source": newsletter["from"],
                "section": "Tecnologia",
                "title": title,
                "text": body,
                "image_url": "",
                "image_caption": "",
            }
        )

    return candidates


def extract_thenews_candidates(newsletter, prefix):
    """
    Parser específico do formato textual do the news.

    Formato esperado:

    ###### SEÇÃO
    # TÍTULO
    Ver imagem: (URL)
    Caption: legenda opcional
    Corpo da matéria
    ———————————————————————————

    Cada candidato recebe image_url e image_caption quando houver uma imagem
    editorial no bloco.
    """
    text = newsletter["text"].replace(
        "\r\n",
        "\n",
    )

    candidates = []

    section_pattern = re.compile(
        r"(?m)^#{6}\s+(.+?)\s*$"
    )

    sections = list(
        section_pattern.finditer(text)
    )

    blocked_sections = {
        "quick takes",
        "na edição de hoje",
        "para não ficar por fora",
        "prazo de validade",
        "da semana",
        "….",
        "...",
    }

    for index, match in enumerate(sections):
        section = clean_inline(
            match.group(1)
        )

        section_low = section.casefold()

        block_start = match.end()

        block_end = (
            sections[index + 1].start()
            if index + 1 < len(sections)
            else len(text)
        )

        block = text[block_start:block_end]

        if section_low in blocked_sections:
            continue

        if "apresentado por" in section_low:
            continue

        if "patrocinado" in section_low:
            continue

        if "publicidade" in section_low:
            continue

        title_match = re.search(
            r"(?m)^#\s+(.+?)\s*$",
            block,
        )

        if not title_match:
            continue

        title = clean_inline(
            title_match.group(1)
        )

        body = block[title_match.end():]

        image_url, image_caption, body = (
            extract_image_from_block(body)
        )

        body = remove_image_link_block(body)

        body = re.sub(
            r"==\[~_?\*{0,2}compartilhar.*",
            "",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        body = re.sub(
            r"\*\*\[\s*compartilhe\s+essa\s+notícia.*",
            "",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        body = clean_inline(body)

        if len(title) < 12 or len(body) < 120:
            continue

        if is_noise(title) or is_noise(body):
            continue

        candidates.append(
            {
                "id": f"{prefix}-{len(candidates) + 1:02d}",
                "source": newsletter["from"],
                "section": section.upper(),
                "title": title,
                "text": body,
                "image_url": image_url,
                "image_caption": image_caption,
            }
        )

    return candidates


def extract_candidates(newsletters):
    """
    Escolhe o parser de acordo com a origem da newsletter.
    """
    candidates = []

    for newsletter_index, newsletter in enumerate(
        newsletters,
        start=1,
    ):
        source = newsletter.get(
            "from",
            "",
        ).casefold()

        if "the news" in source:
            extracted = extract_thenews_candidates(
                newsletter,
                prefix=f"TN{newsletter_index}",
            )
        else:
            extracted = extract_filipe_candidates(
                newsletter,
                prefix=f"FD{newsletter_index}",
            )

        candidates.extend(extracted)

    return candidates


def main():
    data = json.loads(
        INPUT_FILE.read_text(
            encoding="utf-8",
        )
    )

    candidates = extract_candidates(
        data.get("newsletters", [])
    )

    output = {
        "edition_date": data.get(
            "edition_date",
            data.get("generated_at", "")[:10],
        ),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Candidatos extraídos: {len(candidates)}")
    print(f"Arquivo criado: {OUTPUT_FILE}")
    print()

    for candidate in candidates:
        image_status = (
            "com imagem"
            if candidate.get("image_url")
            else "sem imagem"
        )

        print(
            f"{candidate['id']} | "
            f"{candidate['section']} | "
            f"{image_status} | "
            f"{candidate['title']}"
        )


if __name__ == "__main__":
    main()