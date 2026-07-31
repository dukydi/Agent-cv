import io
from copy import deepcopy
from dataclasses import replace as _dc_replace

from pptx import Presentation
from pptx.oxml.ns import qn

from src.config import GOLDEN_TEMPLATE_PATH
from src.rendering.auto_shrink import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE_PT,
    DEFAULT_SAFETY_MARGIN,
    EMU_PER_PT,
    SIMPLE_LINE_SPACING,
    shrink_text_frame_to_fit,
)
from src.rendering.layout_budget import DEFAULT_EXPERIENCES_LAYOUT, ExperiencesBlockLayout
from src.rendering.packer import pack
from src.rendering.text_metrics import FontResolutionError, wrap_text
from src.schemas import AdaptedCV, Consultant, RenderConstraints, RenderOutput


PH_NOM = "{d. nom_consultant}"
PH_GRADE_EXP = "{d. grade_experience}"
PH_RESUME = "{d. resume_profil}"
PH_FORMATION = "{d. formation}"
PH_COMPS = tuple(f"{{d. comp_{i}}}" for i in range(1, 10))
PH_DOMAINE = "{d. domaine}"
PH_MISSION = "{d. mission}"
PH_REALISATION = "{d. realisation}"

EXPERIENCES_SHAPE_INDEX = 8


def _signal_overflow(value: str, max_chars: int, label: str, truncations: list[str]) -> str:
    # Ne tronque PAS : signale juste le dépassement. L'auto-shrink Python
    # déterministe (rendering/auto_shrink.py) appliqué après injection
    # réduira la taille de police pour faire tenir, ce qui évite les "…"
    # disgracieux dans le livrable.
    if not value or len(value) <= max_chars:
        return value
    if value.startswith("[[À compléter"):
        return value
    truncations.append(
        f"{label} dépasse {max_chars} caractères (était {len(value)}) — auto-shrink à venir"
    )
    return value


def _build_formation_text(consultant: Consultant) -> str:
    formations = consultant.formation or []
    return " | ".join(formations) if formations else "[[À compléter : formation]]"


def _build_grade_experience(consultant: Consultant) -> str:
    grade = consultant.grade
    n = consultant.annees_experience
    if grade and n is not None:
        return f"{grade} – {n} ans d'expérience"
    if grade:
        return grade
    if n is not None:
        return f"{n} ans d'expérience"
    return "[[À compléter : grade et expérience]]"


def _build_simple_mapping(
    adapted: AdaptedCV,
    constraints: RenderConstraints,
    truncations: list[str],
) -> dict[str, str]:
    consultant = adapted.consultant

    nom = consultant.nom or "[[À compléter : nom du consultant]]"
    grade_exp = _build_grade_experience(consultant)
    resume = adapted.resume_profil or ""
    formation_text = _build_formation_text(consultant)

    mapping: dict[str, str] = {
        PH_NOM: _signal_overflow(nom, constraints.max_chars_nom, "nom_consultant", truncations),
        PH_GRADE_EXP: _signal_overflow(grade_exp, constraints.max_chars_grade, "grade_experience", truncations),
        PH_RESUME: _signal_overflow(resume, constraints.max_chars_resume, "resume_profil", truncations),
        PH_FORMATION: _signal_overflow(formation_text, constraints.max_chars_formation_line, "formation", truncations),
    }

    skills = list(adapted.skills[: constraints.max_skills])
    for i, ph in enumerate(PH_COMPS[: constraints.max_skills]):
        if i < len(skills):
            mapping[ph] = _signal_overflow(
                skills[i].label, constraints.max_chars_skill_label, f"comp_{i + 1}", truncations
            )
        else:
            mapping[ph] = ""

    return mapping


def _set_paragraph_text(p_element, text: str) -> None:
    runs = p_element.findall(qn("a:r"))
    if not runs:
        return
    t = runs[0].find(qn("a:t"))
    if t is not None:
        t.text = text
    for r in runs[1:]:
        p_element.remove(r)


def _set_space_before_pt(p_element, pts: float) -> None:
    """Fixe l'espace AVANT le paragraphe (en points), dans le XML. Sert à
    aérer les blocs domaines : un espace au-dessus de chaque `{d. domaine}`
    = un espace entre les blocs. Respecte l'ordre de schéma DrawingML du
    `a:pPr` (spcBef se place après un éventuel a:lnSpc)."""
    pPr = p_element.find(qn("a:pPr"))
    if pPr is None:
        pPr = p_element.makeelement(qn("a:pPr"), {})
        p_element.insert(0, pPr)
    for old in pPr.findall(qn("a:spcBef")):
        pPr.remove(old)
    spc_bef = pPr.makeelement(qn("a:spcBef"), {})
    spc_pts = pPr.makeelement(qn("a:spcPts"), {"val": str(int(round(pts * 100)))})
    spc_bef.append(spc_pts)
    ln_spc = pPr.find(qn("a:lnSpc"))
    if ln_spc is not None:
        ln_spc.addnext(spc_bef)
    else:
        pPr.insert(0, spc_bef)


