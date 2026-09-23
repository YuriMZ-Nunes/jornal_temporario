#!/usr/bin/env python3

import argparse
import base64
import hashlib
import random
import re
import json
from datetime import date, datetime, time, timedelta
from email.utils import parseaddr
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 1.25 * cm

PAPER = colors.white
INK = colors.HexColor("#1A1712")
MUTED_INK = colors.HexColor("#51493E")
RULE = colors.HexColor("#574F43")
LIGHT_FILL = colors.HexColor("#F7F7F7")

TIMEZONE = ZoneInfo("America/Sao_Paulo")
NEWSLETTER_LABEL = "News"
MAX_NEWSLETTERS = 4
MAX_AGENDA_EVENTS = 4
MAX_TASKS = 6
STORIES_FILE = Path("output/stories.json")
MAX_WEEK_EVENTS = 14
MAX_COVER_SUMMARY = 520

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_google_credentials():
    """Lê ou cria credenciais OAuth locais para os serviços Google usados."""
    token_path = Path("token.json")
    credentials_path = Path("credentials.json")
    credentials = None

    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not credentials_path.exists():
            raise FileNotFoundError(
                "Não encontrei credentials.json na pasta do projeto."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_path,
            GOOGLE_SCOPES,
        )
        credentials = flow.run_local_server(port=0)
        token_path.write_text(credentials.to_json())

    return credentials


def get_calendar_service(credentials):
    return build("calendar", "v3", credentials=credentials)


def get_tasks_service(credentials):
    return build("tasks", "v1", credentials=credentials)


def get_gmail_service(credentials):
    return build("gmail", "v1", credentials=credentials)


def event_start_datetime(event):
    start = event["start"]

    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"]).astimezone(TIMEZONE)

    return datetime.combine(
        date.fromisoformat(start["date"]),
        time.min,
        tzinfo=TIMEZONE,
    )


def format_calendar_event(event):
    title = event.get("summary", "(Sem título)")
    start = event["start"]

    if "date" in start:
        return {"time": "DIA TODO", "title": title}

    start_dt = event_start_datetime(event)
    return {"time": start_dt.strftime("%H:%M"), "title": title}


def get_events_for_day(service, target_day):
    start = datetime.combine(target_day, time.min, tzinfo=TIMEZONE)
    end = start + timedelta(days=1)

    response = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()

    return response.get("items", [])


def task_is_for_day(task, target_day):
    due = task.get("due")
    return bool(due) and date.fromisoformat(due[:10]) == target_day


def get_tasks_for_day(service, target_day):
    task_lists = service.tasklists().list(maxResults=100).execute()
    tasks_for_day = []

    for task_list in task_lists.get("items", []):
        response = service.tasks().list(
            tasklist=task_list["id"],
            showCompleted=False,
            showHidden=False,
            maxResults=100,
        ).execute()

        for task in response.get("items", []):
            if task_is_for_day(task, target_day):
                tasks_for_day.append(task)

    return tasks_for_day


def get_gmail_label_id(service, label_name):
    response = service.users().labels().list(userId="me").execute()

    for label in response.get("labels", []):
        if label["name"].strip().casefold() == label_name.strip().casefold():
            return label["id"]

    raise ValueError(
        f'Não encontrei o marcador "{label_name}" no Gmail. '
        "Crie-o no Gmail ou altere NEWSLETTER_LABEL no início do arquivo."
    )


def get_message_header(message, header_name):
    headers = message.get("payload", {}).get("headers", [])

    for header in headers:
        if header["name"].casefold() == header_name.casefold():
            return header["value"]

    return ""

def story_height(story, width, styles):
    """
    Calcula a altura aproximada necessária para uma matéria na página interna.
    """
    section = clean_text(
        story.get("section", "Sem seção"),
        48,
    )

    title = clean_text(
        story.get("title", "Sem título"),
    )

    source_text = clean_text(
        story.get("source_text")
        or story.get("body")
        or story.get("summary", "")
    )

    header_height = 0.68 * cm

    title_paragraph = Paragraph(
        title,
        styles["article_headline"],
    )

    _, title_height = title_paragraph.wrap(
        width,
        PAGE_HEIGHT,
    )

    body_paragraph = Paragraph(
        source_text,
        styles["article_body"],
    )

    _, body_height = body_paragraph.wrap(
        width,
        PAGE_HEIGHT,
    )

    return (
        header_height
        + title_height
        + 0.16 * cm
        + body_height
        + 0.72 * cm
    )

