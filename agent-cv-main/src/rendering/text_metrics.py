"""Mesure de hauteur de texte rendu via Pillow + font TTF.

Usage : estimer la hauteur en points qu'occupera un texte dans un text frame
PowerPoint donné, avec un wrapping word-by-word identique à celui de PPT.

La précision dépend de la font utilisée. Stratégie de fallback :
1. Arial Nova Condensed (la vraie font du template, sur Windows 10+)
2. Arial Narrow (largeur similaire, présente sur tout Windows)
3. Arial (surestime un peu, mais safe)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


# Conversion : 1 pt = 1.333... px à 96 DPI (résolution PowerPoint standard)
PT_TO_PX = 96 / 72
# Calibré empiriquement contre le rendu PowerPoint réel : pour la font
# Arial Nova Condensed à 9.5 pt, la hauteur effective d'une ligne (avec
# ascender + descender + leading natif) est ~1.4× la taille de police.
# Une valeur trop basse (1.2) fait sous-estimer la hauteur et donne un
# packer trop laxiste.
LINE_SPACING_RATIO = 1.4

# Ordre de fallback pour la résolution de fonts
_FALLBACK_FAMILIES = {
    "Arial Nova Condensed": [
        "ARIALNNV.TTF", "ariannv.ttf", "ArialNovaCond.ttf",
        "ARIALN.TTF", "arialn.ttf", "Arial Narrow.ttf",
        "arial.ttf", "ARIAL.TTF",
    ],
    "Arial Nova": [
        "ARIALN.TTF", "arialnv.ttf",
        "arial.ttf", "ARIAL.TTF",
    ],
    "Arial": [
        "arial.ttf", "ARIAL.TTF",
    ],
    "Calibri": [
        "calibri.ttf", "CALIBRI.TTF",
        "arial.ttf",
    ],
}

_WINDOWS_FONT_DIRS = [
    Path("C:/Windows/Fonts"),
    Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
]
_LINUX_FONT_DIRS = [
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
]
_BUNDLED_FONTS_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"


class FontResolutionError(RuntimeError):
    pass


@lru_cache(maxsize=64)
def _resolve_font_path(family: str) -> Path:
    candidates = _FALLBACK_FAMILIES.get(family, [f"{family}.ttf"])
    search_dirs: list[Path] = []
    if _BUNDLED_FONTS_DIR.exists():
        search_dirs.append(_BUNDLED_FONTS_DIR)
    search_dirs.extend(d for d in _WINDOWS_FONT_DIRS if d.exists())
    search_dirs.extend(d for d in _LINUX_FONT_DIRS if d.exists())

    for candidate in candidates:
        for directory in search_dirs:
            for path in directory.rglob(candidate):
                if path.is_file():
                    return path

    raise FontResolutionError(
        f"Aucune font trouvable pour {family!r}. Cherché : {candidates} "
        f"dans {[str(d) for d in search_dirs]}"
    )


@lru_cache(maxsize=128)
def _load_font(family: str, size_pt: float) -> ImageFont.FreeTypeFont:
    path = _resolve_font_path(family)
    size_px = int(round(size_pt * PT_TO_PX))
    return ImageFont.truetype(str(path), size_px)


def _measure_text_width_px(text: str, font: ImageFont.FreeTypeFont) -> float:
    if not text:
        return 0.0
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def wrap_text(text: str, family: str, size_pt: float, max_width_pt: float) -> list[str]:
    """Word-wrap un texte selon la largeur max disponible (en pt). Retourne
    la liste des lignes."""
    if not text:
        return [""]
    font = _load_font(family, size_pt)
    max_width_px = max_width_pt * PT_TO_PX

    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip() if current else word
        if _measure_text_width_px(test, font) <= max_width_px:
            current = test
        else:
            if current:
                lines.append(current)
                current = word
            else:
                # Mot seul plus large que la zone : on le force tout de même.
                lines.append(word)
                current = ""
    if current:
        lines.append(current)
    return lines


def estimate_height_pt(
    text: str,
    family: str,
    size_pt: float,
    max_width_pt: float,
    line_spacing: float = LINE_SPACING_RATIO,
) -> float:
    """Estime la hauteur en points qu'occupera un texte après wrapping."""
    if not text:
        return 0.0
    lines = wrap_text(text, family, size_pt, max_width_pt)
    line_height_pt = size_pt * line_spacing
    return len(lines) * line_height_pt