def _replace_in_paragraph_simple(paragraph, mapping: dict[str, str]) -> str | None:
    full = paragraph.text
    for key, value in mapping.items():
        if key not in full:
            continue
        new_text = full.replace(key, value)
        runs = paragraph.runs
        if not runs:
            return None
        runs[0].text = new_text
        for run in runs[1:]:
            run._r.getparent().remove(run._r)
        return key
    return None


def _render_simple_shapes(
    slide,
    mapping: dict[str, str],
    fields_rendered: dict[str, str],
    truncations: list[str],
) -> None:
    for i, shape in enumerate(slide.shapes):
        if i == EXPERIENCES_SHAPE_INDEX:
            continue
        if not shape.has_text_frame:
            continue
        replaced_in_shape: list[str] = []
        for paragraph in list(shape.text_frame.paragraphs):
            replaced = _replace_in_paragraph_simple(paragraph, mapping)
            if replaced is not None:
                fields_rendered[replaced] = mapping[replaced]
                replaced_in_shape.append(replaced)
        # Auto-shrink déterministe : si le texte dépasse la zone visible, on
        # réduit la taille de police de chaque run. Résultat figé dans le
        # XML, donc identique sur tous les rendus (PPT/LibreOffice/PDF).
        if replaced_in_shape:
            result = shrink_text_frame_to_fit(shape)
            if result is not None:
                truncations.append(
                    f"auto-shrink shape[{i}] ({', '.join(replaced_in_shape)}) : "
                    f"ratio {result.ratio}"
                    + (" — taille min atteinte" if result.min_size_reached else "")
                )


def _extract_paragraph_templates(text_frame):
    """Identifie les 3 paragraphes-modèles (domaine, mission, réalisation)
    par le placeholder qu'ils contiennent. Retourne 3 deepcopies."""
    p_domaine = p_mission = p_real = None
    for p in text_frame.paragraphs:
        text = p.text
        if PH_DOMAINE in text and p_domaine is None:
            p_domaine = deepcopy(p._p)
        elif PH_MISSION in text and p_mission is None:
            p_mission = deepcopy(p._p)
        elif PH_REALISATION in text and p_real is None:
            p_real = deepcopy(p._p)
    return p_domaine, p_mission, p_real


def _shrink_experiences_shape_if_overflow(
    shape, layout: ExperiencesBlockLayout, truncations: list[str]
) -> None:
    # Filet de sécurité visuel sur le shape [8] : ne se déclenche que si le
    # contenu déborde RÉELLEMENT la zone visible. Calibré conservateur pour
    # éviter les faux positifs (auto-shrink qui réduit la police alors que
    # le contenu tient).
    #
    #   - available_height_pt = budget réel du bloc (layout, ~414 pt). On NE
    #     mesure PAS contre `shape.height` : ce shape est en autofit
    #     SHAPE_TO_FIT_TEXT et sa hauteur stockée (~53 pt) ne reflète que le
    #     contenu du template, pas la zone visible. Sans ça, le filet croit à
    #     un débordement massif et écrase la police au plancher (8 pt) à chaque
    #     rendu — alors que le packer a déjà calibré le contenu pour ~9.5 pt.
    #   - line_spacing = 1.15 : rendu PowerPoint des bullets level 1 à 9-9.5 pt
    #     (le packer utilise 1.4, volontairement pessimiste pour l'élagage).
    #   - safety_margin = 1.00 : jusqu'à 100 % de la hauteur visible.
    #   - tolérance d'overflow = 1.05 : 5 % de marge pour absorber le bruit de
    #     la mesure Pillow avant de réduire la police.
    # Le shape [8] a 27 paragraphes typiquement, avec un paragraph-spacing
    # PowerPoint visible (3-5pt entre chaque). Pillow l'ignore par défaut,
    # on l'ajoute manuellement pour mesurer juste.
    result = shrink_text_frame_to_fit(
        shape,
        safety_margin=1.00,
        line_spacing=1.15,
        overflow_tolerance=1.05,
        extra_per_paragraph_pt=3.5,
        available_height_pt=layout.effective_height_pt,
    )
    if result is not None:
        truncations.append(
            f"auto-shrink shape[{EXPERIENCES_SHAPE_INDEX}] (expériences) : "
            f"ratio {result.ratio}"
            + (" — taille min atteinte" if result.min_size_reached else "")
        )