def clean_text(text, max_length=None):
    text = " ".join((text or "").split())
    text = re.sub(r"\s+", " ", text).strip()

    if max_length and len(text) > max_length:
        return text[: max_length - 1].rstrip() + "…"

    return text

def get_stories():
    """
    Lê as matérias já selecionadas por editor_llm.py.

    Não reescreve título, seção, fonte nem texto.
    """
    if not STORIES_FILE.exists():
        raise FileNotFoundError(
            f"Não encontrei {STORIES_FILE}. "
            "Rode editor_llm.py antes de gerar o PDF."
        )

    data = json.loads(
        STORIES_FILE.read_text(
            encoding="utf-8",
        )
    )

    stories = data.get("stories", [])

    if not stories:
        raise RuntimeError(
            "stories.json foi encontrado, mas não contém matérias."
        )

    return stories

def get_stories():
    """
    Lê as matérias selecionadas em output/stories.json.

    O arquivo deve ser gerado antes por editor_llm.py.
    Títulos, seções, fontes e textos são preservados.
    """
    if not STORIES_FILE.exists():
        raise FileNotFoundError(
            f"Não encontrei {STORIES_FILE}. "
            "Rode editor_llm.py antes de gerar o PDF."
        )

    data = json.loads(
        STORIES_FILE.read_text(
            encoding="utf-8",
        )
    )

    stories = data.get("stories", [])

    if not stories:
        raise RuntimeError(
            "stories.json existe, mas não possui matérias."
        )

    return stories

def sender_name(sender):
    name, address = parseaddr(sender)
    return clean_text(name or address or sender, 48)


