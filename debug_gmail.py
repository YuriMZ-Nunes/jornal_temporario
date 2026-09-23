import base64
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
    """Decodifica conteúdo MIME que veio do Gmail."""
    if not data:
        return ""

    padding = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(data + padding)

    return raw.decode("utf-8", errors="replace")


def walk_mime_parts(part):
    """
    Percorre recursivamente partes MIME e devolve pares:
    (tipo MIME, conteúdo decodificado).
    """
    parts_found = []

    mime_type = part.get("mimeType", "")
    body_data = part.get("body", {}).get("data")

    if body_data:
        parts_found.append(
            (mime_type, decode_base64url(body_data))
        )

    for child in part.get("parts", []):
        parts_found.extend(walk_mime_parts(child))

    return parts_found


def get_label_id(service, label_name):
    response = service.users().labels().list(userId="me").execute()

    for label in response.get("labels", []):
        if label["name"].strip().casefold() == label_name.strip().casefold():
            return label["id"]

    raise ValueError(f'Label "{label_name}" não encontrado.')


def main():
    credentials = get_google_credentials()
    gmail = build("gmail", "v1", credentials=credentials)

    label_id = get_label_id(gmail, LABEL_NAME)

    response = gmail.users().messages().list(
        userId="me",
        labelIds=[label_id],
        maxResults=2,
    ).execute()

    messages = response.get("messages", [])

    if not messages:
        print(f'Nenhuma mensagem encontrada no label "{LABEL_NAME}".')
        return

    for message_ref in messages:
        message = gmail.users().messages().get(
            userId="me",
            id=message_ref["id"],
            format="full",
        ).execute()

        headers = message.get("payload", {}).get("headers", [])
        subject = next(
            (
                header["value"]
                for header in headers
                if header["name"].casefold() == "subject"
            ),
            "(sem assunto)",
        )

        print("\n" + "=" * 88)
        print("ASSUNTO:", subject)
        print("=" * 88)

        mime_parts = walk_mime_parts(message.get("payload", {}))

        for mime_type, content in mime_parts:
            print(f"\n--- MIME: {mime_type} | {len(content)} caracteres ---\n")
            print(content[:5000])

        print("\n[FIM DA MENSAGEM]\n")


if __name__ == "__main__":
    main()