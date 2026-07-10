"""Algorithme adaptatif du bloc expériences (shape [8]).

Stratégie "round-robin équilibré" (construction par addition) :

1. **Squelette** — pour chaque domaine (par priorité ascendante), ajouter
   le minimum (1 mission × 1 réa). Si un domaine ne tient plus, on
   l'abandonne (et les suivants, moins prioritaires).

2. **Round-robin de remplissage** — distribuer les éléments restants par
   tours pour équilibrer le rendu visuel :
   - Tour A : ajouter réa 2 de mission 1 pour chaque domaine retenu (dans
     l'ordre des priorités), puis réa 3, réa 4, ...
   - Tour B : ajouter mission 2 pour chaque domaine (avec sa 1ère réa),
     puis remplir mission 2 réa par réa, round-robin.
   - Et ainsi de suite.

   Si une addition ferait dépasser le budget, on saute cet élément et on
   continue d'essayer les suivants (au cas où un texte plus court tiendrait).

Comparé au "fill-first pur" (qui saturait le domaine 1 avant de toucher
au 2), cette stratégie produit un CV visuellement équilibré : chaque
domaine reçoit un nombre comparable de réalisations.

Squelette minimum garanti : si même (1 domaine × 1 mission × 1 réa)
déborde théoriquement, on le conserve quand même.
"""

from __future__ import annotations

from src.rendering.layout_budget import DEFAULT_EXPERIENCES_LAYOUT, ExperiencesBlockLayout
from src.rendering.text_metrics import estimate_height_pt
from src.schemas import AdaptedCV, AdaptedExperience, Mission


def measure_block_height(
    adapted: AdaptedCV,
    layout: ExperiencesBlockLayout = DEFAULT_EXPERIENCES_LAYOUT,
) -> float:
    total = 0.0
    for i, exp in enumerate(_sorted_experiences(adapted)):
        if i > 0:
            total += layout.space_before_new_domaine_pt
        total += estimate_height_pt(
            exp.domaine,
            layout.font_family,
            layout.font_size_pt,
            layout.width_level0_pt,
        )
        total += layout.space_after_domaine_pt

        for mis in exp.missions:
            total += estimate_height_pt(
                mis.description_courte,
                layout.font_family,
                layout.font_size_pt,
                layout.width_level0_pt,
            )
            total += layout.space_after_mission_pt
            for real in mis.realisations:
                total += estimate_height_pt(
                    real,
                    layout.font_family,
                    layout.font_size_pt,
                    layout.width_level1_pt,
                )
                total += layout.space_after_realisation_pt
    return total


def _sorted_experiences(adapted: AdaptedCV) -> list[AdaptedExperience]:
    return sorted(adapted.experiences, key=lambda e: e.position)


def _make_skeleton_experience(source: AdaptedExperience) -> AdaptedExperience | None:
    if not source.missions:
        return None
    first_mis = source.missions[0]
    if not first_mis.realisations:
        return None
    return AdaptedExperience(
        domaine=source.domaine,
        missions=[
            Mission(
                client=first_mis.client,
                description_courte=first_mis.description_courte,
                realisations=[first_mis.realisations[0]],
            )
        ],
        score=source.score,
        position=source.position,
        mapping_besoins=list(source.mapping_besoins),
    )


