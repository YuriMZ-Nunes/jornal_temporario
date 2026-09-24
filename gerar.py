#!/usr/bin/env python3

import argparse
import hashlib
import json
import random
import re
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import unicodedata

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
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

STORIES_FILE = Path("output/stories.json")
IMAGES_FILE = Path("output/images.json")

MAX_AGENDA_EVENTS = 4
MAX_TASKS = 6
MAX_WEEK_EVENTS = 14
MAX_COVER_SUMMARY = 520

COVER_IMAGE_HEIGHT = 4.6 * cm
COVER_IMAGE_GAP = 0.18 * cm

ARTICLE_IMAGE_MIN_WIDTH = 4.4 * cm
ARTICLE_IMAGE_MAX_WIDTH = 6.8 * cm

ARTICLE_IMAGE_MIN_HEIGHT = 2.4 * cm
ARTICLE_IMAGE_MAX_HEIGHT = 4.6 * cm

ARTICLE_IMAGE_GAP = 0.22 * cm
BODY_CONTINUATION_ADJUSTMENT = 0.08 * cm
SIDEBAR_TOP_HEIGHT = 5.8 * cm
SIDEBAR_PADDING_BOTTOM = 0.18 * cm
BODY_CONTINUATION_ADJUSTMENT = 0.10 * cm
APOD_OUTPUT_DIR = Path("output/apod")

ARTICLE_SIDE_LINES = 12
ARTICLE_BODY_LEADING = 12

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]


def get_google_credentials():
    """
    Lê ou cria credenciais OAuth para Google Calendar e Tasks.

    Quando o token salvo está expirado ou revogado, remove token.json
    e abre automaticamente uma nova autorização no navegador.
    """
    token_path = Path("token.json")
    credentials_path = Path("credentials.json")
    credentials = None

    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            token_path,
            GOOGLE_SCOPES,
        )

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
    ):
        try:
            credentials.refresh(Request())
        except RefreshError:
            print(
                "Token Google expirado ou revogado. "
                "Abrindo nova autorização."
            )

            credentials = None
            token_path.unlink(missing_ok=True)

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

        token_path.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return credentials


def get_calendar_service(credentials):
    return build(
        "calendar",
        "v3",
        credentials=credentials,
    )


def get_tasks_service(credentials):
    return build(
        "tasks",
        "v1",
        credentials=credentials,
    )


