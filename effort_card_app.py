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

    Normal format returns:
        {"subjects": [("Reading", 4), ...], "split_term": False, ...}

    Split-term format (Weeks 1-4 + Weeks 5-8 instead of a Term Average) returns:
        {"subjects": [("Reading", 4, 3), ...], "split_term": True, ...}
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        cover = pdf.pages[0].extract_text() or ""
        info = _parse_cover(cover)

        # Concatenate all subject pages into one block so that subjects whose
        # scores overflow onto the next page are still parsed correctly.
        combined = "\n".join(page.extract_text() or "" for page in pdf.pages[2:])

        w58_pat = re.compile(r"Weeks\s+5[-–]8\s+\d", re.IGNORECASE)
        split_term = bool(w58_pat.search(combined))
        info["split_term"] = split_term

        if split_term:
            info["subjects"] = _parse_subject_page_split(combined)
        else:
            info["subjects"] = _parse_subject_page(combined, info["term"])

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


_INVALID_SUBJECT = re.compile(
    r"^\d|average|weeks|end of year|effort", re.IGNORECASE
)

def _valid_subject(name: str) -> bool:
    """Return True if the line looks like a real subject name."""
    return bool(name) and not _INVALID_SUBJECT.search(name)


def _parse_subject_page(text: str, term: int) -> list:
    """
    Parse subject blocks from the concatenated subject-page text.

    Each block:
        Subject Name      ← lines[i-2]
        Teacher Name      ← lines[i-1]
        Effort            ← lines[i]  (anchor)
        End of year average N
        Term N Average N
        Weeks 1-4 N
    """
    subjects = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    for i, line in enumerate(lines):
        if line != "Effort" or i < 2:
            continue
        subject_name = lines[i - 2]
        if not _valid_subject(subject_name):
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
    for j in range(start, min(start + 12, len(lines))):
        m = term_pat.match(lines[j])
        if m:
            score = int(m.group(1))
            return score if score in SCORE_COLORS else None
        m2 = weeks_pat.match(lines[j])
        if m2 and fallback is None:
            s = int(m2.group(1))
            fallback = s if s in SCORE_COLORS else None
    return fallback


def _parse_subject_page_split(text: str) -> list:
    """
    Parse split-term blocks (Weeks 1-4 + Weeks 5-8).
    Returns [(subject_name, score_w14, score_w58), ...]
    """
    subjects = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    for i, line in enumerate(lines):
        if line != "Effort" or i < 2:
            continue
        subject_name = lines[i - 2]
        if not _valid_subject(subject_name):
            continue
        w14, w58 = _find_weeks_scores(lines, i + 1)
        if w14 is not None or w58 is not None:
            subjects.append((subject_name, w14, w58))

    return subjects


def _find_weeks_scores(lines: list, start: int) -> tuple:
    """Return (weeks_1_4_score, weeks_5_8_score) from lines after 'Effort'."""
    w14_pat = re.compile(r"Weeks\s+1[-–]4\s+(\d)", re.IGNORECASE)
    w58_pat = re.compile(r"Weeks\s+5[-–]8\s+(\d)", re.IGNORECASE)
    w14 = w58 = None
    for j in range(start, min(start + 12, len(lines))):
        m = w14_pat.match(lines[j])
        if m and w14 is None:
            s = int(m.group(1))
            w14 = s if s in SCORE_COLORS else None
        m = w58_pat.match(lines[j])
        if m and w58 is None:
            s = int(m.group(1))
            w58 = s if s in SCORE_COLORS else None
    return w14, w58


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

    split = data.get("split_term", False)

    if split:
        col_labels = ["Term 2.1", "Term 2.2", "Term 3", "Term 4"]
        num_labels = ["2.1", "2.2", "3", "4"]
    else:
        col_labels = [f"Term {i}" for i in range(1, 5)]
        num_labels = [str(i) for i in range(1, 5)]

    header = [""] + [Paragraph(f"<b>{lbl}</b>", th) for lbl in col_labels]
    nums   = [""] + [Paragraph(f"<b>{lbl}</b>", num) for lbl in num_labels]

    rows = [header, nums]
    for entry in data["subjects"]:
        rows.append([Paragraph(entry[0], cell), "", "", "", ""])

    n_subj = len(data["subjects"])
    table = Table(
        rows,
        colWidths=col_widths,
        rowHeights=[10 * mm, 10 * mm] + [12 * mm] * n_subj,
    )

    ts = TableStyle([
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND",  (0, 0), (-1,  1), colors.white),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("ALIGN",       (0, 0), (0,  -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (0,  -1), 4),
    ])

    for i, entry in enumerate(data["subjects"]):
        row = i + 2
        if split:
            # entry = (name, score_w14, score_w58); col 1 = w14, col 2 = w58
            _, w14, w58 = entry
            ts.add("BACKGROUND", (1, row), (1, row), SCORE_COLORS[w14] if w14 else colors.white)
            ts.add("BACKGROUND", (2, row), (2, row), SCORE_COLORS[w58] if w58 else colors.white)
            ts.add("BACKGROUND", (3, row), (3, row), colors.white)
            ts.add("BACKGROUND", (4, row), (4, row), colors.white)
        else:
            # entry = (name, score); color the current term's column
            _, score = entry
            term_col = data["term"]
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

    with st.expander("Raw extracted text (for debugging)"):
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as _pdf:
            for _i, _page in enumerate(_pdf.pages):
                st.markdown(f"**Page {_i}**")
                st.code(_page.extract_text() or "(empty)")

    if not data["subjects"]:
        st.error("No subjects found. Is this a Medbury effort card?")
        st.stop()

    color_names = {1: "Red", 2: "Yellow", 3: "Green", 4: "Blue", 5: "Purple"}
    if data.get("split_term"):
        st.info("Split-term format detected: columns will show Term 2.1 (Weeks 1–4) and Term 2.2 (Weeks 5–8).")
        table_rows = [
            {"Subject": e[0],
             "Term 2.1 Score": e[1], "Term 2.1 Color": color_names.get(e[1], "—"),
             "Term 2.2 Score": e[2], "Term 2.2 Color": color_names.get(e[2], "—")}
            for e in data["subjects"]
        ]
    else:
        table_rows = [
            {"Subject": e[0], "Score": e[1], "Color": color_names.get(e[1], str(e[1]))}
            for e in data["subjects"]
        ]
    st.dataframe(table_rows, use_container_width=True, hide_index=True)

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