def pack(
    adapted: AdaptedCV,
    layout: ExperiencesBlockLayout = DEFAULT_EXPERIENCES_LAYOUT,
) -> tuple[AdaptedCV, list[str]]:
    """Remplit le bloc expériences en round-robin équilibré sur les domaines.
    Retourne (cv_pack, journal) où journal liste les éléments refusés."""
    cv = adapted.model_copy(deep=True)
    journal: list[str] = []
    budget = layout.effective_height_pt
    all_sources = _sorted_experiences(cv)
    cv.experiences = []

    if not all_sources:
        return cv, journal

    # ── PHASE 1 — Squelette par priorité ascendante.
    # On garde la liste des sources "actives" (celles dont le squelette tient).
    sources: list[AdaptedExperience] = []
    for idx, source in enumerate(all_sources):
        skeleton = _make_skeleton_experience(source)
        if skeleton is None:
            continue

        cv.experiences.append(skeleton)
        sources.append(source)

        if measure_block_height(cv, layout) > budget:
            if len(cv.experiences) == 1:
                # Squelette minimum garanti : on garde même si ça déborde.
                break
            cv.experiences.pop()
            sources.pop()
            journal.append(
                f"domaine '{source.domaine}' refusé (budget plein au squelette)"
            )
            for remaining in all_sources[idx + 1 :]:
                journal.append(
                    f"domaine '{remaining.domaine}' refusé (budget plein)"
                )
            break

    if not cv.experiences:
        return cv, journal

    # ── PHASE 2 — Round-robin de remplissage.
    # Stratégie : on alterne entre les domaines tour par tour.

    # Étape 2A : remplir les réalisations supplémentaires de la mission 1
    # de chaque domaine, round-robin.
    max_reals_m1 = max(len(s.missions[0].realisations) for s in sources)
    for r_idx in range(1, max_reals_m1):
        for d_idx, source in enumerate(sources):
            mis_in = source.missions[0]
            if r_idx >= len(mis_in.realisations):
                continue
            mis_out = cv.experiences[d_idx].missions[0]
            real = mis_in.realisations[r_idx]
            mis_out.realisations.append(real)
            if measure_block_height(cv, layout) > budget:
                mis_out.realisations.pop()
                journal.append(
                    f"réalisation refusée domaine {source.position} mission 1"
                )

    # Étape 2B : pour chaque mission supplémentaire (m=1, 2, ...), ajouter la
    # mission à chaque domaine round-robin, puis remplir ses réa round-robin.
    max_missions = max(len(s.missions) for s in sources)
    for m_idx in range(1, max_missions):
        # 2B.1 — Ajouter mission m_idx à chaque domaine (avec sa 1ère réa).
        for d_idx, source in enumerate(sources):
            if m_idx >= len(source.missions):
                continue
            mis_in = source.missions[m_idx]
            if not mis_in.realisations:
                continue
            new_mis = Mission(
                client=mis_in.client,
                description_courte=mis_in.description_courte,
                realisations=[mis_in.realisations[0]],
            )
            cv.experiences[d_idx].missions.append(new_mis)
            if measure_block_height(cv, layout) > budget:
                cv.experiences[d_idx].missions.pop()
                journal.append(
                    f"mission '{mis_in.client}' refusée (domaine {source.position})"
                )

        # 2B.2 — Remplir les réa supplémentaires de mission m_idx, round-robin.
        valid_max_reals = [
            len(source.missions[m_idx].realisations)
            for source in sources
            if m_idx < len(source.missions)
        ]
        if not valid_max_reals:
            continue
        max_reals_m = max(valid_max_reals)
        for r_idx in range(1, max_reals_m):
            for d_idx, source in enumerate(sources):
                if m_idx >= len(source.missions):
                    continue
                mis_in = source.missions[m_idx]
                if r_idx >= len(mis_in.realisations):
                    continue
                # Trouver la mission m_idx dans la sortie (peut ne pas avoir
                # été ajoutée si le budget l'a refusée).
                exp_out = cv.experiences[d_idx]
                target_mis_out = None
                for mis_out in exp_out.missions:
                    if mis_out.client == mis_in.client:
                        target_mis_out = mis_out
                        break
                if target_mis_out is None:
                    continue
                real = mis_in.realisations[r_idx]
                target_mis_out.realisations.append(real)
                if measure_block_height(cv, layout) > budget:
                    target_mis_out.realisations.pop()
                    journal.append(
                        f"réalisation refusée domaine {source.position} "
                        f"mission '{mis_in.client}'"
                    )

    return cv, journal
