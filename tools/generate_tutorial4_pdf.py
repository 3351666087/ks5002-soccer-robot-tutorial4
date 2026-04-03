from __future__ import annotations

import re
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, KeepInFrame, Paragraph


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
OUTPUT = DOCS / "Tutorial4_Submission_3351666087.pdf"
TRANSCRIPT = DOCS / "tutorial4_ai_transcript.md"
REFLECTION = DOCS / "tutorial4_reflection.md"
REPO_URL = "https://github.com/3351666087/ks5002-soccer-robot-tutorial4"

PAGE_WIDTH = 13.333 * inch
PAGE_HEIGHT = 7.5 * inch


PALETTE = {
    "bg": colors.HexColor("#F4EFE6"),
    "ink": colors.HexColor("#1F2933"),
    "muted": colors.HexColor("#52606D"),
    "card": colors.HexColor("#FFFDFC"),
    "line": colors.HexColor("#D9D2C5"),
    "gold": colors.HexColor("#D97706"),
    "gold_soft": colors.HexColor("#F7E4C9"),
    "teal": colors.HexColor("#0F766E"),
    "teal_soft": colors.HexColor("#D6F2ED"),
    "blue": colors.HexColor("#155E75"),
    "blue_soft": colors.HexColor("#DDEFF6"),
    "rose": colors.HexColor("#9A3412"),
    "rose_soft": colors.HexColor("#FBE4DB"),
}


def styles():
    base = getSampleStyleSheet()
    return {
        "kicker": ParagraphStyle(
            "Kicker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=PALETTE["gold"],
        ),
        "title": ParagraphStyle(
            "Title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=PALETTE["ink"],
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            textColor=PALETTE["muted"],
        ),
        "card_title": ParagraphStyle(
            "CardTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            textColor=PALETTE["ink"],
        ),
        "repo_title": ParagraphStyle(
            "RepoTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=14,
            textColor=colors.white,
        ),
        "repo_body": ParagraphStyle(
            "RepoBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.5,
            textColor=colors.white,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=PALETTE["ink"],
            alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=PALETTE["muted"],
        ),
        "transcript": ParagraphStyle(
            "Transcript",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.3,
            leading=10.2,
            textColor=PALETTE["ink"],
        ),
        "mono": ParagraphStyle(
            "Mono",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=8.1,
            leading=9.9,
            textColor=PALETTE["ink"],
        ),
        "reflection": ParagraphStyle(
            "Reflection",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            textColor=PALETTE["ink"],
        ),
    }


def parse_markdown_sections(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    sections: dict[str, list[str]] = {}
    current = "Intro"
    sections[current] = []
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if line.startswith("# "):
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items() if "\n".join(value).strip()}


