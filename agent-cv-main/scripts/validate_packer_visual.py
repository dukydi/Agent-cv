"""Génération de PPTX à densités variables pour valider visuellement le packer.

Usage :
    python scripts/validate_packer_visual.py

Produit dans `output/` 5 fichiers PPTX avec des densités de contenu croissantes
(de "peu de contenu" à "très chargé"). Ouvre chacun dans PowerPoint et
observe à l'œil le remplissage de la zone expériences (shape [8]) :

- Sous-rempli : zone vide en bas, le packer a élagué trop tôt.
- Bien rempli : la zone est densément utilisée, sans débordement.
- Déborde    : du texte sort de la zone visible.

Affiche aussi le ratio de remplissage calculé (mesure Pillow). Objectif :
fill_ratio ≥ 70 % sur des CV chargés (3 dom × 2 mis × 5+ réa).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rendering.constraints import default_constraints
from src.rendering.layout_budget import DEFAULT_EXPERIENCES_LAYOUT
from src.rendering.packer import measure_block_height, pack
from src.rendering.pptx_renderer import render
from src.schemas import (
    AdaptedCV,
    AdaptedExperience,
    AdaptedSkill,
    Brief,
    Consultant,
    CoverageReport,
    Mission,
    Need,
)


REAL_TEXTS = [
    "Piloté le déploiement d'une plateforme SI multi-pays — 8 entités, 600 utilisateurs, "
    "intégration Active Directory et SSO — pour fiabiliser les opérations.",
    "Cadré la roadmap produit sur 18 mois en lien direct avec le COMEX — séquençage des "
    "lots, arbitrage budget/délai, alignement des parties prenantes.",
    "Mené un audit complet des processus IT — cartographie de 40 processus, identification "
    "de 12 quick-wins (~400 k€ d'économies annualisées).",
    "Coordonné 4 prestataires externes sur une intégration ERP critique Oracle Fusion — "
    "gouvernance hebdo, gestion des dépendances, validation des livrables.",
    "Reconstruit l'équipe data (5 → 12 ETP) en 9 mois — plan de recrutement structuré, "
    "onboarding et montée en compétence sur la stack analytique.",
    "Conçu le framework de pilotage projet adopté par 3 BU et 15 chefs de projet — "
    "templates, indicateurs cibles, rituels et points de gouvernance hebdomadaires.",
    "Animé la transformation agile à l'échelle (SAFe 5.0) sur 4 trains de release — "
    "PI Planning, formation des Release Train Engineers, métriques de vélocité.",
    "Sécurisé le budget de 2,3 M€ alloué au programme de modernisation infrastructure — "
    "défense en COMEX, suivi des engagements financiers et reporting trimestriel.",
]


def _make_cv(
    n_dom: int, n_mis: int, n_real: int, formation: list[str] | None = None
) -> AdaptedCV:
    experiences = []
    for d in range(1, n_dom + 1):
        missions = []
        for m in range(1, n_mis + 1):
            reals = [REAL_TEXTS[(d * 3 + m * 2 + r) % len(REAL_TEXTS)] for r in range(n_real)]
            missions.append(
                Mission(
                    client=f"Client {d}-{m}",
                    description_courte=(
                        f"Pour Client {d}-{m} – Mission de pilotage stratégique "
                        f"dans le secteur cible, sur 12 à 18 mois."
                    ),
                    realisations=reals,
                )
            )
        experiences.append(
            AdaptedExperience(
                domaine=f"DOMAINE D'EXPERTISE {d} — PILOTAGE TRANSFORMATION SI",
                missions=missions,
                score=95 - d * 5,
                position=d,
                mapping_besoins=["Pilotage SI"],
            )
        )

    return AdaptedCV(
        consultant=Consultant(
            nom="Diane Maurin",
            grade="Senior Manager",
            annees_experience=12,
            formation=formation or ["ESSEC Business School (Programme MSc IMHI) : 2020"],
        ),
        resume_profil=(
            "Senior Manager avec 12 ans d'expérience dans le pilotage de programmes "
            "SI complexes pour le secteur de l'énergie. Spécialiste du cadrage "
            "stratégique, de la conduite du changement et de l'animation d'équipes "
            "pluridisciplinaires en environnement réglementé."
        ),
        experiences=experiences,
        skills=[AdaptedSkill(label=f"Compétence {i}") for i in range(1, 10)],
        coverage=CoverageReport(score_global=85, needs_couverts=["Pilotage SI"]),
        brief_source=Brief(
            secteur="Énergie",
            client="Enedis",
            intitule_mission="Pilotage SI distribution",
            needs=[
                Need(
                    label="Pilotage SI",
                    category="competence",
                    priority="must_have",
                    source_quote="Le profil doit avoir piloté un programme SI complexe.",
                )
            ],
        ),
        versions_count=3,
    )


SCENARIOS = [
    ("01_light", 2, 1, 2),     # CV léger : 2 dom × 1 mis × 2 réa = 4 réa
    ("02_moyen", 3, 2, 3),     # CV moyen : 3 × 2 × 3 = 18 réa
    ("03_charge", 3, 2, 5),    # CV chargé : 3 × 2 × 5 = 30 réa (cible du packer)
    ("04_tres_charge", 3, 2, 7),  # Très chargé : 3 × 2 × 7 = 42 réa
    ("05_extreme", 4, 3, 8),   # Extrême : 4 × 3 × 8 = 96 réa (stress test)
]


def main() -> None:
    output_dir = ROOT / "output" / "packer_validation"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nGeneration des PPTX de validation dans : {output_dir}")
    print("=" * 100)
    print(f"{'Scenario':<18} {'Densite':<10} {'Retenu':<22} {'Reals':<10} {'Pillow':<10} {'Auto-shrink':<14}")
    print("-" * 100)

    for name, n_dom, n_mis, n_real in SCENARIOS:
        cv = _make_cv(n_dom, n_mis, n_real)
        packed, _ = pack(cv, DEFAULT_EXPERIENCES_LAYOUT)
        # render() applique le packer en interne + l'auto-shrink final
        out = render(cv, default_constraints())

        target = output_dir / f"{name}.pptx"
        target.write_bytes(out.pptx_bytes)

        measured = measure_block_height(packed, DEFAULT_EXPERIENCES_LAYOUT)
        fill_ratio = measured / DEFAULT_EXPERIENCES_LAYOUT.available_height_pt

        density = f"{n_dom}x{n_mis}x{n_real}"
        n_input = n_dom * n_mis * n_real
        n_kept = sum(len(m.realisations) for e in packed.experiences for m in e.missions)
        retained = (
            f"{len(packed.experiences)}d x "
            f"{sum(len(e.missions) for e in packed.experiences)}m x "
            f"{n_kept}r"
        )
        reals_str = f"{n_kept}/{n_input}"

        shrink_info = "non"
        for t in out.truncations:
            if "auto-shrink" in t and "shape[8]" in t:
                if "ratio" in t:
                    try:
                        ratio_str = t.split("ratio")[1].split("--")[0].strip()
                        shrink_info = f"oui ({ratio_str})"
                    except Exception:
                        shrink_info = "oui"
                else:
                    shrink_info = "oui"
                break

        print(
            f"{name:<18} {density:<10} {retained:<22} {reals_str:<10} "
            f"{fill_ratio:.0%}{'':<6} {shrink_info:<14}"
        )

    # Scénarios formation : valider le layout dynamique (1 → 2 lignes sans
    # réduction de police, puis fallback > 2 lignes).
    print("-" * 100)
    formation_scenarios = [
        (
            "06_formation_2lignes",
            [
                "ESSEC Business School (Programme Grande École, Major Stratégie) : 2012",
                "MSc Data Science, Télécom Paris : 2014",
                "Certification PMP (PMI) : 2018",
            ],
        ),
        (
            "07_formation_longue",
            [
                "ESSEC Business School (Programme Grande École, Major Stratégie) : 2012",
                "MSc Data Science, Télécom Paris : 2014",
                "Certification PMP (Project Management Institute) : 2018",
                "Certification SAFe Program Consultant (SPC) : 2021",
            ],
        ),
    ]
    for name, formation in formation_scenarios:
        cv = _make_cv(3, 2, 3, formation=formation)
        out = render(cv, default_constraints())
        (output_dir / f"{name}.pptx").write_bytes(out.pptx_bytes)
        formation_log = next(
            (t for t in out.truncations if t.startswith("formation sur")), "1 ligne"
        )
        print(f"{name:<18} {'formation':<10} {formation_log}")

    print("=" * 80)
    print("\nOuvre les fichiers dans PowerPoint et verifie :")
    print("  [v] Pas de debordement visible (zone experiences tient sur la slide)")
    print("  [v] Pas de '...' dans le resume / les competences")
    print("  [v] Le bas de la zone experiences est bien rempli (pas de vide)")
    print("  [v] Le domaine 1 conserve toutes ses realisations sur les scenarios charges")
    print("\nRapporte ce que tu observes : si un scenario sous-remplit ou deborde,")
    print("on ajuste safety_margin_ratio ou les espacements dans layout_budget.py.")


if __name__ == "__main__":
    main()