def get_recent_newsletters(service, label_name=NEWSLETTER_LABEL, max_messages=MAX_NEWSLETTERS):
    """Busca as mensagens mais recentes que possuem o marcador escolhido."""
    label_id = get_gmail_label_id(service, label_name)

    today = datetime.now(TIMEZONE).date()
    start_of_today = datetime.combine(
        today,
        time.min,
        tzinfo=TIMEZONE,
    )
    after = int(start_of_today.timestamp()) - 60

    response = service.users().messages().list(
        userId="me",
        labelIds=[label_id],
        q=f"after:{after}",
        maxResults=max_messages,
    ).execute()

    newsletters = []


    for message_ref in response.get("messages", []):
        message = service.users().messages().get(
            userId="me",
            id=message_ref["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()

        print(message)

        sender = get_message_header(message, "From")
        subject = get_message_header(message, "Subject")
        snippet = clean_text(message.get("snippet", ""), 260)

        newsletters.append(
            {
                "id": message["id"],
                "source": sender_name(sender),
                "subject": clean_text(subject or "(Sem assunto)", 120),
                "snippet": snippet,
            }
        )

    return newsletters


def daily_rng(day):
    seed_text = f"jornal-pessoal:sudoku:{day.isoformat()}"
    seed = int(hashlib.sha256(seed_text.encode()).hexdigest(), 16)
    return random.Random(seed)


def valid(grid, row, col, number):
    if any(grid[row][x] == number for x in range(9)):
        return False

    if any(grid[y][col] == number for y in range(9)):
        return False

    box_row = (row // 3) * 3
    box_col = (col // 3) * 3

    for y in range(box_row, box_row + 3):
        for x in range(box_col, box_col + 3):
            if grid[y][x] == number:
                return False

    return True


def solve_grid(grid, rng):
    empty_cell = None

    for row in range(9):
        for col in range(9):
            if grid[row][col] == 0:
                empty_cell = (row, col)
                break
        if empty_cell:
            break

    if empty_cell is None:
        return True

    row, col = empty_cell
    candidates = list(range(1, 10))
    rng.shuffle(candidates)

    for number in candidates:
        if valid(grid, row, col, number):
            grid[row][col] = number
            if solve_grid(grid, rng):
                return True
            grid[row][col] = 0

    return False


def generate_sudoku(day, blanks=48):
    rng = daily_rng(day)
    solution = [[0 for _ in range(9)] for _ in range(9)]
    solve_grid(solution, rng)

    puzzle = [row[:] for row in solution]
    positions = [(row, col) for row in range(9) for col in range(9)]
    rng.shuffle(positions)

    for row, col in positions[:blanks]:
        puzzle[row][col] = 0

    return puzzle, solution


def draw_rule(c, y, x1=MARGIN, x2=PAGE_WIDTH - MARGIN, width=0.8):
    c.setStrokeColor(RULE)
    c.setLineWidth(width)
    c.line(x1, y, x2, y)


def draw_wrapped_paragraph(c, text, x, y_top, width, style):
    paragraph = Paragraph(text, style)
    _, height = paragraph.wrap(width, PAGE_HEIGHT)
    paragraph.drawOn(c, x, y_top - height)
    return y_top - height


def draw_section_title(c, title, x, y, width):
    c.setFillColor(INK)
    c.setFont("Times-Bold", 10)
    c.drawString(x, y, title.upper())
    draw_rule(c, y - 0.12 * cm, x1=x, x2=x + width, width=0.5)
    return y - 0.42 * cm


def draw_sudoku(c, puzzle, x, y_top, size):
    cell = size / 9
    y = y_top - size

    c.setFillColor(LIGHT_FILL)
    c.rect(x, y, size, size, fill=1, stroke=0)
    c.setStrokeColor(INK)

    for index in range(10):
        line_width = 1.8 if index % 3 == 0 else 0.45
        c.setLineWidth(line_width)
        c.line(x + index * cell, y, x + index * cell, y + size)
        c.line(x, y + index * cell, x + size, y + index * cell)

    font_name = "Times-Bold"
    font_size = 18
    c.setFillColor(INK)
    c.setFont(font_name, font_size)

    for row in range(9):
        for col in range(9):
            value = puzzle[row][col]
            if value == 0:
                continue

            center_x = x + (col + 0.5) * cell
            center_y = y + (8 - row + 0.5) * cell
            baseline_y = center_y - font_size * 0.35
            c.drawCentredString(center_x, baseline_y, str(value))


def draw_agenda_rows(c, events, x, y_top, width, max_items=MAX_AGENDA_EVENTS):
    y = y_top

    if not events:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 8)
        c.drawString(x, y, "Nenhum compromisso.")
        return y - 0.55 * cm

    for event in events[:max_items]:
        c.setFillColor(INK)
        c.setFont("Times-Bold", 8.3)
        c.drawString(x, y, event["time"])

        event_style = ParagraphStyle(
            "AgendaEvent",
            fontName="Times-Roman",
            fontSize=8.3,
            leading=9.8,
            textColor=INK,
        )
        y_after = draw_wrapped_paragraph(
            c,
            event["title"],
            x + 1.55 * cm,
            y + 0.11 * cm,
            width - 1.55 * cm,
            event_style,
        )
        y = min(y - 0.48 * cm, y_after - 0.16 * cm)

    if len(events) > max_items:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 7.4)
        c.drawString(x, y, f"+ {len(events) - max_items} outro(s) compromisso(s)")
        y -= 0.42 * cm

    return y


def draw_task_rows(c, tasks, x, y_top, width, max_items=MAX_TASKS):
    y = y_top

    if not tasks:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 8)
        c.drawString(x, y, "Nenhuma tarefa agendada.")
        return y - 0.55 * cm

    task_style = ParagraphStyle(
        "Task",
        fontName="Times-Roman",
        fontSize=8.7,
        leading=10,
        textColor=INK,
    )

    for task in tasks[:max_items]:
        box = 0.30 * cm
        c.setStrokeColor(INK)
        c.setLineWidth(0.75)
        c.rect(x, y - 0.23 * cm, box, box, fill=0, stroke=1)

        y_after = draw_wrapped_paragraph(
            c,
            task,
            x + 0.52 * cm,
            y + 0.10 * cm,
            width - 0.52 * cm,
            task_style,
        )
        y = min(y - 0.48 * cm, y_after - 0.14 * cm)

    if len(tasks) > max_items:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 7.4)
        c.drawString(x, y, f"+ {len(tasks) - max_items} outra(s) tarefa(s)")
        y -= 0.42 * cm

    return y

