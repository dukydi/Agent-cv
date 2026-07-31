from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BaseStrict(BaseModel):
    model_config = ConfigDict(extra="forbid")


NeedCategory = Literal["competence", "experience", "contexte"]
NeedPriority = Literal["must_have", "important", "nice_to_have"]
SkillCategory = Literal["metier", "technique", "outil", "methode", "langue", "soft"]
SkillLevel = Literal["expert", "confirme", "operationnel"]
SourceKind = Literal["pdf", "text"]
ApiErrorCode = Literal[
    "validation_error",
    "llm_error",
    "render_error",
    "internal",
]


# ──────────────────────────────────────────────────────────────────────────
# Inputs
# ──────────────────────────────────────────────────────────────────────────

class RawDocument(BaseStrict):
    source_kind: SourceKind
    source_name: str
    text: str


# ──────────────────────────────────────────────────────────────────────────
# Brief (sortie d'Extract-Brief)
# ──────────────────────────────────────────────────────────────────────────

class Need(BaseStrict):
    label: str
    category: NeedCategory
    priority: NeedPriority
    source_quote: str
    deal_breaker: bool = False
    seuil_quantitatif: str | None = None


class VocabularyTerm(BaseStrict):
    terme: str
    frequence: int = Field(default=0, ge=0)


class Brief(BaseStrict):
    secteur: str | None = None
    client: str | None = None
    intitule_mission: str | None = None
    needs: list[Need] = Field(default_factory=list)
    vocabulaire: list[VocabularyTerm] = Field(default_factory=list)
    livrables: list[str] = Field(default_factory=list)
    contraintes: list[str] = Field(default_factory=list)
    ton_attendu: str | None = None
    alertes: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# RawCV (sortie d'Extract-CV)
# ──────────────────────────────────────────────────────────────────────────

class Skill(BaseStrict):
    label: str
    category: SkillCategory
    level: SkillLevel | None = None
    sources: list[str] = Field(default_factory=list)
    demonstree_par: list[str] = Field(default_factory=list)


class Experience(BaseStrict):
    titre: str
    client: str | None = None
    secteur: str | None = None
    date_debut: str | None = None
    date_fin: str | None = None
    duree: str | None = None
    contexte: str | None = None
    description_brute: str
    realisations: list[str] = Field(default_factory=list)
    skills_utilisees: list[str] = Field(default_factory=list)
    livrables: list[str] = Field(default_factory=list)
    chiffres_cles: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    conflits: list[str] = Field(default_factory=list)


class Consultant(BaseStrict):
    nom: str | None = None
    grade: str | None = None
    annees_experience: int | None = Field(default=None, ge=0)
    formation: list[str] = Field(default_factory=list)
    langues: list[str] = Field(default_factory=list)
    domaines_fonctionnels: list[str] = Field(default_factory=list)


class RawCV(BaseStrict):
    consultant: Consultant
    resume_brut: str | None = None
    experiences: list[Experience] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    alertes_fusion: list[str] = Field(default_factory=list)
    versions_count: int = Field(ge=1)


# ──────────────────────────────────────────────────────────────────────────
# AdaptedCV (sortie de Match + Reformulate)
# ──────────────────────────────────────────────────────────────────────────

class Mission(BaseStrict):
    client: str
    description_courte: str
    realisations: list[str] = Field(default_factory=list)


class AdaptedExperience(BaseStrict):
    domaine: str
    missions: list[Mission] = Field(default_factory=list)
    score: int = Field(ge=0, le=100)
    position: int = Field(ge=1)
    mapping_besoins: list[str] = Field(default_factory=list)


class AdaptedSkill(BaseStrict):
    label: str


class CoverageReport(BaseStrict):
    score_global: int = Field(ge=0, le=100)
    needs_couverts: list[str] = Field(default_factory=list)
    needs_non_couverts: list[str] = Field(default_factory=list)


class AdaptedCV(BaseStrict):
    consultant: Consultant
    resume_profil: str
    experiences: list[AdaptedExperience] = Field(default_factory=list)
    skills: list[AdaptedSkill] = Field(default_factory=list)
    coverage: CoverageReport
    alertes_completude: list[str] = Field(default_factory=list)
    brief_source: Brief
    versions_count: int = Field(ge=1)


# ──────────────────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────────────────

class RenderConstraints(BaseStrict):
    max_skills: int = Field(ge=1)
    max_chars_skill_label: int = Field(ge=1)
    max_chars_nom: int = Field(ge=1)
    max_chars_grade: int = Field(ge=1)
    max_chars_resume: int = Field(ge=1)
    max_chars_formation_line: int = Field(ge=1)
    max_chars_domaine: int = Field(ge=1)
    max_chars_mission_desc_courte: int = Field(ge=1)
    max_chars_realisation: int = Field(ge=1)
    max_experiences: int = Field(ge=1)
    max_missions_per_domain: int = Field(ge=1)
    max_realisations_per_mission: int = Field(ge=1)


class RenderOutput(BaseStrict):
    pptx_bytes: bytes
    fields_rendered: dict[str, str] = Field(default_factory=dict)
    truncations: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────────────────

class ApiError(BaseStrict):
    code: ApiErrorCode
    message: str
    details: dict | None = None


class GenerateResponse(BaseStrict):
    success: bool
    error: ApiError | None = None
    adapted_cv: AdaptedCV | None = None
    pptx_base64: str | None = None
    warnings: list[str] = Field(default_factory=list)