def _render_experiences_block(
    shape,
    adapted: AdaptedCV,
    constraints: RenderConstraints,
    layout: ExperiencesBlockLayout,
    truncations: list[str],
    fields_rendered: dict[str, str],
) -> None:
    tf = shape.text_frame
    txBody = tf._txBody

    p_domaine, p_mission, p_real = _extract_paragraph_templates(tf)
    if p_domaine is None or p_mission is None or p_real is None:
        truncations.append(
            "Modèles de paragraphes manquants dans le shape expériences"
        )
        return

    for p in list(txBody.findall(qn("a:p"))):
        txBody.remove(p)

    # Le packer a déjà élagué l'AdaptedCV pour qu'il rentre. On rend tel quel
    # sans tronquer (les longueurs unitaires sont gérées par le packer ou par
    # le LLM en amont).
    experiences = sorted(adapted.experiences, key=lambda e: e.position)

    n_dom = n_mis = n_real = 0
    for exp in experiences:
        new_p = deepcopy(p_domaine)
        _set_paragraph_text(new_p, exp.domaine)
        # Aère les blocs : espace au-dessus de chaque domaine sauf le premier
        # (= espace entre blocs). Aligné sur le budget réservé par le packer.
        if n_dom > 0 and layout.space_before_new_domaine_pt > 0:
            _set_space_before_pt(new_p, layout.space_before_new_domaine_pt)
        txBody.append(new_p)
        n_dom += 1

        for mis in exp.missions:
            new_p = deepcopy(p_mission)
            _set_paragraph_text(new_p, mis.description_courte)
            txBody.append(new_p)
            n_mis += 1

            for real in mis.realisations:
                new_p = deepcopy(p_real)
                _set_paragraph_text(new_p, real)
                txBody.append(new_p)
                n_real += 1

    fields_rendered[PH_DOMAINE] = f"{n_dom} domaine(s)"
    fields_rendered[PH_MISSION] = f"{n_mis} mission(s)"
    fields_rendered[PH_REALISATION] = f"{n_real} réalisation(s)"


# Au-delà de ce nombre de lignes, la formation retombe sur l'auto-shrink
# (cas extrême : on ne réserve pas plus de 2 lignes pour ne pas trop grignoter
# la zone expériences).
MAX_FORMATION_LINES = 2
# Tolérance horizontale pour rattacher au "bloc bas-droite" les shapes alignées
# sous la formation (bandeau « Expériences significatives », connecteurs, bloc
# expériences) qu'il faut décaler ensemble.
_RIGHT_COLUMN_LEFT_MARGIN_PT = 60.0


def _find_formation_shape(slide):
    for shape in slide.shapes:
        if shape.has_text_frame and PH_FORMATION in shape.text_frame.text:
            return shape
    return None


def _nominal_run_font(shape) -> tuple[float, str]:
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            size = run.font.size.pt if run.font.size is not None else DEFAULT_FONT_SIZE_PT
            family = run.font.name or DEFAULT_FONT_FAMILY
            return size, family
    return DEFAULT_FONT_SIZE_PT, DEFAULT_FONT_FAMILY


def _count_wrapped_lines(text: str, family: str, size_pt: float, width_pt: float) -> int:
    try:
        return len(wrap_text(text, family, size_pt, width_pt))
    except FontResolutionError:
        return len(wrap_text(text, DEFAULT_FONT_FAMILY, size_pt, width_pt))