def is_filipe_technology_story(story):
    source = clean_text(
        story.get("source", "")
    ).casefold()

    section = clean_text(
        story.get("section", "")
    ).casefold()

    return (
        "filipe deschamps" in source
        and section == "tecnologia"
    )

def draw_cover_story(c, story, x, y_top, width, styles):
    """
    Desenha a única notícia principal da capa.
    """
    section = clean_text(
        story.get("section", "Destaque"),
        48,
    )

    title = clean_text(
        story.get("title", "Sem título"),
    )

    source = clean_text(
        story.get("source", "Fonte desconhecida"),
        60,
    )

    summary = clean_text(
        story.get("summary", ""),
        MAX_COVER_SUMMARY,
    )

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Bold", 8)
    c.drawString(
        x,
        y_top,
        section.upper(),
    )

    c.setFont("Times-Roman", 7.5)
    c.drawRightString(
        x + width,
        y_top,
        source.upper(),
    )

    y = y_top - 0.30 * cm

    y = draw_wrapped_paragraph(
        c,
        title,
        x,
        y,
        width,
        styles["cover_headline"],
    )

    y -= 0.18 * cm

    if summary:
        y = draw_wrapped_paragraph(
            c,
            summary,
            x,
            y,
            width,
            styles["cover_body"],
        )

    return y - 0.20 * cm

def draw_week_agenda(c, events, x, y_top, width, styles):
    """
    Mostra compromissos dos próximos sete dias em uma faixa horizontal.

    Eventos são agrupados por data e desenhados em até duas colunas.
    """
    y = draw_section_title(
        c,
        "Agenda da semana",
        x,
        y_top,
        width,
    )

    if not events:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 8.5)
        c.drawString(
            x,
            y,
            "Nenhum compromisso nos próximos sete dias.",
        )
        return y - 0.55 * cm

    column_gap = 0.45 * cm
    column_width = (width - column_gap) / 2

    left_x = x
    right_x = x + column_width + column_gap

    left_y = y
    right_y = y

    events_by_day = {}

    for event in events[:MAX_WEEK_EVENTS]:
        event_day = event_start_datetime(event).date()

        if event_day not in events_by_day:
            events_by_day[event_day] = []

        events_by_day[event_day].append(
            format_calendar_event(event)
        )

    for index, event_day in enumerate(sorted(events_by_day)):
        target_x = left_x if index % 2 == 0 else right_x
        target_y = left_y if index % 2 == 0 else right_y

        weekday_names = [
            "segunda",
            "terça",
            "quarta",
            "quinta",
            "sexta",
            "sábado",
            "domingo",
        ]

        day_label = (
            f"{weekday_names[event_day.weekday()].upper()} "
            f"• {event_day.strftime('%d/%m')}"
        )

        c.setFillColor(MUTED_INK)
        c.setFont("Times-Bold", 7.2)
        c.drawString(
            target_x,
            target_y,
            day_label,
        )

        target_y -= 0.18 * cm

        agenda_style = ParagraphStyle(
            "WeekAgenda",
            fontName="Times-Roman",
            fontSize=7.8,
            leading=9.2,
            textColor=INK,
        )

        for event in events_by_day[event_day]:
            text = (
                f"<b>{event['time']}</b> "
                f"{clean_text(event['title'], 110)}"
            )

            target_y = draw_wrapped_paragraph(
                c,
                text,
                target_x,
                target_y,
                column_width,
                agenda_style,
            )

            target_y -= 0.11 * cm

        if index % 2 == 0:
            left_y = target_y - 0.18 * cm
        else:
            right_y = target_y - 0.18 * cm

    return min(left_y, right_y)

