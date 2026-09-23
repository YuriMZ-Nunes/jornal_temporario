#!/usr/bin/env python3

import base64
import json
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo
from email.utils import parseaddr
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

LABEL_NAME = "News"
MAX_MESSAGES = 5
TIMEZONE = ZoneInfo("America/Sao_Paulo")


def get_google_credentials():
    token_path = Path("token.json")
    credentials_path = Path("credentials.json")
    credentials = None

    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            token_path,
            GOOGLE_SCOPES,
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_path,
            GOOGLE_SCOPES,
        )
        credentials = flow.run_local_server(port=0)
        token_path.write_text(credentials.to_json())

    return credentials


def decode_base64url(data):
    """Decodifica body.data retornado pelo Gmail."""
    if not data:
        return ""

    padding = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(data + padding)
    return raw.decode("utf-8", errors="replace")


def find_mime_parts(part):
    """Retorna lista de pares (mime_type, text) encontrados no payload MIME."""
    found = []

    body_data = part.get("body", {}).get("data")
    mime_type = part.get("mimeType", "")

    if body_data:
        found.append(
            {
                "mime_type": mime_type,
                "content": decode_base64url(body_data),
            }
        )

    for child in part.get("parts", []):
        found.extend(find_mime_parts(child))

    return found


def get_best_plain_text(message):
    """
    Prefere text/plain. Caso não exista, devolve string vazia por enquanto.
    O fallback HTML entra depois.
    """
    parts = find_mime_parts(message.get("payload", {}))

    for part in parts:
        if part["mime_type"] == "text/plain":
            return part["content"]

    return ""

def get_best_html(message):
    """
    Retorna a parte text/html do e-mail, quando ela existir.
    """
    parts = find_mime_parts(message.get("payload", {}))

    for part in parts:
        if part["mime_type"] == "text/html":
            return part["content"]

    return ""

def get_header(message, name):
    headers = message.get("payload", {}).get("headers", [])

    for header in headers:
        if header["name"].casefold() == name.casefold():
            return header["value"]

    return ""


def clean_text(text):
    """Remove excesso de espaços e linhas vazias."""
    text = text.replace("\u200c", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_obvious_noise(text):
    """Remove chamadas típicas de rodapé, propaganda e gestão de assinatura."""
    noise_patterns = [
        r"(?is)cancelar inscrição.*",
        r"(?is)unsubscribe.*",
        r"(?is)manage preferences.*",
        r"(?is)seguir no instagram.*",
        r"(?is)todos os direitos reservados.*",
        r"(?is)clique aqui para.*patroc",
    ]

    for pattern in noise_patterns:
        text = re.sub(pattern, "", text)

    return clean_text(text)

def remove_sponsored_sections(text):
    """Remove blocos explicitamente marcados como publicidade/patrocínio."""
    patterns = [
        r"(?is)######\s+APRESENTADO POR .*?(?=———————————————————————————|$)",
        r"(?is)Link Patrocinado.*$",
    ]

    for pattern in patterns:
        text = re.sub(pattern, "", text)

    return clean_text(text)


def get_label_id(service, label_name):
    response = service.users().labels().list(userId="me").execute()

    for label in response.get("labels", []):
        if label["name"].strip().casefold() == label_name.strip().casefold():
            return label["id"]

    raise ValueError(f'Não encontrei o marcador "{label_name}".')


def parse_sender(header_value):
    name, address = parseaddr(header_value)
    return name or address or header_value


def main():
    credentials = get_google_credentials()
    gmail = build("gmail", "v1", credentials=credentials)

    label_id = get_label_id(gmail, LABEL_NAME)

    today = datetime.now(TIMEZONE).date()

    start_of_today = datetime.combine(
        today,
        time.min,
        tzinfo=TIMEZONE,
    )

    # after: é exclusivo; a margem evita perder um e-mail na virada do dia.
    after = int(start_of_today.timestamp()) - 60

    response = gmail.users().messages().list(
        userId="me",
        labelIds=[label_id],
        q=f"after:{after}",
        maxResults=MAX_MESSAGES,
    ).execute()

    collected = []

    for message_ref in response.get("messages", []):
        message = gmail.users().messages().get(
            userId="me",
            id=message_ref["id"],
            format="full",
        ).execute()

        plain_text = get_best_plain_text(message)
        html_text = get_best_html(message)
        plain_text = remove_obvious_noise(plain_text)
        plain_text = remove_sponsored_sections(plain_text)

        collected.append(
            {
                "id": message["id"],
                "from": parse_sender(get_header(message, "From")),
                "subject": get_header(message, "Subject"),
                "date": get_header(message, "Date"),
                "text": plain_text[:30000],
                "html": html_text[:500000],
            }
        )

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "newsletter_input.json"
    output_file.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(TIMEZONE).isoformat(),
                "edition_date": today.isoformat(),
                "label": LABEL_NAME,
                "newsletter_count": len(collected),
                "newsletters": collected,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print(f"Arquivo criado: {output_file}")
    print(f"Data da edição: {today.isoformat()}")
    print(f"Newsletters encontradas: {len(collected)}")

    for item in collected:
        print()
        print("=" * 80)
        print(item["from"])
        print(item["subject"])
        print(f"{len(item['text'])} caracteres limpos")
        print("=" * 80)
        print(item["text"][:800])


if __name__ == "__main__":
    main()