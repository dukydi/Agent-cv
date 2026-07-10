import io
from pathlib import Path

import pdfplumber

from src.schemas import RawDocument


class ParsingError(Exception):
    pass


def parse_pdf_bytes(content: bytes, source_name: str) -> RawDocument:
    if not content:
        raise ParsingError(f"Contenu PDF vide : {source_name}")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n\n".join(
                (page.extract_text() or "") for page in pdf.pages
            ).strip()
    except Exception as e:
        raise ParsingError(f"Erreur lecture PDF {source_name} : {e}") from e
    if not text:
        raise ParsingError(f"PDF sans texte extractible : {source_name}")
    return RawDocument(source_kind="pdf", source_name=source_name, text=text)


def parse_pdf(path: str | Path) -> RawDocument:
    p = Path(path)
    if not p.exists():
        raise ParsingError(f"Fichier introuvable : {p}")
    if not p.is_file():
        raise ParsingError(f"N'est pas un fichier : {p}")
    if p.suffix.lower() != ".pdf":
        raise ParsingError(f"Extension attendue .pdf, reçu {p.suffix} : {p}")

    try:
        with pdfplumber.open(p) as pdf:
            text = "\n\n".join(
                (page.extract_text() or "") for page in pdf.pages
            ).strip()
    except ParsingError:
        raise
    except Exception as e:
        raise ParsingError(f"Erreur lecture PDF {p.name} : {e}") from e

    if not text:
        raise ParsingError(f"PDF sans texte extractible : {p.name}")

    return RawDocument(
        source_kind="pdf",
        source_name=p.name,
        text=text,
    )


def parse_text(text: str, source_name: str = "input.txt") -> RawDocument:
    cleaned = text.strip()
    if not cleaned:
        raise ParsingError(f"Texte vide : {source_name}")
    return RawDocument(
        source_kind="text",
        source_name=source_name,
        text=cleaned,
    )
