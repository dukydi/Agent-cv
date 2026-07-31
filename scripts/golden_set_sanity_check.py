"""Sanity check léger (BRIEF-GOLDEN-SET.md, §7) — pas un grading complet.

Lance le CLI de production sur quelques cas du golden set et vérifie
seulement : pas de plantage, AdaptedCV valide produit. Passe l'AO en texte
brut via subprocess (liste d'arguments, jamais via une chaîne shell) pour
éviter tout problème d'échappement lié à la longueur/au contenu du texte.

Usage : python scripts/golden_set_sanity_check.py cas_01 cas_06
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_SET = ROOT / "golden_set"
OUTPUT_DIR = ROOT / "output" / "golden_set_sanity"


def run_case(case_id: str) -> dict:
    case_dir = GOLDEN_SET / case_id
    cv_pdfs = sorted((case_dir / "cv").glob("*.pdf"))
    ao_text = (case_dir / "ao.txt").read_text(encoding="utf-8")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    debug_json_path = OUTPUT_DIR / f"{case_id}.json"
    pptx_path = OUTPUT_DIR / f"{case_id}.pptx"

    cmd = [
        sys.executable,
        "-m",
        "src.cli",
        "--cvs",
        *[str(p) for p in cv_pdfs],
        "--ao-text",
        ao_text,
        "--output",
        str(pptx_path),
        "--debug-json",
        str(debug_json_path),
    ]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)

    report = {
        "case_id": case_id,
        "returncode": result.returncode,
        "stderr_tail": result.stderr[-2000:] if result.returncode != 0 else "",
    }
    if result.returncode == 0:
        adapted = json.loads(debug_json_path.read_text(encoding="utf-8"))
        report["adapted_cv_valid_json"] = True
        report["consultant"] = adapted.get("consultant")
        report["nb_domaines_experience"] = len(adapted.get("experiences", []))
        report["score_global"] = adapted["coverage"]["score_global"]
        report["needs_non_couverts"] = adapted["coverage"]["needs_non_couverts"]
        report["alertes_completude"] = adapted.get("alertes_completude", [])
        report["pptx_produced"] = pptx_path.is_file()
    return report


def main() -> None:
    case_ids = sys.argv[1:] or ["cas_01", "cas_06"]
    reports = [run_case(cid) for cid in case_ids]
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
