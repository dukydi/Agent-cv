import argparse
import sys
from pathlib import Path

from src.analysis.parsing import parse_pdf, parse_text
from src.analysis.pipeline.orchestrate import generate
from src.config import OUTPUT_DIR
from src.rendering.constraints import default_constraints
from src.rendering.pptx_renderer import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-cv",
        description="Adapte un CV à un AO et génère un PPTX au template Colombus.",
    )
    parser.add_argument(
        "--cvs",
        nargs="+",
        required=True,
        metavar="CV.pdf",
        help="1 à N PDFs du CV consultant (versions à fusionner)",
    )
    ao_group = parser.add_mutually_exclusive_group(required=True)
    ao_group.add_argument("--ao", help="PDF de l'AO")
    ao_group.add_argument("--ao-text", help="Texte de l'AO en ligne")
    parser.add_argument(
        "--output",
        default=None,
        help="Chemin du PPTX produit (défaut: output/cv-<nom>.pptx)",
    )
    parser.add_argument(
        "--debug-json",
        default=None,
        help="Si fourni, écrit l'AdaptedCV en JSON à ce chemin (utile pour valider le prompt)",
    )

    args = parser.parse_args(argv)

    cvs = [parse_pdf(p) for p in args.cvs]
    if args.ao:
        ao = parse_pdf(args.ao)
    else:
        ao = parse_text(args.ao_text, "ao-cli.txt")

    constraints = default_constraints()
    print(f"[CLI] Pipeline en cours ({len(cvs)} CV, AO={ao.source_name})...")
    adapted = generate(cvs, ao, constraints)
    print(f"[CLI] Pipeline OK — couverture besoins: {adapted.coverage.score_global}/100")
    print(f"      domaines retenus: {len(adapted.experiences)}")
    print(f"      compétences retenues: {len(adapted.skills)}")
    if adapted.alertes_completude:
        print(f"      alertes complétude: {len(adapted.alertes_completude)}")

    out = render(adapted, constraints)
    print(f"[CLI] Rendu PPTX OK ({len(out.pptx_bytes)} octets)")
    if out.truncations:
        print(f"      troncatures ({len(out.truncations)}):")
        for t in out.truncations:
            print(f"        - {t}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.output:
        target = Path(args.output)
    else:
        nom = adapted.consultant.nom or "sans-nom"
        slug = nom.replace("[[", "").replace("]]", "").strip().replace(" ", "_") or "cv"
        target = OUTPUT_DIR / f"cv-{slug}.pptx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out.pptx_bytes)
    print(f"[CLI] PPTX écrit : {target}")

    if args.debug_json:
        debug_path = Path(args.debug_json)
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(adapted.model_dump_json(indent=2), encoding="utf-8")
        print(f"[CLI] Debug JSON écrit : {debug_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
