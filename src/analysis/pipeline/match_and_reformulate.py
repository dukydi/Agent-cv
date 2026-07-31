from src.analysis.llm_client import LLMClient
from src.analysis.prompts import load_prompt
from src.schemas import AdaptedCV, Brief, RawCV, RenderConstraints


def match_and_reformulate(
    brief: Brief,
    raw_cv: RawCV,
    constraints: RenderConstraints,
    client: LLMClient | None = None,
) -> AdaptedCV:
    """Sélectionne ET reformule en un seul appel LLM.

    Combine les anciennes étapes Match + Reformulate. Le LLM voit
    simultanément le Brief, le RawCV et les contraintes typographiques,
    et produit directement un AdaptedCV final (sélection + rédaction
    adaptée).
    """
    llm = client or LLMClient()
    system = load_prompt("match_and_reformulate")
    user_message = (
        f"=== BRIEF ===\n{brief.model_dump_json(indent=2)}\n\n"
        f"=== RAW CV ===\n{raw_cv.model_dump_json(indent=2)}\n\n"
        f"=== CONTRAINTES TYPOGRAPHIQUES ===\n"
        f"{constraints.model_dump_json(indent=2)}\n"
    )
    adapted = llm.call_structured(
        system=system,
        user_message=user_message,
        response_model=AdaptedCV,
    )
    # Sécurise les champs critiques contre un éventuel drift LLM
    return adapted.model_copy(update={
        "consultant": raw_cv.consultant,
        "versions_count": raw_cv.versions_count,
        "brief_source": brief,
    })
