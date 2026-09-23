#!/usr/bin/env python3

import hashlib
import json
import mimetypes
import shutil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from io import BytesIO
from PIL import Image


STORIES_FILE = Path("output/stories.json")
IMAGES_DIR = Path("output/images")
OUTPUT_FILE = Path("output/images.json")

TIMEOUT_SECONDS = 20
MAX_IMAGE_BYTES = 12 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}

CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
}

def convert_avif_to_png(image_bytes):
    """
    Converte bytes AVIF para PNG para uso no ReportLab.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")

        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

def load_json(path):
    """
    Lê e decodifica um arquivo JSON UTF-8.
    """
    return json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )


def get_extension(content_type, image_url):
    """
    Escolhe a extensão do arquivo usando primeiro o Content-Type
    recebido no HTTP e, como fallback, o sufixo da URL.
    """
    content_type = (
        (content_type or "")
        .split(";", 1)[0]
        .strip()
        .casefold()
    )

    if content_type in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[content_type]

    url_path = urlparse(image_url).path
    url_suffix = Path(url_path).suffix.casefold()

    if url_suffix in ALLOWED_EXTENSIONS:
        if url_suffix == ".jpeg":
            return ".jpg"

        return url_suffix

    guessed_extension = mimetypes.guess_extension(
        content_type
    )

    if guessed_extension:
        guessed_extension = guessed_extension.casefold()

        if guessed_extension in ALLOWED_EXTENSIONS:
            if guessed_extension == ".jpeg":
                return ".jpg"

            return guessed_extension

    return ".jpg"


def build_filename(candidate_id, image_url, extension):
    """
    Cria um nome estável e único por candidato + URL.

    Exemplo:
        TN2-01-5c9b0ac942d7.png
    """
    url_hash = hashlib.sha256(
        image_url.encode("utf-8")
    ).hexdigest()[:12]

    safe_candidate_id = "".join(
        char
        for char in candidate_id
        if char.isalnum() or char in {"-", "_"}
    )

    if not safe_candidate_id:
        safe_candidate_id = "imagem"

    return (
        f"{safe_candidate_id}-"
        f"{url_hash}"
        f"{extension}"
    )


def is_valid_local_file(path):
    """
    Confirma que um arquivo existe e não está vazio.
    """
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def fetch_image(image_url):
    """
    Baixa a imagem e retorna:

        (bytes, content_type, final_url)

    O Request permite incluir User-Agent e Accept; alguns CDNs recusam
    requisições sem esses cabeçalhos.
    """
    request = Request(
        image_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/123.0 Safari/537.36 "
                "JornalPessoal/1.0"
            ),
            "Accept": (
                "image/webp,image/png,image/jpeg,"
                "image/gif,image/*;q=0.8,*/*;q=0.5"
            ),
        },
    )

    with urlopen(
        request,
        timeout=TIMEOUT_SECONDS,
    ) as response:
        content_type = (
            response.headers.get("Content-Type", "")
            .split(";", 1)[0]
            .strip()
            .casefold()
        )

        content_length = response.headers.get(
            "Content-Length"
        )

        if (
            content_length
            and int(content_length) > MAX_IMAGE_BYTES
        ):
            raise ValueError(
                "Imagem excede o limite de "
                f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB."
            )

        if (
            content_type
            and content_type not in ALLOWED_CONTENT_TYPES
        ):
            raise ValueError(
                "Resposta não parece ser uma imagem suportada: "
                f"{content_type!r}"
            )

        image_bytes = response.read(
            MAX_IMAGE_BYTES + 1
        )

        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError(
                "Imagem excede o limite de "
                f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB."
            )

        if not image_bytes:
            raise ValueError(
                "O servidor retornou uma imagem vazia."
            )

        final_url = response.geturl()

    return image_bytes, content_type, final_url


def reuse_existing_image(
    previous_index,
    candidate_id,
    image_url,
):
    """
    Reutiliza um arquivo local previamente baixado quando a URL não mudou.
    """
    previous = previous_index.get(candidate_id)

    if not previous:
        return None

    if previous.get("image_url") != image_url:
        return None

    image_file = previous.get("image_file", "")

    if not image_file:
        return None

    image_path = Path(image_file)

    if not is_valid_local_file(image_path):
        return None

    return {
        "candidate_id": candidate_id,
        "image_url": image_url,
        "final_url": previous.get(
            "final_url",
            image_url,
        ),
        "image_file": str(image_path),
        "content_type": previous.get(
            "content_type",
            "",
        ),
        "bytes": image_path.stat().st_size,
        "cached": True,
    }


def load_previous_index():
    """
    Lê images.json anterior para permitir cache por candidate_id + URL.
    """
    if not OUTPUT_FILE.exists():
        return {}

    try:
        data = load_json(OUTPUT_FILE)
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {}

    return {
        item.get("candidate_id", ""): item
        for item in data.get("images", [])
        if item.get("candidate_id")
    }


def main():
    if not STORIES_FILE.exists():
        raise FileNotFoundError(
            f"Não encontrei {STORIES_FILE}. "
            "Rode editor_llm.py primeiro."
        )

    stories_data = load_json(STORIES_FILE)
    stories = stories_data.get("stories", [])

    if not stories:
        raise RuntimeError(
            "stories.json foi encontrado, mas não contém matérias."
        )

    IMAGES_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    previous_index = load_previous_index()

    downloaded_images = []
    without_image = 0
    failed_images = 0
    cached_images = 0
    new_images = 0

    for story in stories:
        candidate_id = str(
            story.get("candidate_id", "")
        ).strip()

        image_url = str(
            story.get("image_url", "")
        ).strip()

        image_caption = str(
            story.get("image_caption", "")
        ).strip()

        if not candidate_id:
            print(
                "Ignorada: matéria sem candidate_id."
            )
            continue

        if not image_url:
            without_image += 1

            print(
                f"Sem imagem: {candidate_id}"
            )

            continue

        cached_item = reuse_existing_image(
            previous_index,
            candidate_id,
            image_url,
        )

        if cached_item:
            cached_item["image_caption"] = image_caption

            downloaded_images.append(cached_item)
            cached_images += 1

            print(
                f"Imagem em cache: {candidate_id} -> "
                f"{cached_item['image_file']}"
            )

            continue

        try:
            image_bytes, content_type, final_url = fetch_image(
                image_url
            )

            if content_type == "image/avif":
                image_bytes = convert_avif_to_png(image_bytes)
                content_type = "image/png"

            extension = get_extension(
                content_type,
                final_url or image_url,
            )

            filename = build_filename(
                candidate_id,
                image_url,
                extension,
            )

            image_path = IMAGES_DIR / filename

            image_path.write_bytes(image_bytes)

            if not is_valid_local_file(image_path):
                raise RuntimeError(
                    "A imagem foi salva, mas o arquivo está vazio."
                )

            downloaded_images.append(
                {
                    "candidate_id": candidate_id,
                    "image_url": image_url,
                    "final_url": final_url,
                    "image_file": str(image_path),
                    "image_caption": image_caption,
                    "content_type": content_type,
                    "bytes": len(image_bytes),
                    "cached": False,
                }
            )

            new_images += 1

            print(
                f"Imagem salva: {candidate_id} -> "
                f"{image_path}"
            )

        except HTTPError as error:
            failed_images += 1

            print(
                f"Falha HTTP ao baixar {candidate_id}: "
                f"{error.code} {error.reason}"
            )

        except URLError as error:
            failed_images += 1

            print(
                f"Falha de rede ao baixar {candidate_id}: "
                f"{error.reason}"
            )

        except (
            OSError,
            ValueError,
            RuntimeError,
        ) as error:
            failed_images += 1

            print(
                f"Falha ao baixar imagem de "
                f"{candidate_id}: {error}"
            )

    output_data = {
        "generated_from": str(STORIES_FILE),
        "story_count": len(stories),
        "image_count": len(downloaded_images),
        "cached_count": cached_images,
        "downloaded_count": new_images,
        "without_image_count": without_image,
        "failed_count": failed_images,
        "images": downloaded_images,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output_data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Arquivo criado: {OUTPUT_FILE}")
    print(f"Matérias processadas: {len(stories)}")
    print(f"Imagens disponíveis: {len(downloaded_images)}")
    print(f"Imagens novas: {new_images}")
    print(f"Imagens em cache: {cached_images}")
    print(f"Matérias sem imagem: {without_image}")
    print(f"Falhas ao baixar: {failed_images}")


if __name__ == "__main__":
    main()