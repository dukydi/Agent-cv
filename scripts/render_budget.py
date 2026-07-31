"""Re-rend le PPTX depuis le JSON avec un budget de hauteur packer override.

Usage : python -m scripts.render_budget <budget_pt> <suffixe>
N'appelle PAS le LLM (repart du JSON adapté).
"""
import dataclasses
import sys

import src.rendering.pptx_renderer as renderer
from src.config import OUTPUT_DIR
from src.rendering.constraints import default_constraints
from src.rendering.layout_budget import DEFAULT_EXPERIENCES_LAYOUT
from src.schemas import AdaptedCV


def main() -> None:
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 510.0
    suffix = sys.argv[2] if len(sys.argv) > 2 else f"b{int(budget)}"

    renderer.DEFAULT_EXPERIENCES_LAYOUT = dataclasses.replace(
        DEFAULT_EXPERIENCES_LAYOUT, available_height_pt=budget
    )

    adapted = AdaptedCV.model_validate_json(
        (OUTPUT_DIR / "CV-Diane-energie-DSI.json").read_text(encoding="utf-8")
    )
    out = renderer.render(adapted, default_constraints())

    pptx_path = OUTPUT_DIR / f"CV-Diane-energie-DSI-{suffix}.pptx"
    pptx_path.write_bytes(out.pptx_bytes)
    print(f"[render] budget={budget} -> {pptx_path}")
    for t in out.truncations:
        print(f"    - {t}")


if __name__ == "__main__":
    main()
