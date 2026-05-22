"""
Medbury School Effort Card Reformatter
--------------------------------------
Upload a new-format effort card PDF → download the old-style color-coded table PDF.

Requirements:
    pip install streamlit pdfplumber reportlab

Run:
    streamlit run effort_card_app.py
"""

import io
import re
import tempfile

import pdfplumber
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ---------------------------------------------------------------------------
# Colour palette (matches original Medbury old-format card)
# ---------------------------------------------------------------------------
SCORE_COLORS = {
    1: colors.HexColor("#CC0000"),  # Red    – Requiring Support
    2: colors.HexColor("#FFD700"),  # Yellow – Developing Consistency
    3: colors.HexColor("#006400"),  # Green  – Secure and Steady
    4: colors.HexColor("#00008B"),  # Blue   – Strongly Engaged
    5: colors.HexColor("#800080"),  # Purple – Demonstrating Excellence
}

KEY_LABELS = {
    1: "1 – Requiring Support\n(Lack of effort)",
    2: "2 – Developing Consistency\n(Some effort)",
    3: "3 – Secure and Steady\n(Good effort)",
    4: "4 – Strongly Engaged\n(High levels of effort)",
    5: "5 – Demonstrating Excellence\n(Exceptional levels of effort)",
}


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def parse_effort_card(pdf_bytes: bytes) -> dict:
    """
    Extract student info and subject scores from a Medbury new-format PDF.

    Returns a dict:
        {
            "student": "Alexander Radecki",
            "year_level": "Year 8",
            "term": 2,
            "year": 2026,
            "subjects": [("Reading", 4), ("Writing", 4), ...]
        }
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        # --- Cover page: student info ---
        cover = pdf.pages[0].extract_text() or ""
        info = _parse_cover(cover)

        # --- Subject pages (skip cover + grading key) ---
        subjects = []
        for page in pdf.pages[2:]:
            text = page.extract_text() or ""
            subjects.extend(_parse_subject_page(text, info["term"]))

    info["subjects"] = subjects
    return info


def _parse_cover(text: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    term = 2
    year = 2026
    student = ""
    year_level = ""

    for line in lines:
        m = re.match(r"Term\s+(\d)\s+Effort Card", line, re.IGNORECASE)
        if m:
            term = int(m.group(1))
            continue
        if re.match(r"^\d{4}$", line):
            year = int(line)
            continue
        m = re.match(r"Year\s+(\d+)", line, re.IGNORECASE)
        if m:
            year_level = line
            continue
        if re.match(r"Homeroom|Medbury", line, re.IGNORECASE):
            continue
        if not student and re.match(r"[A-Z][a-z]+ [A-Z][a-z]+", line):
            student = line

    return {"student": student, "year_level": year_level, "term": term, "year": year}


def _parse_subject_page(text: str, term: int) -> list:
    """
    Parse one page of subject blocks.

    Each block has this structure:
        Subject Name      ← lines[i-2]
        Teacher Name      ← lines[i-1]
        Effort            ← lines[i]  (our anchor)
        End of year average N
        Term N Average N
        Weeks 1-4 N

    We anchor on the literal line "Effort" and look back two lines to find
    the subject name, skipping the teacher name in between.
    """
    subjects = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    for i, line in enumerate(lines):
        if line != "Effort" or i < 2:
            continue
        subject_name = lines[i - 2]
        if re.match(r"^\d", subject_name) or subject_name in ("Effort Card",):
            continue
        score = _find_term_score(lines, i + 1, term)
        if score is not None:
            subjects.append((subject_name, score))

    return subjects


def _find_term_score(lines: list, start: int, term: int) -> int | None:
    """
    Search forward for "Term N Average N". Falls back to "Weeks 1-4 N"
    if the term average row isn't present (e.g. early in the year).
    """
    term_pat  = re.compile(rf"Term\s+{term}\s+Average\s+(\d)", re.IGNORECASE)
    weeks_pat = re.compile(r"Weeks\s+1[-–]4\s+(\d)", re.IGNORECASE)
    fallback = None
    for j in range(start, min(start + 8, len(lines))):
        m = term_pat.match(lines[j])
        if m:
            score = int(m.group(1))
            return score if score in SCORE_COLORS else None
        m2 = weeks_pat.match(lines[j])
        if m2 and fallback is None:
            s = int(m2.group(1))
            fallback = s if s in SCORE_COLORS else None
    return fallback


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def build_color_pdf(data: dict) -> bytes:
    """Render the old-style color-coded table and return raw PDF bytes."""
    buf = io.BytesIO()

    MARGIN = 18 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )

    th  = ParagraphStyle("th",  fontName="Helvetica-Bold", fontSize=9,  alignment=TA_CENTER)
    num = ParagraphStyle("num", fontName="Helvetica-Bold", fontSize=9,  alignment=TA_CENTER)
    cell= ParagraphStyle("cell",fontName="Helvetica",      fontSize=9)
    hdr = ParagraphStyle("hdr", fontName="Helvetica-Bold", fontSize=13, spaceAfter=4)
    key = ParagraphStyle("key", fontName="Helvetica-Bold", fontSize=14)
    kl  = ParagraphStyle("kl",  fontName="Helvetica",      fontSize=8,  alignment=TA_CENTER)

    story = []

    year_num = data["year_level"].replace("Year", "").strip()
    story.append(Paragraph(
        f"<b>YEAR {year_num} &nbsp;&nbsp; {data['student']} &nbsp;&nbsp; "
        f"Term {data['term']}, {data['year']}</b>", hdr
    ))
    story.append(Spacer(1, 4 * mm))

    col_subj  = 72 * mm
    col_term  = 22 * mm
    col_widths = [col_subj] + [col_term] * 4

    header = [""] + [Paragraph(f"<b>Term {i}</b>", th) for i in range(1, 5)]
    nums   = [""] + [Paragraph(f"<b>{i}</b>", num)    for i in range(1, 5)]

    rows = [header, nums]
    for name, _ in data["subjects"]:
        rows.append([Paragraph(name, cell), "", "", "", ""])

    n_subj = len(data["subjects"])
    table = Table(
        rows,
        colWidths=col_widths,
        rowHeights=[10 * mm, 10 * mm] + [12 * mm] * n_subj,
    )

    term_col = data["term"]  # Term 1 → col 1, Term 2 → col 2, etc.

    ts = TableStyle([
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND",  (0, 0), (-1,  1), colors.white),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("ALIGN",       (0, 0), (0,  -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (0,  -1), 4),
    ])

    for i, (_, score) in enumerate(data["subjects"]):
        row = i + 2
        ts.add("BACKGROUND", (term_col, row), (term_col, row), SCORE_COLORS[score])
        for c in range(1, 5):
            if c != term_col:
                ts.add("BACKGROUND", (c, row), (c, row), colors.white)

    table.setStyle(ts)
    story.append(table)
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph("<b>KEY:</b>", key))
    story.append(Spacer(1, 4 * mm))

    key_data = [[""] * 5, [Paragraph(KEY_LABELS[i], kl) for i in range(1, 6)]]
    key_table = Table(key_data, colWidths=[36 * mm] * 5, rowHeights=[12 * mm, 20 * mm])
    kts = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
    ])
    for i in range(5):
        kts.add("BACKGROUND", (i, 0), (i, 0), SCORE_COLORS[i + 1])
        kts.add("BOX",        (i, 0), (i, 0), 0.5, colors.black)
    key_table.setStyle(kts)
    story.append(key_table)

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Medbury Effort Card Reformatter", page_icon="🏫")

st.title("Medbury Effort Card Reformatter")
st.write(
    "Upload a new-format Medbury effort card PDF and get back the "
    "old-style color-coded table."
)

uploaded = st.file_uploader("Upload effort card PDF", type="pdf")

if uploaded:
    with st.spinner("Parsing PDF…"):
        try:
            pdf_bytes = uploaded.read()
            data = parse_effort_card(pdf_bytes)
        except Exception as e:
            st.error(f"Could not parse the PDF: {e}")
            st.stop()

    st.subheader("Extracted data")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Student", data["student"] or "—")
    col2.metric("Year level", data["year_level"] or "—")
    col3.metric("Term", data["term"])
    col4.metric("Year", data["year"])

    if not data["subjects"]:
        st.error("No subjects found. Is this a Medbury effort card?")
        st.stop()

    color_names = {1: "Red", 2: "Yellow", 3: "Green", 4: "Blue", 5: "Purple"}
    rows = [{"Subject": s, "Score": sc, "Color": color_names.get(sc, str(sc))}
            for s, sc in data["subjects"]]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.spinner("Building color-coded PDF…"):
        try:
            pdf_out = build_color_pdf(data)
        except Exception as e:
            st.error(f"Could not build output PDF: {e}")
            st.stop()

    st.success("Done!")
    st.download_button(
        label="Download color-coded PDF",
        data=pdf_out,
        file_name=f"effort_card_{data['student'].replace(' ', '_')}_Term{data['term']}_{data['year']}.pdf",
        mime="application/pdf",
    )
