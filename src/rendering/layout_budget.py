"""Budget de layout du shape expériences (shape [8]) calibré sur le template.

Toutes les dimensions sont en points (1 pt = 1/72 inch). Valeurs mesurées
empiriquement sur `golden-source-template-v2-templated.pptx`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExperiencesBlockLayout:
    """Layout du shape [8] (bloc expériences hiérarchique)."""

    # Police : Arial Nova Condensed sur le template, fallback géré par text_metrics
    font_family: str = "Arial Nova Condensed"
    font_size_pt: float = 9.5

    # Hauteur utilisable du shape (height - marges top/bottom)
    available_height_pt: float = 414.5

    # Largeur effective selon le niveau du paragraphe (compte tenu de
    # l'indentation des bullets) :
    #   - level 0 (domaine sans bullet, mission avec bullet)
    #   - level 1 (réalisation avec sous-bullet, indent supplémentaire)
    width_level0_pt: float = 545.0
    width_level1_pt: float = 520.0

    # Espacement vertical après chaque paragraphe (en plus de la hauteur de
    # texte). Calibré sur le rendu PowerPoint réel du template — PowerPoint
    # applique un paragraph-spacing visible entre les bullets level 0/1, que
    # Pillow ignore par défaut. Sur 25-30 paragraphes, cela ajoute 70-100 pt
    # de hauteur invisibles dans la mesure brute.
    space_after_domaine_pt: float = 6.0
    space_after_mission_pt: float = 3.0
    space_after_realisation_pt: float = 2.0
    space_before_new_domaine_pt: float = 6.0  # respiration entre domaines

    # Marge de sécurité : calibrée empiriquement par run live sur le CV
    # Diane + AO Enedis. Pillow + paragraph_spacing calibrés donnent une
    # mesure ~10-15 % en-dessous du rendu PowerPoint réel ; safety_margin =
    # 1.0 (budget = hauteur visible) compense en visant la zone exacte.
    # L'auto-shrink étendu au shape [8] sert de filet final pour les rares
    # cas où malgré tout ça déborde.
    safety_margin_ratio: float = 1.00

    @property
    def effective_height_pt(self) -> float:
        return self.available_height_pt * self.safety_margin_ratio


DEFAULT_EXPERIENCES_LAYOUT = ExperiencesBlockLayout()