def draw_news_column(c, newsletters, x, y_top, width, y_bottom, styles):
    y = draw_section_title(c, "Destaques", x, y_top, width)

    if not newsletters:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 9)
        c.drawString(x, y, "Nenhuma leitura selecionada para esta edição.")
        return y

    lead = newsletters[0]
    c.setFillColor(MUTED_INK)
    c.setFont("Times-Bold", 7.5)
    c.drawString(x, y, lead["source"].upper())
    y -= 0.22 * cm

    y = draw_wrapped_paragraph(
        c,
        lead["subject"],
        x,
        y,
        width,
        styles["lead_headline"],
    )
    y -= 0.12 * cm

    if lead["snippet"]:
        y = draw_wrapped_paragraph(
            c,
            lead["snippet"],
            x,
            y,
            width,
            styles["lead_body"],
        )
        y -= 0.25 * cm

    remaining = newsletters[1:]
    if remaining and y > y_bottom + 1.2 * cm:
        draw_rule(c, y, x1=x, x2=x + width, width=0.45)
        y -= 0.30 * cm
        y = draw_section_title(c, "Outras leituras", x, y, width)

    for newsletter in remaining:
        if y < y_bottom + 1.35 * cm:
            break

        c.setFillColor(MUTED_INK)
        c.setFont("Times-Bold", 7.2)
        c.drawString(x, y, newsletter["source"].upper())
        y -= 0.20 * cm

        y = draw_wrapped_paragraph(
            c,
            newsletter["subject"],
            x,
            y,
            width,
            styles["secondary_headline"],
        )
        y -= 0.08 * cm

        if newsletter["snippet"]:
            y = draw_wrapped_paragraph(
                c,
                newsletter["snippet"],
                x,
                y,
                width,
                styles["secondary_body"],
            )

        y -= 0.20 * cm
        if y > y_bottom + 0.9 * cm:
            draw_rule(c, y, x1=x, x2=x + width, width=0.3)
            y -= 0.24 * cm

    return y


