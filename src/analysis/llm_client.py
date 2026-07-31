import json
import logging
import re
import threading
from typing import TypeVar

import litellm
from pydantic import BaseModel, ValidationError

from src.config import LLM_MODEL, MAX_RETRIES, MAX_TOKENS, REASONING_EFFORT, TEMPERATURE


T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def _as_number(value: object) -> float:
    """Coercion défensive : litellm peut renvoyer None, et les tests passent des
    MagicMock. Tout ce qui n'est pas un nombre vaut 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


class LLMClient:
    """Client LLM. Accumule les tokens et le coût de TOUS les appels qu'il a
    servis, retries compris — un retry est facturé comme n'importe quel appel.

    Une instance est partagée par les 3 appels d'un job, dont 2 tournent en
    parallèle (cf. `pipeline.orchestrate.generate`) : l'accumulation est donc
    protégée par un verrou.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or LLM_MODEL
        self.api_key = api_key
        self._lock = threading.Lock()
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._cost_usd = 0.0
        self._calls = 0

    # ── Comptabilité usage / coût ─────────────────────────────────────────

    def usage_totals(self) -> dict[str, int]:
        """Cumul des tokens, dans les clés attendues par Polaris
        (`GovernanceService.log_usage` lit input_tokens / output_tokens /
        total_tokens). litellm normalise au format OpenAI — d'où la traduction
        prompt_tokens → input_tokens, completion_tokens → output_tokens."""
        with self._lock:
            return {
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "total_tokens": self._total_tokens,
            }

    def total_cost_usd(self) -> float:
        with self._lock:
            return round(self._cost_usd, 6)

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._calls

    def _record(self, response: object) -> None:
        """Ne doit jamais faire échouer un appel LLM réussi : une erreur de
        comptabilité coûte une ligne de stats, pas un job."""
        try:
            usage = getattr(response, "usage", None)
            prompt = _as_number(getattr(usage, "prompt_tokens", 0))
            completion = _as_number(getattr(usage, "completion_tokens", 0))
            total = _as_number(getattr(usage, "total_tokens", 0)) or prompt + completion
            cost = self._response_cost(response)
        except Exception:  # noqa: BLE001
            logger.warning("usage accounting failed for one LLM call", exc_info=True)
            return

        with self._lock:
            self._input_tokens += int(prompt)
            self._output_tokens += int(completion)
            self._total_tokens += int(total)
            self._cost_usd += cost
            self._calls += 1

    @staticmethod
    def _response_cost(response: object) -> float:
        """litellm calcule déjà le coût (cache Anthropic inclus) et le range dans
        `_hidden_params`. On retombe sur `completion_cost` si absent, et sur 0 si
        le modèle est inconnu de la table de prix."""
        hidden = getattr(response, "_hidden_params", None)
        if isinstance(hidden, dict):
            cost = _as_number(hidden.get("response_cost"))
            if cost:
                return cost
        try:
            return _as_number(litellm.completion_cost(completion_response=response))
        except Exception:  # noqa: BLE001
            logger.warning("litellm could not price a response", exc_info=True)
            return 0.0

    def call_structured(
        self,
        system: str,
        user_message: str,
        response_model: type[T],
        max_tokens: int = MAX_TOKENS,
        temperature: float = TEMPERATURE,
        max_retries: int = MAX_RETRIES,
        cache_system: bool = True,
        reasoning_effort: str | None = REASONING_EFFORT,
    ) -> T:
        system_content = self._build_system_content(system, cache_system)
        last_error: str | None = None
        last_response: str | None = None

        for _ in range(max_retries + 1):
            current_user = user_message
            if last_error is not None:
                current_user = (
                    f"{user_message}\n\n---\n"
                    f"ATTENTION : ta réponse précédente n'était pas du JSON valide "
                    f"conforme au schéma attendu.\n"
                    f"Erreur de validation :\n{last_error}\n\n"
                    f"Ta sortie précédente :\n{last_response}\n\n"
                    f"Réponds UNIQUEMENT avec du JSON valide conforme au schéma demandé, "
                    f"sans texte avant ni après."
                )

            kwargs: dict = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": current_user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                # Laisse litellm dropper silencieusement les params non
                # supportés par le modèle cible (ex: GPT-5 refuse
                # temperature=0 quand reasoning est actif).
                "drop_params": True,
            }
            if reasoning_effort is not None:
                kwargs["reasoning_effort"] = reasoning_effort
            if self.api_key is not None:
                kwargs["api_key"] = self.api_key

            response = litellm.completion(**kwargs)
            # Compté avant toute validation : un JSON invalide a coûté ses tokens.
            self._record(response)
            raw_text = response.choices[0].message.content or ""

            try:
                cleaned = self._extract_json(raw_text)
                data = json.loads(cleaned)
                return response_model.model_validate(data)
            except json.JSONDecodeError as e:
                last_error = f"JSON invalide : {e}"
                last_response = raw_text
            except ValidationError as e:
                last_error = f"Schéma invalide : {e}"
                last_response = raw_text

        raise LLMError(
            f"Échec après {max_retries + 1} tentatives. Dernière erreur : {last_error}"
        )

    def _build_system_content(self, system: str, cache: bool):
        if not cache:
            return system
        if self._is_anthropic():
            return [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        return system

    def _is_anthropic(self) -> bool:
        m = self.model.lower()
        if m.startswith("anthropic/"):
            return True
        tail = m.split("/")[-1]
        return tail.startswith("claude")

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extrait le JSON de la réponse même si le LLM a ajouté du texte autour
        ou wrappé dans des fences markdown."""
        s = text.strip()
        fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```$", s, re.DOTALL)
        if fence:
            s = fence.group(1).strip()
        first = s.find("{")
        last = s.rfind("}")
        if first >= 0 and last > first:
            return s[first : last + 1]
        return s
