"""Download the NASA Astronomy Picture of the Day (APOD) and its metadata.

Usage:
    python nasa_apod.py
    NASA_API_KEY=your_key python nasa_apod.py

The script stores the media in output/apod/ and creates a JSON file containing
its title, explanation, date, attribution, source URL and local file path.
"""

from __future__ import annotations

import json
import mimetypes
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests

API_URL = "https://api.nasa.gov/planetary/apod"
OUTPUT_DIR = Path("output/apod")


def _extension_from_response(response: requests.Response, url: str) -> str:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    extension = mimetypes.guess_extension(content_type)
    if extension == ".jpe":
        return ".jpg"
    if extension:
        return extension

    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".jpg"


def download_apod(output_dir: Path = OUTPUT_DIR) -> dict:
    """Fetch today's APOD, download its image (or video thumbnail) and save metadata."""
    api_key = os.getenv("NASA_API_KEY", "DEMO_KEY")
    response = requests.get(
        API_URL,
        params={
            "api_key": api_key,
            "date": date.today().isoformat(),
            "thumbs": "true",
        },
        timeout=30,
    )
    response.raise_for_status()
    apod = response.json()

    media_url = apod["url"] if apod.get("media_type") == "image" else apod.get("thumbnail_url")
    if not media_url:
        raise RuntimeError(
            "A APOD de hoje é um vídeo sem miniatura disponível; nenhuma imagem foi baixada."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    image_response = requests.get(media_url, timeout=60)
    image_response.raise_for_status()

    image_path = output_dir / f"apod-{apod['date']}{_extension_from_response(image_response, media_url)}"
    image_path.write_bytes(image_response.content)

    metadata = {
        "date": apod["date"],
        "title": apod.get("title", "Astronomy Picture of the Day"),
        "explanation": apod.get("explanation", ""),
        "copyright": apod.get("copyright", "NASA"),
        "media_type": apod.get("media_type"),
        "source_url": apod.get("hdurl") or apod.get("url"),
        "download_url": media_url,
        "local_image_path": str(image_path),
    }

    metadata_path = output_dir / f"apod-{apod['date']}.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata


if __name__ == "__main__":
    try:
        apod = download_apod()
    except requests.RequestException as error:
        raise SystemExit(f"Falha ao obter a APOD: {error}") from error
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    print(f"Imagem salva em: {apod['local_image_path']}")
    print(f"Metadados salvos em: output/apod/apod-{apod['date']}.json")
    print(f"Título: {apod['title']}")