def build_pdf(edition, newsletters_label=NEWSLETTER_LABEL):
    today = date.today()
    now = datetime.now(TIMEZONE)

    credentials = get_google_credentials()
    calendar_service = get_calendar_service(credentials)
    tasks_service = get_tasks_service(credentials)
    gmail_service = get_gmail_service(credentials)

    events_today = get_events_for_day(calendar_service, today)
    events_tomorrow = get_events_for_day(calendar_service, today + timedelta(days=1))
    tasks_today = get_tasks_for_day(tasks_service, today)
    newsletters = get_recent_newsletters(gmail_service)

    agenda_hoje = [format_calendar_event(event) for event in events_today]
    agenda_amanha = [format_calendar_event(event) for event in events_tomorrow]
    tasks_do_dia = [task.get("title", "(Sem título)") for task in tasks_today]

    output_dir = Path("output") / str(today.year) / f"{today.month:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = output_dir / f"{today.isoformat()}-{edition}.pdf"
    c = canvas.Canvas(str(filename), pagesize=A4)
    c.setTitle(f"O Jornal do Yuri — {today.isoformat()}")

    styles = {
        "lead_headline": ParagraphStyle(
            "LeadHeadline",
            fontName="Times-Bold",
            fontSize=15.5,
            leading=17.5,
            textColor=INK,
        ),
        "lead_body": ParagraphStyle(
            "LeadBody",
            fontName="Times-Roman",
            fontSize=9.1,
            leading=11.6,
            textColor=INK,
        ),
        "secondary_headline": ParagraphStyle(
            "SecondaryHeadline",
            fontName="Times-Bold",
            fontSize=10.4,
            leading=12,
            textColor=INK,
        ),
        "secondary_body": ParagraphStyle(
            "SecondaryBody",
            fontName="Times-Roman",
            fontSize=8.2,
            leading=10.1,
            textColor=MUTED_INK,
        ),
    }

    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    c.setFillColor(INK)
    c.setFont("Times-Bold", 8)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 0.58 * cm,
        "EDIÇÃO PESSOAL • SÃO PAULO • USO PRIVADO",
    )
    draw_rule(c, PAGE_HEIGHT - 0.77 * cm, width=1.0)

    c.setFont("Times-Bold", 24)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 1.48 * cm,
        "O JORNAL DO YURI",
    )

    c.setFont("Times-Italic", 8.5)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 1.84 * cm,
        "São Paulo • edição pessoal diária",
    )
    draw_rule(c, PAGE_HEIGHT - 2.04 * cm, width=1.0)

    edition_label = "EDIÇÃO DA MANHÃ" if edition == "manha" else "EDIÇÃO DA NOITE"
    c.setFont("Times-Roman", 8)
    c.drawString(
        MARGIN,
        PAGE_HEIGHT - 2.36 * cm,
        f"{edition_label} • {today.strftime('%d/%m/%Y')}",
    )
    c.drawRightString(
        PAGE_WIDTH - MARGIN,
        PAGE_HEIGHT - 2.36 * cm,
        f"Gerado às {now.strftime('%H:%M')}",
    )
    draw_rule(c, PAGE_HEIGHT - 2.55 * cm, width=0.65)

    content_top = PAGE_HEIGHT - 2.90 * cm
    content_bottom = 2.0 * cm
    gutter = 0.45 * cm
    content_width = PAGE_WIDTH - 2 * MARGIN
    left_width = 12.2 * cm
    right_width = content_width - left_width - gutter
    right_x = MARGIN + left_width + gutter

    draw_news_column(
        c,
        newsletters,
        MARGIN,
        content_top,
        left_width,
        content_bottom,
        styles,
    )

    right_y = content_top
    right_y = draw_section_title(c, "Hoje", right_x, right_y, right_width)
    right_y = draw_agenda_rows(c, agenda_hoje, right_x, right_y, right_width)
    right_y -= 0.10 * cm

    right_y = draw_section_title(c, "Amanhã", right_x, right_y, right_width)
    right_y = draw_agenda_rows(c, agenda_amanha, right_x, right_y, right_width)
    right_y -= 0.10 * cm

    right_y = draw_section_title(c, "Tarefas", right_x, right_y, right_width)
    draw_task_rows(c, tasks_do_dia, right_x, right_y, right_width)

    draw_rule(c, 1.10 * cm, width=0.65)
    c.setFillColor(MUTED_INK)
    c.setFont("Times-Italic", 7.2)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        0.72 * cm,
        "O Jornal do Yuri • Edição gerada localmente",
    )

    c.showPage()

    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    c.setFillColor(INK)
    c.setFont("Times-Bold", 9)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 0.7 * cm,
        "O JORNAL DO YURI • PASSATEMPO DIÁRIO",
    )
    draw_rule(c, PAGE_HEIGHT - 0.9 * cm, width=1.2)

    c.setFont("Times-Bold", 25)
    c.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 1.85 * cm, "SUDOKU DO DIA")

    c.setFont("Times-Italic", 9)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 2.3 * cm,
        f"{today.strftime('%d/%m/%Y')} • dificuldade média",
    )
    draw_rule(c, PAGE_HEIGHT - 2.5 * cm, width=1.2)

    puzzle, _solution = generate_sudoku(today, blanks=48)
    sudoku_size = 14.5 * cm
    sudoku_x = (PAGE_WIDTH - sudoku_size) / 2
    sudoku_top = PAGE_HEIGHT - 3.6 * cm
    draw_sudoku(c, puzzle, sudoku_x, sudoku_top, sudoku_size)

    instruction_y = sudoku_top - sudoku_size - 0.6 * cm
    c.setFillColor(INK)
    c.setFont("Times-Bold", 11)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        instruction_y,
        "Complete cada linha, coluna e bloco 3×3 com os números de 1 a 9.",
    )

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Italic", 8.5)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        instruction_y - 0.45 * cm,
        "Mesmo dia, mesmo puzzle. A edição seguinte terá uma nova grade.",
    )

    draw_rule(c, 1.1 * cm, width=0.8)
    c.setFont("Times-Italic", 7.5)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        0.72 * cm,
        "O Jornal do Yuri • Passatempo diário • Gerado localmente",
    )

    c.save()
    return filename


def main():
    parser = argparse.ArgumentParser(
        description="Gera uma edição local do Jornal do Yuri."
    )
    parser.add_argument(
        "--edition",
        choices=["manha", "noite"],
        default="manha",
        help="Tipo da edição a gerar.",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Marcador do Gmail usado para as newsletters.",
    )
    args = parser.parse_args()

    if args.label:
        newsletters_label = args.label
    else:
        newsletters_label = NEWSLETTER_LABEL

    filename = build_pdf(args.edition, newsletters_label)
    print(f"PDF gerado: {filename}")


if __name__ == "__main__":
    main()