def _apply_dynamic_formation_layout(
    slide,
    formation_text: str,
    truncations: list[str],
) -> ExperiencesBlockLayout:
    """Si la formation déborde une ligne au corps nominal, agrandit sa zone et
    décale le bloc bas-droite (bandeau + expériences) vers le bas — au lieu de
    laisser l'auto-shrink réduire la police. Retourne le layout du bloc
    expériences, dont la hauteur disponible est réduite d'autant (le bas reste
    calé sur la marge basse de la slide).
    """
    shape = _find_formation_shape(slide)
    if shape is None:
        return DEFAULT_EXPERIENCES_LAYOUT

    tf = shape.text_frame
    size_pt, family = _nominal_run_font(shape)
    margin_l = (tf.margin_left or 0) / EMU_PER_PT
    margin_r = (tf.margin_right or 0) / EMU_PER_PT
    margin_t = (tf.margin_top or 0) / EMU_PER_PT
    margin_b = (tf.margin_bottom or 0) / EMU_PER_PT
    available_width = max(1.0, (shape.width or 0) / EMU_PER_PT - margin_l - margin_r)

    n_lines = _count_wrapped_lines(formation_text, family, size_pt, available_width)
    if n_lines <= 1:
        return DEFAULT_EXPERIENCES_LAYOUT

    # Hauteur intérieure visée pour `capped` lignes au corps nominal, avec une
    # marge (1.05 / safety) pour que l'auto-shrink générique ne se déclenche pas.
    capped = min(n_lines, MAX_FORMATION_LINES)
    line_h = size_pt * SIMPLE_LINE_SPACING
    needed_inner = capped * line_h * 1.05 / DEFAULT_SAFETY_MARGIN
    orig_height = (shape.height or 0) / EMU_PER_PT
    delta = max(0.0, needed_inner + margin_t + margin_b - orig_height)
    if delta <= 0.0:
        return DEFAULT_EXPERIENCES_LAYOUT

    delta_emu = int(round(delta * EMU_PER_PT))
    formation_id = shape.shape_id
    formation_top = shape.top or 0
    formation_left = shape.left or 0
    left_threshold = formation_left - int(round(_RIGHT_COLUMN_LEFT_MARGIN_PT * EMU_PER_PT))

    # Agrandit la zone formation pour accueillir la 2e ligne.
    shape.height = (shape.height or 0) + delta_emu

    # Décale vers le bas le bloc bas-droite (bandeau, connecteurs, expériences)
    # pour préserver leurs positions relatives. NB : `slide.shapes[i]` renvoie
    # un nouvel objet à chaque accès — on compare donc par `shape_id`, pas par
    # identité Python.
    for other in slide.shapes:
        if other.shape_id == formation_id:
            continue
        if (other.left or 0) >= left_threshold and (other.top or 0) >= formation_top:
            other.top = (other.top or 0) + delta_emu

    # Réduit d'autant le budget de hauteur du bloc expériences.
    layout = _dc_replace(
        DEFAULT_EXPERIENCES_LAYOUT,
        available_height_pt=DEFAULT_EXPERIENCES_LAYOUT.available_height_pt - delta,
    )

    if n_lines > MAX_FORMATION_LINES:
        truncations.append(
            f"formation sur {n_lines} lignes (> {MAX_FORMATION_LINES}) — "
            f"zone agrandie à {MAX_FORMATION_LINES} lignes, auto-shrink résiduel"
        )
    else:
        truncations.append(
            f"formation sur {n_lines} lignes — zone agrandie de {round(delta, 1)} pt, "
            f"bloc expériences décalé (police nominale conservée)"
        )
    return layout


def render(adapted: AdaptedCV, constraints: RenderConstraints) -> RenderOutput:
    truncations: list[str] = []

    prs = Presentation(GOLDEN_TEMPLATE_PATH)
    slide = prs.slides[0]

    # Étape 0 — layout dynamique de la formation (AVANT le packer). Si la
    # formation déborde une ligne au corps nominal, on agrandit sa zone et on
    # décale le bloc expériences vers le bas (police conservée), et le budget
    # de hauteur du packer est réduit d'autant.
    formation_text = _build_formation_text(adapted.consultant)
    exp_layout = _apply_dynamic_formation_layout(slide, formation_text, truncations)

    # Étape 1 — packer le bloc expériences pour qu'il tienne dans la zone du
    # template (budget éventuellement réduit). Élagage équilibré et déterministe.
    packed_cv, pack_journal = pack(adapted, exp_layout)
    truncations.extend(f"packer: élagué {label}" for label in pack_journal)

    # Étape 2 — construire les mappings pour les zones simples (qui sont
    # tronquées si nécessaire selon RenderConstraints).
    mapping = _build_simple_mapping(packed_cv, constraints, truncations)

    fields_rendered: dict[str, str] = {}
    _render_simple_shapes(slide, mapping, fields_rendered, truncations)

    if (
        len(slide.shapes) > EXPERIENCES_SHAPE_INDEX
        and slide.shapes[EXPERIENCES_SHAPE_INDEX].has_text_frame
    ):
        exp_shape = slide.shapes[EXPERIENCES_SHAPE_INDEX]
        _render_experiences_block(
            exp_shape,
            packed_cv,
            constraints,
            exp_layout,
            truncations,
            fields_rendered,
        )
        # Filet de sécurité visuel : si malgré le packer le bloc déborde,
        # réduction proportionnelle des polices (préserve la hiérarchie
        # domaine/mission/réalisation). Mesuré contre le budget réel
        # (`exp_layout`), pas la hauteur stockée du shape autofit.
        _shrink_experiences_shape_if_overflow(exp_shape, exp_layout, truncations)

    buffer = io.BytesIO()
    prs.save(buffer)
    return RenderOutput(
        pptx_bytes=buffer.getvalue(),
        fields_rendered=fields_rendered,
        truncations=truncations,
    )
