"""Auto-shrink déterministe des shapes simples (en Python, sans LLM).

Quand le LLM produit un texte légèrement plus long que ce que la zone du
template peut visuellement accueillir, on réduit la `font.size` de chaque
run jusqu'à ce que le texte tienne. Le résultat est **figé dans le XML
PPTX**, donc identique sur tous les rendus (PowerPoint Windows/Mac,
LibreOffice, Office Online, export PDF) — contrairement à l'autofit natif
PowerPoint qui dépend du moteur de rendu.

Stratégie : mesurer la hauteur réelle via Pillow + TTF (`text_metrics`),
calculer le ratio nécessaire pour rentrer dans la zone, l'appliquer à
chaque run en une passe avec un floor (`min_size_pt`) pour éviter
l'illisibilité.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.util import Pt

from src.rendering.text_metrics import FontResolutionError, estimate_height_pt


# 1 pt = 12700 EMU (English Metric Units, l'unité interne PowerPoint)
EMU_PER_PT = 12700

DEFAULT_FONT_FAMILY = "Arial Nova Condensed"
DEFAULT_FONT_SIZE_PT = 11.0
DEFAULT_MIN_SIZE_PT = 8.0
DEFAULT_SAFETY_MARGIN = 0.98
# Les shapes simples n'ont pas de paragraph-spacing comme le bloc
# expériences : le line height effectif PowerPoint est plus proche de 1.2×
# la taille de police. Le ratio 1.4 utilisé par text_metrics est calibré
# pour le bloc hiérarchique avec puces et sera trop pessimiste ici.
SIMPLE_LINE_SPACING = 1.2


@dataclass(frozen=True)
class ShrinkResult:
    shrunk: bool
    ratio: float
    min_size_reached: bool
    fits_after: bool
    measured_before_pt: float
    measured_after_pt: float
    available_height_pt: float


def _emu_to_pt(emu: int | None) -> float:
    if emu is None:
        return 0.0
    return emu / EMU_PER_PT


def _effective_size_pt(run) -> float:
    if run.font.size is not None:
        return run.font.size.pt
    return DEFAULT_FONT_SIZE_PT


def _effective_family(run) -> str:
    return run.font.name or DEFAULT_FONT_FAMILY


def _safe_estimate_height(
    text: str, family: str, size_pt: float, max_width_pt: float, line_spacing: float
) -> float:
    # Le template peut contenir des fonts custom non installées localement
    # (ex: "Times New Roman" sur un poste sans cette font). On retombe alors
    # sur la font par défaut pour la mesure, sans bloquer.
    try:
        return estimate_height_pt(text, family, size_pt, max_width_pt, line_spacing=line_spacing)
    except FontResolutionError:
        return estimate_height_pt(
            text, DEFAULT_FONT_FAMILY, size_pt, max_width_pt, line_spacing=line_spacing
        )


def _measure_text_frame_height_pt(
    text_frame,
    available_width_pt: float,
    line_spacing: float,
    extra_per_paragraph_pt: float = 0.0,
) -> float:
    total = 0.0
    for para in text_frame.paragraphs:
        text = para.text
        if not text:
            continue
        runs = list(para.runs)
        if runs:
            size = _effective_size_pt(runs[0])
            family = _effective_family(runs[0])
        else:
            size = DEFAULT_FONT_SIZE_PT
            family = DEFAULT_FONT_FAMILY
        total += _safe_estimate_height(text, family, size, available_width_pt, line_spacing)
        # PowerPoint applique un paragraph-spacing entre les paragraphes
        # (space_before/after dans le style). Pillow ne le voit pas — on
        # l'ajoute manuellement, configurable par l'appelant.
        total += extra_per_paragraph_pt
    return total


def shrink_text_frame_to_fit(
    shape,
    *,
    min_size_pt: float = DEFAULT_MIN_SIZE_PT,
    safety_margin: float = DEFAULT_SAFETY_MARGIN,
    line_spacing: float = SIMPLE_LINE_SPACING,
    overflow_tolerance: float = 1.02,
    extra_per_paragraph_pt: float = 0.0,
    available_height_pt: float | None = None,
) -> ShrinkResult | None:
    """Réduit la taille de police des runs du shape pour que le texte rentre
    dans la zone visible. Retourne `None` si le shape n'a pas de text frame
    ou si le texte tient déjà ; sinon retourne un `ShrinkResult`.

    `available_height_pt` : hauteur utile de référence (déjà nette des marges
    haut/bas). À fournir quand la hauteur stockée du shape n'est pas fiable —
    typiquement les shapes en autofit `SHAPE_TO_FIT_TEXT`, dont la hauteur XML
    correspond au dernier contenu enregistré, pas à la zone réellement visible.
    Si omis, on déduit la zone de `shape.height` moins ses marges.
    """
    if not shape.has_text_frame:
        return None

    tf = shape.text_frame

    width_pt = _emu_to_pt(shape.width)
    margin_l = _emu_to_pt(tf.margin_left)
    margin_r = _emu_to_pt(tf.margin_right)
    available_width = max(1.0, width_pt - margin_l - margin_r)

    if available_height_pt is not None:
        available_height = max(1.0, available_height_pt * safety_margin)
    else:
        height_pt = _emu_to_pt(shape.height)
        margin_t = _emu_to_pt(tf.margin_top)
        margin_b = _emu_to_pt(tf.margin_bottom)
        available_height = max(1.0, (height_pt - margin_t - margin_b) * safety_margin)

    measured_before = _measure_text_frame_height_pt(
        tf, available_width, line_spacing, extra_per_paragraph_pt
    )

    # Tolérance de bruit de mesure (par défaut 2%, configurable par appelant) :
    # Pillow estime un peu de travers selon la font/wrapping/rendering exact
    # PowerPoint. En dessous de cette marge on n'agit pas, pour éviter du
    # bruit (réductions de police invisibles à l'œil).
    if measured_before <= available_height * overflow_tolerance:
        return None

    # Pillow surestime souvent un peu la hauteur (line spacing 1.4 calibré
    # pour le bloc expériences). On vise le ratio direct, le floor par run
    # garantit la lisibilité.
    ratio = available_height / measured_before
    min_reached = False

    for para in tf.paragraphs:
        for run in para.runs:
            current = _effective_size_pt(run)
            new_pt = current * ratio
            if new_pt < min_size_pt:
                new_pt = min_size_pt
                min_reached = True
            # Arrondi à 0.5 pt près pour éviter des tailles bizarres en XML
            new_pt = round(new_pt * 2) / 2
            run.font.size = Pt(new_pt)

    measured_after = _measure_text_frame_height_pt(
        tf, available_width, line_spacing, extra_per_paragraph_pt
    )
    return ShrinkResult(
        shrunk=True,
        ratio=round(ratio, 3),
        min_size_reached=min_reached,
        fits_after=measured_after <= available_height,
        measured_before_pt=round(measured_before, 1),
        measured_after_pt=round(measured_after, 1),
        available_height_pt=round(available_height, 1),
    )
