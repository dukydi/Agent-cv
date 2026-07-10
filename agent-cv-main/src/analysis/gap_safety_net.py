"""Garde-fou déterministe : rattrape les besoins critiques non signalés par le LLM.

Le prompt de Match+Reformulate demande au modèle de détecter et signaler les
`Need` critiques (deal_breaker ou must_have) qu'aucune expérience du RawCV ne
permet de couvrir. C'est une consigne, pas une vérification : le modèle peut
l'oublier. Cette fonction recoupe indépendamment le Brief et le RawCV, et
complète les signalements manquants — elle n'en retire jamais.
"""
import re
import unicodedata

from src.schemas import AdaptedCV, Brief, Need, RawCV


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def _is_demonstrated(need: Need, raw_cv: RawCV) -> bool:
    need_norm = _normalize(need.label)
    if not need_norm:
        return True

    haystacks: list[str] = []
    for skill in raw_cv.skills:
        haystacks.append(skill.label)
        haystacks.extend(skill.demonstree_par)
    for experience in raw_cv.experiences:
        haystacks.append(experience.titre)
        haystacks.append(experience.description_brute)
        haystacks.extend(experience.skills_utilisees)
        haystacks.extend(experience.realisations)

    for hay in haystacks:
        hay_norm = _normalize(hay)
        if hay_norm and (need_norm in hay_norm or hay_norm in need_norm):
            return True
    return False


def _already_flagged(label: str, needs_non_couverts: list[str], alertes: list[str]) -> bool:
    if label in needs_non_couverts:
        return True
    label_norm = _normalize(label)
    return any(label_norm in _normalize(alerte) for alerte in alertes)


def apply_gap_safety_net(brief: Brief, raw_cv: RawCV, adapted_cv: AdaptedCV) -> AdaptedCV:
    """Complète `coverage.needs_non_couverts` et `alertes_completude` pour les
    besoins critiques (deal_breaker ou must_have) qu'aucune expérience du
    RawCV ne démontre, et que le LLM n'a signalés dans aucun des deux champs.

    N'ajoute jamais de faux positif (un besoin réellement démontré n'est
    jamais signalé) et ne retire jamais un signalement existant. Retourne le
    même objet `adapted_cv` si rien n'est à ajouter.
    """
    critical_needs = [n for n in brief.needs if n.deal_breaker or n.priority == "must_have"]

    needs_non_couverts = list(adapted_cv.coverage.needs_non_couverts)
    alertes_completude = list(adapted_cv.alertes_completude)
    changed = False

    for need in critical_needs:
        if _is_demonstrated(need, raw_cv):
            continue
        if _already_flagged(need.label, needs_non_couverts, alertes_completude):
            continue
        needs_non_couverts.append(need.label)
        alertes_completude.append(f"[[À compléter : {need.label}]]")
        changed = True

    if not changed:
        return adapted_cv

    new_coverage = adapted_cv.coverage.model_copy(update={"needs_non_couverts": needs_non_couverts})
    return adapted_cv.model_copy(update={
        "coverage": new_coverage,
        "alertes_completude": alertes_completude,
    })
