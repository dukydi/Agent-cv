"""Convertit les CV texte du golden set en PDF minimal (fpdf2), pour le sanity check CLI.

Usage : python scripts/golden_set_txt_to_pdf.py
"""
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent / "golden_set"
ARIAL_TTF = Path(r"C:\Windows\Fonts\arial.ttf")


def txt_to_pdf(txt_path: Path, pdf_path: Path) -> None:
    text = txt_path.read_text(encoding="utf-8")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("Arial", fname=str(ARIAL_TTF))
    pdf.set_font("Arial", size=11)
    for line in text.split("\n"):
        pdf.set_x(pdf.l_margin)
        if not line.strip():
            pdf.ln(6)
            continue
        pdf.multi_cell(0, 6, line)
    pdf.output(str(pdf_path))


def main() -> None:
    cv_files = sorted(ROOT.glob("cas_*/cv/cv_v*.txt"))
    for txt_path in cv_files:
        pdf_path = txt_path.with_suffix(".pdf")
        txt_to_pdf(txt_path, pdf_path)
        print(f"{txt_path} -> {pdf_path}")


if __name__ == "__main__":
    main()