def rich_text(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r"<font face='Courier'>\1</font>", text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            lines.append("<br/>")
        elif line.startswith("- "):
            lines.append("&bull; " + line[2:])
        elif re.match(r"^\d+\.\s", line):
            lines.append(line)
        else:
            lines.append(line)
    return "<br/>".join(lines)


def draw_paragraph(
    c: canvas.Canvas,
    text: str,
    style: ParagraphStyle,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    raw: bool = False,
    shrink: bool = True,
):
    frame = Frame(x, y, w, h, showBoundary=0, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    paragraph = Paragraph(text if raw else rich_text(text), style)
    story = [KeepInFrame(w, h, [paragraph], mode="shrink")] if shrink else [paragraph]
    frame.addFromList(story, c)


def draw_shadow(c: canvas.Canvas, x: float, y: float, w: float, h: float, radius: float = 18):
    c.saveState()
    c.setFillColor(colors.Color(0, 0, 0, alpha=0.08))
    c.roundRect(x + 4, y - 4, w, h, radius, stroke=0, fill=1)
    c.restoreState()


def draw_card(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    fill_color,
    title: str,
    body: str,
    title_style: ParagraphStyle,
    body_style: ParagraphStyle,
    *,
    body_is_raw: bool = False,
):
    draw_shadow(c, x, y, w, h)
    c.saveState()
    c.setFillColor(fill_color)
    c.setStrokeColor(PALETTE["line"])
    c.setLineWidth(1)
    c.roundRect(x, y, w, h, 18, stroke=1, fill=1)
    c.restoreState()
    draw_paragraph(c, title, title_style, x + 18, y + h - 30, w - 36, 18)
    draw_paragraph(c, body, body_style, x + 18, y + 18, w - 36, h - 52, raw=body_is_raw)


def draw_chip(c: canvas.Canvas, x: float, y: float, text: str, fill_color):
    c.saveState()
    c.setFillColor(fill_color)
    c.roundRect(x, y, 112, 24, 12, stroke=0, fill=1)
    c.setFillColor(PALETTE["ink"])
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + 10, y + 8, text)
    c.restoreState()


def draw_image_card(c: canvas.Canvas, image_path: Path, x: float, y: float, w: float, h: float, caption: str):
    draw_shadow(c, x, y, w, h)
    c.saveState()
    c.setFillColor(PALETTE["card"])
    c.setStrokeColor(PALETTE["line"])
    c.roundRect(x, y, w, h, 18, stroke=1, fill=1)
    c.restoreState()

    image_h = h - 36
    with Image.open(image_path) as img:
        img_ratio = img.width / img.height
    box_ratio = (w - 16) / image_h
    if img_ratio > box_ratio:
        draw_w = w - 16
        draw_h = draw_w / img_ratio
    else:
        draw_h = image_h
        draw_w = draw_h * img_ratio
    img_x = x + (w - draw_w) / 2
    img_y = y + 28 + (image_h - draw_h) / 2
    c.drawImage(ImageReader(str(image_path)), img_x, img_y, draw_w, draw_h, preserveAspectRatio=True, mask="auto")
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(PALETTE["ink"])
    c.drawString(x + 12, y + 10, caption)


def paint_background(c: canvas.Canvas):
    c.saveState()
    c.setFillColor(PALETTE["bg"])
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    c.setFillColor(colors.Color(0.09, 0.37, 0.46, alpha=0.08))
    c.circle(PAGE_WIDTH - 70, PAGE_HEIGHT - 40, 115, stroke=0, fill=1)
    c.setFillColor(colors.Color(0.85, 0.47, 0.02, alpha=0.09))
    c.circle(110, PAGE_HEIGHT - 18, 85, stroke=0, fill=1)
    c.setFillColor(colors.Color(0.06, 0.46, 0.43, alpha=0.05))
    c.circle(PAGE_WIDTH - 15, 120, 95, stroke=0, fill=1)
    c.restoreState()


def first_page(c: canvas.Canvas, content: dict[str, str], st: dict[str, ParagraphStyle]):
    paint_background(c)
    draw_paragraph(c, "Tutorial 4 Submission", st["kicker"], 40, 492, 250, 16)
    draw_paragraph(
        c,
        "AI-Driven Physical IoT\nPrototype: KS5002 Smart Soccer Robot",
        st["title"],
        40,
        434,
        520,
        60,
    )
    draw_paragraph(
        c,
        "A polished one-file PDF that matches the course requirement: assembled photos, exact AI prompt/response used, and a short explanation of how the generated idea was improved on the real hardware.",
        st["subtitle"],
        40,
        395,
        560,
        34,
    )

    draw_chip(c, 40, 368, "6 hardware modules", PALETTE["gold_soft"])
    draw_chip(c, 164, 368, "2 AI sections highlighted", PALETTE["teal_soft"])
    draw_chip(c, 288, 368, "3 adaptive edge policies", PALETTE["blue_soft"])

    draw_shadow(c, 40, 328, 880, 34, 14)
    c.saveState()
    c.setFillColor(PALETTE["blue"])
    c.roundRect(40, 328, 880, 34, 14, stroke=0, fill=1)
    c.restoreState()
    draw_paragraph(
        c,
        f"GitHub Repository: {REPO_URL}",
        st["repo_body"],
        56,
        337,
        848,
        12,
    )

    scenario_body = (
        "Scenario: a smart campus football-training robot that can move, detect distance, capture the ball, "
        "and execute a release-and-ram kick with lightweight edge intelligence.\n\n"
        "Modules used: ultrasonic sensor, pan servo, claw servo, dual DC motors, 8x8 LED matrix, RGB LEDs, and Wi-Fi HTTP control.\n\n"
        "Evidence shown below: one fully assembled photo and one wiring/top-view photo from the physical prototype."
    )
    draw_card(
        c,
        40,
        180,
        330,
        150,
        PALETTE["card"],
        "Prototype Summary",
        scenario_body,
        st["card_title"],
        st["body"],
    )

    draw_image_card(c, ASSETS / "assembled_front.jpg", 40, 32, 160, 154, "Assembled kit")
    draw_image_card(c, ASSETS / "wiring_top.jpg", 210, 32, 160, 154, "Wiring close-up")

    prompt_text = (
        content["Prompt"]
        + "\n\nAdapted from the course prompt template to the KS5002 robot hardware available in class."
    )
    draw_card(
        c,
        390,
        200,
        530,
        130,
        colors.white,
        "Exact AI Prompt Used",
        prompt_text,
        st["card_title"],
        st["body"],
    )

    ai_sections = (
        "AI-generated section 1: `AdaptiveBandit` logic for scan/capture/ram profile choice and learning.\n\n"
        "AI-generated section 2: HTTP button routing plus manual/auto command handling for `/btn/F`, `/btn/B`, `/btn/L`, `/btn/R`, `/btn/S`, `/btn/o`, `/btn/uNNN`, `/btn/vNNN`, `/btn/l`, `/btn/m`, and `/btn/n`."
    )
    draw_card(
        c,
        390,
        20,
        255,
        170,
        PALETTE["teal_soft"],
        "Highlighted AI Code",
        ai_sections,
        st["card_title"],
        st["body"],
    )

    improvements = (
        "Human improvements after testing:\n"
        "- tuned the real claw and head servo geometry for this robot;\n"
        "- added station-first Wi-Fi with AP fallback and `/status` monitoring;\n"
        "- persisted learned policy values and refined reward rules using physical trials."
    )
    draw_card(
        c,
        665,
        20,
        255,
        170,
        PALETTE["gold_soft"],
        "Applied + Improved",
        improvements,
        st["card_title"],
        st["body"],
    )

    c.setFont("Helvetica", 8)
    c.setFillColor(PALETTE["muted"])
    c.drawString(40, 14, "Code evidence: soccer_bot.py, main.py, config.py, remote_controller.py | GitHub repo highlighted on this page")


def second_page(c: canvas.Canvas, content: dict[str, str], st: dict[str, ParagraphStyle]):
    paint_background(c)
    draw_paragraph(c, "Appendix", st["kicker"], 40, 492, 250, 16)
    draw_paragraph(c, "Exact Prompt and AI Response", st["title"], 40, 446, 400, 40)
    draw_paragraph(
        c,
        "This page keeps the wording explicit so the submission shows exactly what was asked from the AI and what parts were carried into the final prototype.",
        st["subtitle"],
        40,
        412,
        540,
        28,
    )

    draw_card(c, 40, 140, 280, 248, colors.white, "Prompt", content["Prompt"], st["card_title"], st["mono"])
    draw_card(c, 340, 140, 580, 248, colors.white, "AI Response", content["AI Response"], st["card_title"], st["transcript"])

    applied = content["Applied Improvements"]
    draw_card(c, 40, 32, 880, 94, PALETTE["blue_soft"], "How the Response Was Applied or Improved", applied, st["card_title"], st["small"])


def third_page(c: canvas.Canvas, reflection_text: str, st: dict[str, ParagraphStyle]):
    paint_background(c)
    draw_paragraph(c, "Post-Class", st["kicker"], 40, 492, 200, 16)
    draw_paragraph(c, "250-Word Reflection on AI Assistance", st["title"], 40, 446, 470, 40)
    draw_paragraph(
        c,
        "The course asked for a short reflection comparing AI-assisted development with manual coding. The text below is ready to submit as part of the report package.",
        st["subtitle"],
        40,
        412,
        560,
        28,
    )

    draw_chip(c, 40, 382, "faster first draft", PALETTE["gold_soft"])
    draw_chip(c, 164, 382, "more structured debugging", PALETTE["teal_soft"])
    draw_chip(c, 288, 382, "human tuning still needed", PALETTE["blue_soft"])

    draw_card(c, 40, 40, 880, 324, colors.white, "Reflection", reflection_text, st["card_title"], st["reflection"])


def build_pdf():
    transcript = parse_markdown_sections(TRANSCRIPT)
    reflection = REFLECTION.read_text(encoding="utf-8").strip()

    c = canvas.Canvas(str(OUTPUT), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle("Tutorial 4 Submission - KS5002 Smart Soccer Robot")
    c.setAuthor("3351666087")
    c.setSubject("AI-driven physical IoT prototype submission")

    st = styles()
    first_page(c, transcript, st)
    c.showPage()
    second_page(c, transcript, st)
    c.showPage()
    third_page(c, reflection, st)
    c.save()


if __name__ == "__main__":
    build_pdf()