def clean_text(text):
    """
    Prepara texto para as fontes Times do ReportLab.

    Remove emojis e símbolos sem suporte, mas nunca corta conteúdo.
    """
    text = str(text or "")

    text = text.replace("\u200b", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")
    text = text.replace("\ufe0f", "")
    text = text.replace("\xa0", " ")

    kept = []

    for char in text:
        category = unicodedata.category(char)

        if category.startswith("So"):
            continue

        if category == "Cn":
            continue

        kept.append(char)

    text = "".join(kept)
    text = " ".join(text.split())

    return text.strip()

def get_stories():
    """
    Lê as matérias escolhidas pelo editor_llm.py.
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
            "stories.json existe, mas não contém matérias."
        )

    return stories


def get_image_index():
    """
    Retorna um dicionário de candidate_id para caminho local de imagem.

    O mapa é produzido por download_images.py.
    """
    if not IMAGES_FILE.exists():
        print(
            f"Aviso: não encontrei {IMAGES_FILE}; "
            "o PDF será gerado sem imagens."
        )
        return {}

    try:
        data = json.loads(
            IMAGES_FILE.read_text(
                encoding="utf-8",
            )
        )
    except (OSError, json.JSONDecodeError) as error:
        print(
            f"Aviso: não foi possível ler {IMAGES_FILE}: {error}"
        )
        return {}

    index = {}

    for item in data.get("images", []):
        candidate_id = str(
            item.get("candidate_id", "")
        ).strip()

        image_file = str(
            item.get("image_file", "")
        ).strip()

        if not candidate_id or not image_file:
            continue

        image_path = Path(image_file)

        if image_path.exists() and image_path.is_file():
            index[candidate_id] = image_path
        else:
            print(
                f"Aviso: imagem ausente para "
                f"{candidate_id}: {image_path}"
            )

    return index


def normalize_section_name(section):
    """
    Normaliza seção para uso interno em regras editoriais.
    """
    return (
        clean_text(section)
        .casefold()
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ã", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )

def get_today_apod(today):
    """
    Lê os metadados e valida a imagem da NASA APOD baixada para hoje.

    O arquivo é produzido por nasa_apod.py.
    """
    metadata_path = (
        APOD_OUTPUT_DIR
        / f"apod-{today.isoformat()}.json"
    )

    if not metadata_path.exists():
        raise FileNotFoundError(
            "Não encontrei a APOD de hoje. "
            "Execute `python nasa_apod.py` antes de gerar o PDF. "
            f"Arquivo esperado: {metadata_path}"
        )

    try:
        apod = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Os metadados da APOD são inválidos: {metadata_path}"
        ) from error

    image_path = Path(
        str(apod.get("local_image_path", "")).strip()
    )

    if not image_path.is_file():
        raise FileNotFoundError(
            "Não encontrei a imagem APOD indicada nos metadados: "
            f"{image_path}"
        )

    apod["local_image_path"] = image_path
    return apod


def is_the_news_story(story):
    """
    Identifica matérias vindas do The News.

    Funciona com 'the news ☕' e variações de maiúsculas/minúsculas.
    """
    source = clean_text(
        story.get("source", "")
    ).casefold()

    return "the news" in source


def cover_priority(story):
    """
    Define prioridade editorial de capa para matérias do The News.

    Quanto maior o número, maior a prioridade.
    """
    section = normalize_section_name(
        story.get("section", "")
    )

    priorities = {
        "big story": 100,
        "mundo": 90,
        "brasil": 85,
        "politica": 80,
        "negocios": 75,
        "economia": 72,
        "tecnologia": 70,
        "ciencia": 65,
        "esportes": 55,
        "marketing": 30,
        "giveaway do denius": 10,
        "dicas": 5,
    }

    return priorities.get(section, 50)


def cover_story_score(story):
    """
    Retorna uma tupla usada para escolher a capa.

    Ordem dos critérios:
    1. prioridade da seção;
    2. tamanho do texto-fonte;
    3. tamanho do título.

    Isso favorece uma reportagem mais substancial quando duas matérias
    tiverem a mesma seção/prioridade.
    """
    body = (
        story.get("source_text")
        or story.get("body")
        or story.get("summary", "")
    )   

    return (
        cover_priority(story),
        len(clean_text(body)),
        len(clean_text(story.get("title", ""))),
    )


def choose_cover_story(stories, image_index):
    """
    Escolhe obrigatoriamente uma matéria The News que possua imagem local.

    Não usa matérias do Filipe Deschamps para a capa.
    Não aceita matéria sem arquivo local de imagem.
    """
    eligible = [
        story
        for story in stories
        if is_the_news_story(story)
        and story.get("candidate_id", "") in image_index
    ]

    if not eligible:
        raise RuntimeError(
            "Não encontrei nenhuma matéria do The News com imagem local "
            "para usar na capa. Rode download_images.py e confirme que "
            "output/images.json contém ao menos uma imagem válida."
        )

    return max(
        eligible,
        key=cover_story_score,
    )


def image_side_for_story(story, edition_day):
    """
    Decide se a imagem fica à esquerda ou direita.

    O resultado é pseudoaleatório e estável para a mesma matéria e data.
    Isso evita que regenerar o mesmo PDF altere o layout sem motivo.
    """
    candidate_id = str(
        story.get("candidate_id", "")
    )

    seed = (
        f"jornal-pessoal:image-side:"
        f"{edition_day.isoformat()}:"
        f"{candidate_id}"
    )

    digest = hashlib.sha256(
        seed.encode("utf-8")
    ).digest()

    return "left" if digest[0] % 2 == 0 else "right"


def event_start_datetime(event):
    start = event["start"]

    if "dateTime" in start:
        return datetime.fromisoformat(
            start["dateTime"]
        ).astimezone(TIMEZONE)

    return datetime.combine(
        date.fromisoformat(start["date"]),
        time.min,
        tzinfo=TIMEZONE,
    )


def format_calendar_event(event):
    title = event.get("summary", "(Sem título)")
    start = event["start"]

    if "date" in start:
        return {
            "time": "DIA TODO",
            "title": title,
        }

    start_dt = event_start_datetime(event)

    return {
        "time": start_dt.strftime("%H:%M"),
        "title": title,
    }


def get_events_for_day(service, target_day):
    start = datetime.combine(
        target_day,
        time.min,
        tzinfo=TIMEZONE,
    )

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


def get_events_for_week(service, start_day):
    events = []

    for offset in range(7):
        target_day = start_day + timedelta(days=offset)

        events.extend(
            get_events_for_day(
                service,
                target_day,
            )
        )

    return events


def task_is_for_day(task, target_day):
    due = task.get("due")

    return bool(due) and (
        date.fromisoformat(due[:10]) == target_day
    )


def get_tasks_for_day(service, target_day):
    task_lists = service.tasklists().list(
        maxResults=100,
    ).execute()

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


def daily_rng(day):
    seed_text = f"jornal-pessoal:sudoku:{day.isoformat()}"

    seed = int(
        hashlib.sha256(
            seed_text.encode()
        ).hexdigest(),
        16,
    )

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

    solution = [
        [0 for _ in range(9)]
        for _ in range(9)
    ]

    solve_grid(solution, rng)

    puzzle = [row[:] for row in solution]

    positions = [
        (row, col)
        for row in range(9)
        for col in range(9)
    ]

    rng.shuffle(positions)

    for row, col in positions[:blanks]:
        puzzle[row][col] = 0

    return puzzle, solution


def draw_rule(
    c,
    y,
    x1=MARGIN,
    x2=PAGE_WIDTH - MARGIN,
    width=0.8,
):
    c.setStrokeColor(RULE)
    c.setLineWidth(width)
    c.line(x1, y, x2, y)


def draw_wrapped_paragraph(c, text, x, y_top, width, style):
    paragraph = Paragraph(text, style)

    _, height = paragraph.wrap(
        width,
        PAGE_HEIGHT,
    )

    paragraph.drawOn(
        c,
        x,
        y_top - height,
    )

    return y_top - height


def draw_section_title(c, title, x, y, width):
    c.setFillColor(INK)
    c.setFont("Times-Bold", 10)

    c.drawString(
        x,
        y,
        title.upper(),
    )

    draw_rule(
        c,
        y - 0.12 * cm,
        x1=x,
        x2=x + width,
        width=0.5,
    )

    return y - 0.42 * cm


def load_image_reader(image_path):
    """
    Lê uma imagem via Pillow e a entrega como PNG em memória.

    Isso permite renderizar JPEG, PNG e WebP locais com previsibilidade
    no ReportLab.
    """
    with Image.open(image_path) as image:
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")

        output = BytesIO()

        image.save(
            output,
            format="PNG",
        )

        output.seek(0)

    return ImageReader(output)


def draw_story_image(
    c,
    image_path,
    x,
    y_top,
    max_width,
    max_height,
):
    """
    Desenha imagem proporcional e sem moldura.

    A imagem começa em x e é posicionada imediatamente abaixo de y_top.

    Retorna:
        (image_x, image_y, image_width, image_height, image_drawn)
    """
    if not image_path:
        return x, y_top, 0, 0, False

    try:
        image = load_image_reader(image_path)

        original_width, original_height = image.getSize()

        if original_width <= 0 or original_height <= 0:
            raise ValueError("Dimensões inválidas.")

        scale = min(
            max_width / original_width,
            max_height / original_height,
        )

        image_width = original_width * scale
        image_height = original_height * scale

        image_y = y_top - image_height

        c.drawImage(
            image,
            x,
            image_y,
            width=image_width,
            height=image_height,
            preserveAspectRatio=True,
            anchor="sw",
            mask="auto",
        )

        return (
            x,
            image_y,
            image_width,
            image_height,
            True,
        )

    except Exception as error:
        print(
            f"Aviso: não foi possível desenhar imagem "
            f"{image_path}: {error}"
        )

        return x, y_top, 0, 0, False


def draw_sudoku(c, puzzle, x, y_top, size):
    cell = size / 9
    y = y_top - size

    c.setFillColor(LIGHT_FILL)
    c.rect(
        x,
        y,
        size,
        size,
        fill=1,
        stroke=0,
    )

    c.setStrokeColor(INK)

    for index in range(10):
        line_width = 1.8 if index % 3 == 0 else 0.45

        c.setLineWidth(line_width)

        c.line(
            x + index * cell,
            y,
            x + index * cell,
            y + size,
        )

        c.line(
            x,
            y + index * cell,
            x + size,
            y + index * cell,
        )

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

            c.drawCentredString(
                center_x,
                baseline_y,
                str(value),
            )


def draw_agenda_rows(
    c,
    events,
    x,
    y_top,
    width,
    max_items=MAX_AGENDA_EVENTS,
):
    y = y_top

    if not events:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 8)

        c.drawString(
            x,
            y,
            "Nenhum compromisso.",
        )

        return y - 0.55 * cm

    event_style = ParagraphStyle(
        "AgendaEvent",
        fontName="Times-Roman",
        fontSize=8.3,
        leading=9.8,
        textColor=INK,
    )

    for event in events[:max_items]:
        c.setFillColor(INK)
        c.setFont("Times-Bold", 8.3)

        c.drawString(
            x,
            y,
            event["time"],
        )

        y_after = draw_wrapped_paragraph(
            c,
            clean_text(event["title"]),
            x + 1.55 * cm,
            y + 0.11 * cm,
            width - 1.55 * cm,
            event_style,
        )

        y = min(
            y - 0.48 * cm,
            y_after - 0.16 * cm,
        )

    if len(events) > max_items:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 7.4)

        c.drawString(
            x,
            y,
            f"+ {len(events) - max_items} outro(s) compromisso(s)",
        )

        y -= 0.42 * cm

    return y


def draw_task_rows(
    c,
    tasks,
    x,
    y_top,
    width,
    max_items=MAX_TASKS,
):
    y = y_top

    if not tasks:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 8)

        c.drawString(
            x,
            y,
            "Nenhuma tarefa agendada.",
        )

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

        c.rect(
            x,
            y - 0.23 * cm,
            box,
            box,
            fill=0,
            stroke=1,
        )

        y_after = draw_wrapped_paragraph(
            c,
            clean_text(task),
            x + 0.52 * cm,
            y + 0.10 * cm,
            width - 0.52 * cm,
            task_style,
        )

        y = min(
            y - 0.48 * cm,
            y_after - 0.14 * cm,
        )

    if len(tasks) > max_items:
        c.setFillColor(MUTED_INK)
        c.setFont("Times-Italic", 7.4)

        c.drawString(
            x,
            y,
            f"+ {len(tasks) - max_items} outra(s) tarefa(s)",
        )

        y -= 0.42 * cm

    return y

def draw_cover_sidebar(
    c,
    agenda_amanha,
    tasks_do_dia,
    x,
    y_top,
    width,
):
    """
    Agenda e tarefas no topo direito da capa.

    A linha inferior acompanha o fim real do conteúdo lateral.
    """
    y = draw_section_title(
        c,
        "Amanhã",
        x,
        y_top,
        width,
    )

    y = draw_agenda_rows(
        c,
        agenda_amanha,
        x,
        y,
        width,
        max_items=MAX_AGENDA_EVENTS,
    )

    y -= 0.16 * cm

    y = draw_section_title(
        c,
        "Tarefas",
        x,
        y,
        width,
    )

    y = draw_task_rows(
        c,
        tasks_do_dia,
        x,
        y,
        width,
        max_items=MAX_TASKS,
    )

    y -= 0.12 * cm

    draw_rule(
        c,
        y,
        x1=x,
        x2=x + width,
        width=0.45,
    )

    return y

def draw_cover_story(
    c,
    story,
    x,
    y_top,
    cover_width,
    full_width,
    styles,
    image_index,
):
    """
    Desenha a notícia principal da capa.

    A imagem, a manchete e o texto são empilhados verticalmente sem
    cruzar a área lateral de agenda/tarefas. O texto usa largura completa.
    """
    section = clean_text(
        story.get("section", "Destaque")
    )

    title = clean_text(
        story.get("title", "Sem título")
    )

    source = clean_text(
        story.get("source", "Fonte desconhecida")
    )

    source_text = clean_text(
        story.get("source_text")
        or story.get("body")
        or story.get("summary", "")
    )

    candidate_id = story.get("candidate_id", "")
    image_path = image_index.get(candidate_id)

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Bold", 8)

    c.drawString(
        x,
        y_top,
        section.upper(),
    )

    c.setFont("Times-Roman", 7.5)

    c.drawRightString(
        x + cover_width,
        y_top,
        source.upper(),
    )

    y = y_top - 0.30 * cm

    if image_path:
        (
            _image_x,
            image_y,
            _image_width,
            _image_height,
            image_drawn,
        ) = draw_story_image(
            c,
            image_path,
            x,
            y,
            cover_width,
            COVER_IMAGE_HEIGHT,
        )

        if image_drawn:
            y = image_y - COVER_IMAGE_GAP

    y = draw_wrapped_paragraph(
        c,
        title,
        x,
        y,
        cover_width,
        styles["cover_headline"],
    )

    # Espaço visual real entre manchete e texto.
    y -= 0.42 * cm

    y = draw_wrapped_paragraph(
        c,
        source_text,
        x,
        y,
        full_width,
        styles["cover_body"],
    )

    return y - 0.20 * cm


def draw_nasa_cover(
    c,
    apod,
    x,
    y_top,
    cover_width,
    full_width,
    styles,
):
    """
    Desenha a capa com a Astronomy Picture of the Day da NASA.
    """
    apod_date = clean_text(apod.get("date", ""))
    title = clean_text(
        apod.get("title", "Astronomy Picture of the Day")
    )
    explanation = clean_text(
        apod.get("explanation", "")
    )[:MAX_COVER_SUMMARY]
    credit = clean_text(
        apod.get("copyright") or "NASA"
    )
    image_path = apod["local_image_path"]

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Bold", 8)
    c.drawString(
        x,
        y_top,
        "ASTRONOMY PICTURE OF THE DAY",
    )

    c.setFont("Times-Roman", 7.5)
    c.drawRightString(
        x + cover_width,
        y_top,
        f"NASA • {apod_date}",
    )

    y = y_top - 0.30 * cm

    (
        _image_x,
        image_y,
        _image_width,
        _image_height,
        image_drawn,
    ) = draw_story_image(
        c,
        image_path,
        x,
        y,
        cover_width,
        COVER_IMAGE_HEIGHT,
    )

    if not image_drawn:
        raise RuntimeError(
            "Não foi possível desenhar a imagem APOD na capa."
        )

    y = image_y - COVER_IMAGE_GAP

    y = draw_wrapped_paragraph(
        c,
        title,
        x,
        y,
        cover_width,
        styles["cover_headline"],
    )

    y -= 0.28 * cm

    y = draw_wrapped_paragraph(
        c,
        explanation,
        x,
        y,
        full_width,
        styles["cover_body"],
    )

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Italic", 7.5)
    c.drawString(
        x,
        y - 0.16 * cm,
        f"Crédito: {credit}",
    )

    return y - 0.45 * cm


def story_height(
    story,
    width,
    styles,
    image_index,
):
    """
    Mede a altura estimada de uma matéria usando o mesmo tamanho
    dinâmico de imagem aplicado no desenho.

    A estimativa é conservadora para evitar que a matéria atravesse
    o rodapé da página.
    """
    title = clean_text(
        story.get("title", "Sem título"),
    )

    source_text = clean_text(
        story.get("source_text")
        or story.get("body")
        or story.get("summary", "")
    )

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

    candidate_id = story.get("candidate_id", "")
    image_path = image_index.get(candidate_id)

    if not image_path:
        return (
            0.68 * cm
            + title_height
            + 0.22 * cm
            + body_height
            + 0.72 * cm
        )

    try:
        (
            _image_width,
            image_height,
            text_width,
        ) = choose_article_image_size(
            image_path,
            source_text,
            width,
            styles["article_body"],
        )

        _side_text, remaining_text, _side_height = (
            split_text_for_lines(
                source_text,
                text_width,
                ARTICLE_SIDE_LINES,
                styles["article_body"],
            )
        )

        remaining_paragraph = Paragraph(
            remaining_text,
            styles["article_body"],
        )

        _, remaining_height = remaining_paragraph.wrap(
            width,
            PAGE_HEIGHT,
        )

        # Espaço de seção/fonte + título + respiro + bloco da foto +
        # continuação do texto + régua e margem de segurança.
        return (
            0.68 * cm
            + title_height
            + 0.22 * cm
            + image_height
            + remaining_height
            + 0.90 * cm
        )

    except Exception as error:
        print(
            f"Aviso: medição sem imagem para "
            f"{candidate_id}: {error}"
        )

        return (
            0.68 * cm
            + title_height
            + 0.22 * cm
            + body_height
            + 0.72 * cm
        )

def build_article_plan(
    story,
    width,
    styles,
    image_index,
    edition_day,
):
    """
    Mede matéria interna usando o mesmo fluxo visual do draw_article().
    """
    title = clean_text(
        story.get("title", "Sem título")
    )

    source_text = clean_text(
        story.get("source_text")
        or story.get("body")
        or story.get("summary", "")
    )

    candidate_id = story.get("candidate_id", "")
    image_path = image_index.get(candidate_id)

    title_paragraph = Paragraph(
        title,
        styles["article_headline"],
    )

    _, title_height = title_paragraph.wrap(
        width,
        PAGE_HEIGHT,
    )

    if not image_path:
        body_paragraph = Paragraph(
            source_text,
            styles["article_body"],
        )

        _, body_height = body_paragraph.wrap(
            width,
            PAGE_HEIGHT,
        )

        return {
            "total_height": (
                0.68 * cm
                + title_height
                + 0.22 * cm
                + body_height
                + 0.61 * cm
            )
        }

    try:
        (
            image_width,
            image_height,
            text_width,
        ) = choose_article_image_size(
            image_path,
            source_text,
            width,
            styles["article_body"],
        )

        _side_text, remaining_text, _side_height = (
            split_text_for_lines(
                source_text,
                text_width,
                ARTICLE_SIDE_LINES,
                styles["article_body"],
            )
        )

        remaining_paragraph = Paragraph(
            remaining_text,
            styles["article_body"],
        )

        _, remaining_height = remaining_paragraph.wrap(
            width,
            PAGE_HEIGHT,
        )

        return {
            "total_height": (
                0.68 * cm
                + title_height
                + 0.22 * cm
                + image_height
                + remaining_height
                + 0.70 * cm
            )
        }

    except Exception:
        body_paragraph = Paragraph(
            source_text,
            styles["article_body"],
        )

        _, body_height = body_paragraph.wrap(
            width,
            PAGE_HEIGHT,
        )

        return {
            "total_height": (
                0.68 * cm
                + title_height
                + 0.22 * cm
                + body_height
                + 0.61 * cm
            )
        }

def split_text_for_lines(
    text,
    width,
    line_count,
    style,
):
    """
    Divide texto pela maior quantidade de palavras que ocupa no máximo
    `line_count` linhas dentro da largura fornecida.

    Retorna:
        (texto_lateral, texto_restante, altura_lateral)
    """
    text = clean_text(text)

    if not text:
        return "", "", 0

    max_height = line_count * style.leading
    words = text.split()

    low = 0
    high = len(words)
    best_count = 0
    best_height = 0

    while low <= high:
        middle = (low + high) // 2
        candidate = " ".join(words[:middle])

        paragraph = Paragraph(
            candidate,
            style,
        )

        _, height = paragraph.wrap(
            width,
            PAGE_HEIGHT,
        )

        if height <= max_height:
            best_count = middle
            best_height = height
            low = middle + 1
        else:
            high = middle - 1

    side_text = " ".join(words[:best_count])
    remaining_text = " ".join(words[best_count:])

    return side_text, remaining_text, best_height

def choose_article_image_size(
    image_path,
    source_text,
    available_width,
    body_style,
):
    """
    Escolhe o tamanho horizontal da imagem e limita sua altura à faixa
    fixa reservada ao texto lateral.

    A continuação do texto deve começar sempre após ARTICLE_SIDE_LINES,
    independentemente da proporção original da imagem.

    Retorna:
        (image_width, image_height, text_width)
    """
    image = load_image_reader(image_path)

    original_width, original_height = image.getSize()

    if original_width <= 0 or original_height <= 0:
        raise ValueError("Dimensões de imagem inválidas.")

    aspect_ratio = original_width / original_height

    # A altura editorial do bloco lateral é fixa:
    # por exemplo, 9 linhas de texto com leading de 12 pt.
    side_block_height = (
        ARTICLE_SIDE_LINES
        * body_style.leading
    )

    # Garantimos que a faixa também respeite os limites já definidos.
    target_max_height = min(
        side_block_height,
        ARTICLE_IMAGE_MAX_HEIGHT,
    )

    target_min_height = min(
        ARTICLE_IMAGE_MIN_HEIGHT,
        target_max_height,
    )

    candidate_widths = [
        ARTICLE_IMAGE_MIN_WIDTH + step * 0.4 * cm
        for step in range(
            int(
                (
                    ARTICLE_IMAGE_MAX_WIDTH
                    - ARTICLE_IMAGE_MIN_WIDTH
                ) / (0.4 * cm)
            ) + 1
        )
    ]

    best_choice = None
    best_score = None

    for candidate_width in candidate_widths:
        text_width = (
            available_width
            - candidate_width
            - ARTICLE_IMAGE_GAP
        )

        if text_width < 5.0 * cm:
            continue

        natural_height = candidate_width / aspect_ratio

        # Nunca deixa a foto ultrapassar a faixa de linhas laterais.
        image_height = min(
            natural_height,
            target_max_height,
        )

        # Para imagens muito panorâmicas, não deixamos a foto ficar
        # visualmente pequena demais, mas sem passar da faixa lateral.
        image_height = max(
            image_height,
            target_min_height,
        )

        # A imagem deve continuar proporcional:
        # se limitamos a altura, ajustamos também a largura.
        proportional_width = (
            image_height
            * aspect_ratio
        )

        # Não permite que ela fique maior que a largura candidata.
        image_width = min(
            proportional_width,
            candidate_width,
        )

        # Recalcula a coluna de texto após o ajuste proporcional.
        text_width = (
            available_width
            - image_width
            - ARTICLE_IMAGE_GAP
        )

        if text_width < 5.0 * cm:
            continue

        # Prefere imagens maiores, desde que preservem uma boa coluna
        # de leitura ao lado delas.
        score = (
            abs(image_height - target_max_height)
            + (ARTICLE_IMAGE_MAX_WIDTH - image_width) * 0.10
        )

        if best_score is None or score < best_score:
            best_score = score
            best_choice = (
                image_width,
                image_height,
                text_width,
            )

    if best_choice:
        return best_choice

    fallback_width = min(
        ARTICLE_IMAGE_MIN_WIDTH,
        available_width - 5.0 * cm - ARTICLE_IMAGE_GAP,
    )

    fallback_width = max(
        fallback_width,
        2.5 * cm,
    )

    fallback_height = min(
        fallback_width / aspect_ratio,
        target_max_height,
    )

    fallback_height = max(
        fallback_height,
        target_min_height,
    )

    fallback_width = min(
        fallback_height * aspect_ratio,
        fallback_width,
    )

    return (
        fallback_width,
        fallback_height,
        available_width
        - fallback_width
        - ARTICLE_IMAGE_GAP,
    )

def draw_article(
    c,
    story,
    x,
    y_top,
    width,
    styles,
    image_index,
    edition_day,
):
    """
    Desenha matéria interna em estilo editorial.

    A imagem fica aleatoriamente à esquerda ou à direita.
    O texto ocupa o espaço lateral até a última frase completa que couber.
    O restante segue abaixo em largura total, sem legenda e sem truncamento.
    """
    section = clean_text(
        story.get("section", "Sem seção")
    )

    title = clean_text(
        story.get("title", "Sem título")
    )

    source = clean_text(
        story.get("source", "Fonte desconhecida")
    )

    source_text = clean_text(
        story.get("source_text")
        or story.get("body")
        or story.get("summary", "")
    )

    candidate_id = story.get("candidate_id", "")
    image_path = image_index.get(candidate_id)

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Bold", 7.4)

    c.drawString(
        x,
        y_top,
        section.upper(),
    )

    c.setFont("Times-Roman", 7.2)

    c.drawRightString(
        x + width,
        y_top,
        source.upper(),
    )

    y = y_top - 0.24 * cm

    y = draw_wrapped_paragraph(
        c,
        title,
        x,
        y,
        width,
        styles["article_headline"],
    )

    y -= 0.22 * cm

    if not image_path:
        y = draw_wrapped_paragraph(
            c,
            source_text,
            x,
            y,
            width,
            styles["article_body"],
        )

        y -= 0.25 * cm

        draw_rule(
            c,
            y,
            x1=x,
            x2=x + width,
            width=0.35,
        )

        return y - 0.36 * cm

    image_side = image_side_for_story(
        story,
        edition_day,
    )

    try:
        (
            image_max_width,
            image_max_height,
            text_width,
        ) = choose_article_image_size(
            image_path,
            source_text,
            width,
            styles["article_body"],
        )
    except Exception as error:
        print(
            f"Aviso: usando imagem em tamanho padrão para "
            f"{candidate_id}: {error}"
        )

        image_max_width = 5.4 * cm
        image_max_height = 3.4 * cm
        text_width = (
            width
            - image_max_width
            - ARTICLE_IMAGE_GAP
        )

    if image_side == "left":
        image_x = x
        text_x = (
            x
            + image_max_width
            + ARTICLE_IMAGE_GAP
        )
    else:
        text_x = x
        image_x = (
            x
            + width
            - image_max_width
        )

    text_block_top = y

    (
        _image_x,
        image_y,
        image_width,
        image_height,
        image_drawn,
    ) = draw_story_image(
        c,
        image_path,
        image_x,
        text_block_top,
        image_max_width,
        image_max_height,
    )

    side_text, remaining_text, side_height = (
        split_text_for_lines(
            source_text,
            text_width,
            ARTICLE_SIDE_LINES,
            styles["article_body"],
        )
    )

    if side_text:
        side_y = draw_wrapped_paragraph(
            c,
            side_text,
            text_x,
            text_block_top,
            text_width,
            styles["article_body"],
        )
    else:
        side_y = text_block_top

    continuation_y = (
        text_block_top
        - ARTICLE_SIDE_LINES
        * styles["article_body"].leading
    )

    if remaining_text:
        y = draw_wrapped_paragraph(
            c,
            remaining_text,
            x,
            continuation_y,
            width,
            styles["article_body"],
        )
    else:
        y = continuation_y

    # Espaço antes da linha que separa matérias.
    y -= 0.30 * cm

    c.setStrokeColor(colors.HexColor("#777777"))
    c.setLineWidth(0.35)
    c.line(
        x,
        y,
        x + width,
        y,
    )

    # Espaço depois da linha antes da próxima matéria.
    y -= 0.38 * cm

    return y


def draw_internal_page_header(c, page_number, today):
    c.setFillColor(INK)
    c.setFont("Times-Bold", 8)

    c.drawString(
        MARGIN,
        PAGE_HEIGHT - 0.60 * cm,
        "O JORNAL DO YURI",
    )

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Roman", 7.4)

    c.drawRightString(
        PAGE_WIDTH - MARGIN,
        PAGE_HEIGHT - 0.60 * cm,
        f"{today.strftime('%d/%m/%Y')} • PÁGINA {page_number}",
    )

    draw_rule(
        c,
        PAGE_HEIGHT - 0.80 * cm,
        width=0.7,
    )


def draw_internal_page_footer(c, page_number):
    draw_rule(
        c,
        1.05 * cm,
        width=0.45,
    )

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Italic", 7)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        0.70 * cm,
        f"O Jornal do Yuri • Página {page_number}",
    )


def draw_story_pages(
    c,
    stories,
    today,
    styles,
    image_index,
    first_page_number=2,
):
    """
    Preenche cada página com o máximo possível de matérias completas.

    Uma matéria só é movida de página quando ela não cabe por inteiro
    no espaço que resta. Não corta texto nem desenha por cima do rodapé.
    """
    remaining_stories = stories

    if not remaining_stories:
        return first_page_number - 1

    page_number = first_page_number
    content_width = PAGE_WIDTH - 2 * MARGIN
    y_top_start = PAGE_HEIGHT - 1.18 * cm
    y_bottom = 1.40 * cm
    y = y_top_start

    for story in remaining_stories:
        plan = build_article_plan(
            story,
            content_width,
            styles,
            image_index,
            today,
        )

        available_height = y - y_bottom

        if plan["total_height"] > available_height:
            draw_internal_page_footer(
                c,
                page_number,
            )

            c.showPage()
            page_number += 1

            c.setFillColor(PAPER)
            c.rect(
                0,
                0,
                PAGE_WIDTH,
                PAGE_HEIGHT,
                fill=1,
                stroke=0,
            )

            draw_internal_page_header(
                c,
                page_number,
                today,
            )

            y = y_top_start

        y = draw_article(
            c,
            story,
            MARGIN,
            y,
            content_width,
            styles,
            image_index,
            today,
        )

    draw_internal_page_footer(
        c,
        page_number,
    )

    return page_number

def draw_cover_header(c, edition, today, now):
    c.setFillColor(INK)
    c.setFont("Times-Bold", 8)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 0.58 * cm,
        "EDIÇÃO PESSOAL • SÃO PAULO • USO PRIVADO",
    )

    draw_rule(
        c,
        PAGE_HEIGHT - 0.77 * cm,
        width=1.0,
    )

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

    draw_rule(
        c,
        PAGE_HEIGHT - 2.04 * cm,
        width=1.0,
    )

    edition_label = (
        "EDIÇÃO DA MANHÃ"
        if edition == "manha"
        else "EDIÇÃO DA NOITE"
    )

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

    draw_rule(
        c,
        PAGE_HEIGHT - 2.55 * cm,
        width=0.65,
    )


def draw_cover_footer(c):
    draw_rule(
        c,
        1.10 * cm,
        width=0.65,
    )

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Italic", 7.2)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        0.72 * cm,
        "O Jornal do Yuri • Edição gerada localmente",
    )


def draw_week_agenda(c, events, x, y_top, width):
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

    events_by_day = {}

    for event in events[:MAX_WEEK_EVENTS]:
        event_day = event_start_datetime(event).date()

        if event_day not in events_by_day:
            events_by_day[event_day] = []

        events_by_day[event_day].append(
            format_calendar_event(event)
        )

    weekday_names = [
        "segunda",
        "terça",
        "quarta",
        "quinta",
        "sexta",
        "sábado",
        "domingo",
    ]

    column_gap = 0.45 * cm
    column_width = (width - column_gap) / 2

    left_x = x
    right_x = x + column_width + column_gap

    left_y = y
    right_y = y

    agenda_style = ParagraphStyle(
        "WeekAgenda",
        fontName="Times-Roman",
        fontSize=7.8,
        leading=9.2,
        textColor=INK,
    )

    for index, event_day in enumerate(sorted(events_by_day)):
        if index % 2 == 0:
            target_x = left_x
            target_y = left_y
        else:
            target_x = right_x
            target_y = right_y

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

        for event in events_by_day[event_day]:
            event_text = (
                f"<b>{event['time']}</b> "
                f"{clean_text(event['title'])}"
            )

            target_y = draw_wrapped_paragraph(
                c,
                event_text,
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


def draw_sudoku_page(c, today):
    c.setFillColor(PAPER)
    c.rect(
        0,
        0,
        PAGE_WIDTH,
        PAGE_HEIGHT,
        fill=1,
        stroke=0,
    )

    c.setFillColor(INK)
    c.setFont("Times-Bold", 9)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 0.7 * cm,
        "O JORNAL DO YURI • PASSATEMPO DIÁRIO",
    )

    draw_rule(
        c,
        PAGE_HEIGHT - 0.9 * cm,
        width=1.2,
    )

    c.setFont("Times-Bold", 25)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 1.85 * cm,
        "SUDOKU DO DIA",
    )

    c.setFont("Times-Italic", 9)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 2.3 * cm,
        f"{today.strftime('%d/%m/%Y')} • dificuldade média",
    )

    draw_rule(
        c,
        PAGE_HEIGHT - 2.5 * cm,
        width=1.2,
    )

    puzzle, _solution = generate_sudoku(
        today,
        blanks=48,
    )

    sudoku_size = 14.5 * cm
    sudoku_x = (PAGE_WIDTH - sudoku_size) / 2
    sudoku_top = PAGE_HEIGHT - 3.6 * cm

    draw_sudoku(
        c,
        puzzle,
        sudoku_x,
        sudoku_top,
        sudoku_size,
    )

    instruction_y = sudoku_top - sudoku_size - 0.6 * cm

    c.setFillColor(INK)
    c.setFont("Times-Bold", 11)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        instruction_y,
        (
            "Complete cada linha, coluna e bloco 3×3 "
            "com os números de 1 a 9."
        ),
    )

    c.setFillColor(MUTED_INK)
    c.setFont("Times-Italic", 8.5)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        instruction_y - 0.45 * cm,
        (
            "Mesmo dia, mesmo puzzle. "
            "A edição seguinte terá uma nova grade."
        ),
    )

    draw_rule(
        c,
        1.10 * cm,
        width=0.8,
    )

    c.setFont("Times-Italic", 7.5)

    c.drawCentredString(
        PAGE_WIDTH / 2,
        0.72 * cm,
        "O Jornal do Yuri • Passatempo diário • Gerado localmente",
    )


def build_pdf(edition):
    today = date.today()
    now = datetime.now(TIMEZONE)

    stories = get_stories()
    image_index = get_image_index()

    credentials = get_google_credentials()

    calendar_service = get_calendar_service(
        credentials
    )

    tasks_service = get_tasks_service(
        credentials
    )

    events_tomorrow = get_events_for_day(
        calendar_service,
        today + timedelta(days=1),
    )

    events_week = get_events_for_week(
        calendar_service,
        today,
    )

    tasks_today = get_tasks_for_day(
        tasks_service,
        today,
    )

    agenda_amanha = [
        format_calendar_event(event)
        for event in events_tomorrow
    ]

    tasks_do_dia = [
        task.get("title", "(Sem título)")
        for task in tasks_today
    ]

    output_dir = (
        Path("output")
        / str(today.year)
        / f"{today.month:02d}"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = output_dir / (
        f"{today.isoformat()}-{edition}.pdf"
    )

    c = canvas.Canvas(
        str(filename),
        pagesize=A4,
    )

    c.setTitle(
        f"O Jornal do Yuri — {today.isoformat()}"
    )

    styles = {
        "cover_headline": ParagraphStyle(
            "CoverHeadline",
            fontName="Times-Bold",
            fontSize=21,
            leading=23.5,
            textColor=INK,
        ),
        "cover_body": ParagraphStyle(
            "CoverBody",
            fontName="Times-Roman",
            fontSize=10,
            leading=13,
            textColor=INK,
        ),
        "article_headline": ParagraphStyle(
            "ArticleHeadline",
            fontName="Times-Bold",
            fontSize=15,
            leading=17.5,
            textColor=INK,
        ),
        "article_body": ParagraphStyle(
            "ArticleBody",
            fontName="Times-Roman",
            fontSize=9.4,
            leading=12,
            textColor=INK,
        ),
    }

    c.setFillColor(PAPER)
    c.rect(
        0,
        0,
        PAGE_WIDTH,
        PAGE_HEIGHT,
        fill=1,
        stroke=0,
    )

    draw_cover_header(
        c,
        edition,
        today,
        now,
    )

    content_top = PAGE_HEIGHT - 2.90 * cm
    cover_width = 12.2 * cm
    sidebar_gap = 0.45 * cm

    sidebar_width = (
        PAGE_WIDTH
        - 2 * MARGIN
        - cover_width
        - sidebar_gap
    )

    sidebar_x = MARGIN + cover_width + sidebar_gap

    apod = get_today_apod(today)

    print(
        "Capa NASA APOD: "
        f"{apod.get('date', '')} — "
        f"{apod.get('title', '')}"
    )
    print(
        "Imagem de capa: "
        f"{apod['local_image_path']}"
    )

    sidebar_bottom = draw_cover_sidebar(
        c,
        agenda_amanha,
        tasks_do_dia,
        sidebar_x,
        content_top,
        sidebar_width,
    )

    sidebar_bottom = draw_cover_sidebar(
        c,
        agenda_amanha,
        tasks_do_dia,
        sidebar_x,
        content_top,
        sidebar_width,
    )

    draw_nasa_cover(
        c,
        apod,
        MARGIN,
        content_top,
        cover_width,
        PAGE_WIDTH - 2 * MARGIN,
        styles,
    )

    draw_week_agenda(
        c,
        events_week,
        MARGIN,
        8.25 * cm,
        PAGE_WIDTH - 2 * MARGIN,
    )

    draw_cover_footer(c)

    c.showPage()

    c.setFillColor(PAPER)
    c.rect(
        0,
        0,
        PAGE_WIDTH,
        PAGE_HEIGHT,
        fill=1,
        stroke=0,
    )

    draw_internal_page_header(
        c,
        page_number=2,
        today=today,
    )

    draw_story_pages(
        c,
        stories,
        today,
        styles,
        image_index,
        first_page_number=2,
    )

    c.showPage()

    draw_sudoku_page(
        c,
        today,
    )

    c.save()

    return filename


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Gera uma edição local do Jornal do Yuri."
        )
    )

    parser.add_argument(
        "--edition",
        choices=["manha", "noite"],
        default="manha",
        help="Tipo da edição a gerar.",
    )

    args = parser.parse_args()

    filename = build_pdf(
        args.edition
    )

    print(f"PDF gerado: {filename}")


if __name__ == "__main__":
    main()