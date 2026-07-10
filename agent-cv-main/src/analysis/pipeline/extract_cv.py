from src.analysis.llm_client import LLMClient
from src.analysis.prompts import load_prompt
from src.schemas import RawCV, RawDocument


def extract_cv(cvs: list[RawDocument], client: LLMClient | None = None) -> RawCV:
    if not cvs:
        raise ValueError("Au moins un CV est requis.")

    llm = client or LLMClient()
    system = load_prompt("extract_cv")

    n = len(cvs)
    parts = []
    for i, doc in enumerate(cvs, start=1):
        parts.append(f"=== VERSION {i}/{n} (fichier : {doc.source_name}) ===\n")
        parts.append(doc.text)
        parts.append("")
    user_message = "\n".join(parts)

    raw_cv = llm.call_structured(
        system=system,
        user_message=user_message,
        response_model=RawCV,
    )
    if raw_cv.versions_count != n:
        raw_cv = raw_cv.model_copy(update={"versions_count": n})
    return raw_cv
