from src.schemas import RenderConstraints


def default_constraints() -> RenderConstraints:
    # Valeurs calibrées empiriquement sur le template + run live.
    # Le shape [8] est géré par le packer adaptatif (text_metrics + Pillow),
    # ces limites concernent surtout les zones simples (zone gauche + cases).
    return RenderConstraints(
        max_skills=9,
        max_chars_skill_label=35,
        max_chars_nom=50,
        max_chars_grade=55,
        max_chars_resume=320,
        max_chars_formation_line=130,
        max_chars_domaine=85,
        max_chars_mission_desc_courte=160,
        max_chars_realisation=180,
        max_experiences=3,
        max_missions_per_domain=2,
        max_realisations_per_mission=3,
    )
