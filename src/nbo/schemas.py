from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NBORequest(BaseModel):
    cliente_id: str = Field(min_length=1)


class BatchRequest(BaseModel):
    cliente_ids: list[str] | None = Field(default=None, max_length=1000)
    limit: int = Field(default=100, ge=1, le=1000)

    @field_validator("cliente_ids")
    @classmethod
    def unique_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("cliente_ids no puede contener duplicados")
        return value


class Explanation(BaseModel):
    positive: list[str]
    negative: list[str]


class Objection(BaseModel):
    motivo: str
    probability: float = Field(ge=0, le=1)


class Timing(BaseModel):
    momento: str
    urgencia: Literal["alta", "media", "baja"]


class Recommendation(BaseModel):
    oferta_id: str
    nombre_oferta: str
    canal: str
    probabilidad_contacto: float = Field(ge=0, le=1)
    probabilidad_aceptacion: float = Field(ge=0, le=1)
    probabilidad_venta: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1, description="Ranking interno; no es una probabilidad.")
    es_mt: bool
    precio_mensual: float
    momento: Timing
    explanation: Explanation
    beneficio_cliente: str
    beneficio_negocio: str
    speech_principal: str
    reason_codes: list[str]


class CustomerSummary(BaseModel):
    cliente_id: str
    etapa_mt: str
    elegible_mt: bool
    es_movistar_total: bool
    tipo_cliente: str
    tiene_movil: bool
    tiene_hogar: bool
    tiene_internet_hogar: bool
    plan_actual_id: str
    monto_facturado_prom: float
    consumo_datos_gb_prom: float
    canal_mas_usado: str
    n_reclamos: int
    meses_moroso: int


class Rebate(BaseModel):
    enabled: bool
    strategy: str
    speech: str
    alternative_offer_id: str | None = None


class CommercialStrategy(BaseModel):
    objective: Literal[
        "convertir_a_mt",
        "completar_hogar_para_mt",
        "completar_movil_para_mt",
        "profundizar_relacion_mt",
        "mejor_oferta_compatible",
    ]
    current_stage: str
    mt_priority_applied: bool
    next_step: str
    rationale: str


class PostRejectionAction(BaseModel):
    source: Literal["predicted", "observed"]
    trigger_reason: Literal["precio", "no_necesita", "ya_tiene_similar", "mal_momento", "no_confia", "otro"]
    action: str
    objective: str
    wait_days: int = Field(ge=0)
    recontact_from: str
    channel: str
    alternative_offer_id: str | None = None
    alternative_offer_name: str | None = None
    preserves_mt_path: bool
    speech: str
    reason_codes: list[str]


class SalesPlaybook(BaseModel):
    version: str
    objective: str
    channel_style: Literal[
        "mensaje_breve",
        "conversacion_consultiva",
        "respuesta_contextual",
        "llamada_con_permiso",
    ]
    opening: str
    discovery_question: str
    main_argument: str
    verified_benefit: str
    close: str
    likely_objection: str
    objection_response: str
    post_rejection_guidance: str
    suggested_script: str
    evidence_codes: list[str]
    do_not_say: list[str]


class ScoreBreakdown(BaseModel):
    oferta_id: str
    conversion: float
    customer_fit: float
    business_value: float
    mt_priority: float
    friction: float
    cooldown: float
    raw_score: float
    final_score: float = Field(ge=0, le=1)


class DecisionTrace(BaseModel):
    total_offer_channel_pairs: int
    eligible_offer_channel_pairs: int
    blocked_offer_channel_pairs: int
    blocked_by_reason: dict[str, int]
    top_score_breakdown: list[ScoreBreakdown]
    top1_top2_score_gap: float
    channel_selection_reason: str
    selection_reason: str


class EvidenceConfidence(BaseModel):
    level: Literal["bajo", "medio", "alto"]
    cold_start: bool
    contact_source: str
    acceptance_source: str
    rejection_source: str
    client_events: int
    client_offer_exposures: int
    client_channel_contacts: int
    relevant_support: int
    warning: str


class PlaybookExperiment(BaseModel):
    experiment_version: str
    exposure_id: str
    variant: Literal["benefit_first", "strategic_path_first"]
    assignment_method: Literal["stable_hash"] = "stable_hash"


class NBOResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    decision_id: str
    decision_schema_version: str
    versions: dict[str, str]
    cliente: CustomerSummary
    recommendation: Recommendation
    alternatives: list[Recommendation]
    rejection_prediction: list[Objection]
    rebate: Rebate
    commercial_strategy: CommercialStrategy
    post_rejection_action: PostRejectionAction
    sales_playbook: SalesPlaybook
    decision_trace: DecisionTrace
    evidence_confidence: EvidenceConfidence
    playbook_experiment: PlaybookExperiment
    state_version: int = 0
    state_as_of: datetime | None = None
    applied_state_event_ids: list[str] = Field(default_factory=list)


class SimulationAction(BaseModel):
    action: Literal[
        "set_data_consumption", "set_monthly_budget", "set_mt_eligibility",
        "acquire_offer", "reject_offer", "add_commercial_fatigue", "set_preferred_channel",
    ]
    value: float | bool | str | None = None
    oferta_id: str | None = None
    motivo_rechazo: Literal["precio", "no_necesita", "ya_tiene_similar", "mal_momento", "no_confia", "otro"] | None = None

    @model_validator(mode="after")
    def coherent_action(self) -> "SimulationAction":
        if self.action in {"acquire_offer", "reject_offer"} and not self.oferta_id:
            raise ValueError("oferta_id es obligatorio para adquirir o rechazar")
        if self.action == "reject_offer" and not self.motivo_rechazo:
            raise ValueError("motivo_rechazo es obligatorio para reject_offer")
        if self.action not in {"acquire_offer", "reject_offer"} and self.value is None:
            raise ValueError("value es obligatorio para esta acción")
        return self


class SimulationRequest(BaseModel):
    cliente_id: str = Field(min_length=1)
    actions: list[SimulationAction] = Field(min_length=1, max_length=10)


class SimulationResponse(BaseModel):
    simulation_id: str
    persisted: Literal[False] = False
    applied_actions: list[SimulationAction]
    changed_fields: dict[str, Any]
    stage_change: str
    recommendation_change: str
    base: NBOResult
    simulated: NBOResult


class DemoJourneyRequest(BaseModel):
    cliente_id: str = "CLI000001"
    motivo_rechazo: Literal["precio", "no_necesita", "ya_tiene_similar", "mal_momento", "no_confia", "otro"] = "precio"


class DemoJourneyResponse(BaseModel):
    journey_id: str
    cliente_id: str
    persisted: Literal[False] = False
    initial: NBOResult
    after_acceptance: NBOResult | None = None
    after_activation: NBOResult | None = None
    recovery_action: PostRejectionAction
    immediate_after_rejection: NBOResult
    at_recontact: NBOResult
    steps: list[dict[str, Any]] = Field(default_factory=list)
    events_to_register: list[dict[str, Any]] = Field(default_factory=list)
    markdown: str


class EconomicAssumptions(BaseModel):
    margin_rate: float = Field(default=0.30, ge=0, le=1)
    expected_months: int = Field(default=12, ge=1, le=60)
    channel_costs: dict[str, float] = Field(default_factory=lambda: {"Digital": 1.0, "Tienda": 8.0, "Call In": 4.0, "Call Out": 6.0})
    rebate_cost: float = Field(default=10.0, ge=0)
    expected_rebate_use_rate: float = Field(default=0.25, ge=0, le=1)
    max_experience_penalty: float = Field(default=15.0, ge=0)


class EconomicSimulationRequest(BaseModel):
    cliente_id: str
    assumptions: EconomicAssumptions = Field(default_factory=EconomicAssumptions)


class EconomicOfferResult(BaseModel):
    oferta_id: str
    nombre_oferta: str
    canal: str
    official_rank: int
    economic_rank: int
    expected_margin: float
    expected_value: float
    components: dict[str, float]


class EconomicSimulationResponse(BaseModel):
    cliente_id: str
    assumption_source: Literal["demo_assumptions"] = "demo_assumptions"
    currency: Literal["PEN"] = "PEN"
    assumptions: EconomicAssumptions
    formula: str
    official_offer_id: str
    economic_top3: list[EconomicOfferResult]
    disclaimer: str


class PlaybookRenderRequest(BaseModel):
    decision_id: str
    tone: Literal["formal", "cercano", "conciso"] = "conciso"


class PlaybookRenderResponse(BaseModel):
    decision_id: str
    render_status: Literal["generated", "fallback"]
    provider: str
    model: str | None = None
    rendered_script: str
    fallback_reason: str | None = None
    latency_ms: float


class FeedbackRequest(BaseModel):
    decision_id: str
    resultado_final: Literal["aceptada", "rechazada", "no_contactado"]
    motivo_rechazo: Literal["precio", "no_necesita", "ya_tiene_similar", "mal_momento", "no_confia", "otro"] | None = None
    medio_probatorio: Literal["registro_plataforma", "audio_llamada", "chat_log"]
    rebate_usado: bool = False
    resultado_rebate: Literal["aceptada", "rechazada"] | None = None

    @model_validator(mode="after")
    def coherent(self) -> "FeedbackRequest":
        if self.resultado_final == "rechazada" and self.motivo_rechazo is None:
            raise ValueError("motivo_rechazo es obligatorio si el resultado es rechazada")
        if self.resultado_final != "rechazada" and self.motivo_rechazo is not None:
            raise ValueError("motivo_rechazo solo aplica a rechazada")
        if self.rebate_usado and self.resultado_rebate is None:
            raise ValueError("resultado_rebate es obligatorio cuando rebate_usado=true")
        if not self.rebate_usado and self.resultado_rebate is not None:
            raise ValueError("resultado_rebate requiere rebate_usado=true")
        return self


class FeedbackResponse(BaseModel):
    feedback_id: int
    decision_id: str
    status: Literal["recorded"]
    post_rejection_action: PostRejectionAction | None = None


class FunnelEventRequest(BaseModel):
    decision_id: str
    event_type: Literal["classified", "displayed", "contacted", "negotiated", "rebate_used", "accepted", "rejected"]
    canal: Literal["Digital", "Tienda", "Call In", "Call Out"] | None = None
    oferta_id: str | None = None
    medio_probatorio: Literal["registro_plataforma", "audio_llamada", "chat_log"] | None = None
    evidencia_referencia: str | None = Field(default=None, max_length=500)
    motivo_rechazo: Literal["precio", "no_necesita", "ya_tiene_similar", "mal_momento", "no_confia", "otro"] | None = None

    @model_validator(mode="after")
    def coherent_event(self) -> "FunnelEventRequest":
        if self.event_type == "rejected" and self.motivo_rechazo is None:
            raise ValueError("motivo_rechazo es obligatorio para rejected")
        if self.event_type != "rejected" and self.motivo_rechazo is not None:
            raise ValueError("motivo_rechazo solo aplica a rejected")
        if self.event_type in {"displayed", "contacted", "negotiated", "rebate_used", "accepted", "rejected"} and not self.oferta_id:
            raise ValueError("oferta_id es obligatorio desde displayed")
        return self


CustomerEventType = Literal[
    "product_activated", "product_cancelled", "usage_updated", "billing_updated",
    "preferred_channel_changed", "mt_eligibility_overridden", "customer_attribute_corrected",
]


class CustomerEventRequest(BaseModel):
    cliente_id: str = Field(min_length=1)
    event_type: CustomerEventType
    effective_at: datetime
    source: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)
    expected_state_version: int = Field(ge=0)
    oferta_id: str | None = None
    decision_id: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)
    evidence_type: str | None = Field(default=None, max_length=100)
    evidence_reference: str | None = Field(default=None, max_length=500)
    correction_of_event_id: str | None = None

    @model_validator(mode="after")
    def coherent_customer_event(self) -> "CustomerEventRequest":
        if self.event_type in {"product_activated", "product_cancelled"} and not self.oferta_id:
            raise ValueError("oferta_id es obligatorio para eventos de producto")
        if self.event_type == "product_activated" and (not self.evidence_type or not self.evidence_reference):
            raise ValueError("product_activated requiere evidence_type y evidence_reference")
        if self.event_type == "mt_eligibility_overridden" and (not self.evidence_type or not self.evidence_reference):
            raise ValueError("mt_eligibility_overridden requiere evidencia")
        if self.event_type in {
            "usage_updated", "billing_updated", "preferred_channel_changed",
            "mt_eligibility_overridden", "customer_attribute_corrected",
        } and not self.changes:
            raise ValueError("changes no puede estar vacio para este tipo de evento")
        return self


class StateFieldOrigin(BaseModel):
    source: str
    event_id: str | None = None
    effective_at: datetime | None = None


class CustomerState(BaseModel):
    cliente_id: str
    as_of: datetime
    state_version: int = Field(ge=0)
    mt_stage: str
    active_offer_ids: list[str]
    applied_event_ids: list[str]
    last_updated_at: datetime | None = None
    field_origins: dict[str, StateFieldOrigin]
    mt_override: dict[str, Any] | None = None
    attributes: dict[str, Any]


class CustomerStateEvent(BaseModel):
    event_id: str
    cliente_id: str
    event_type: CustomerEventType
    effective_at: datetime
    recorded_at: datetime
    source: str
    decision_id: str | None = None
    oferta_id: str | None = None
    changes_before: dict[str, Any]
    changes_after: dict[str, Any]
    evidence_type: str | None = None
    evidence_reference: str | None = None
    idempotency_key: str
    correction_of_event_id: str | None = None
    state_version_before: int
    state_version_after: int


class CustomerEventResponse(BaseModel):
    event: CustomerStateEvent
    previous_state: CustomerState
    new_state: CustomerState
    changed_fields: dict[str, dict[str, Any]]
    mt_stage_change: str
    recommendation: NBOResult | None = None
    warning: str | None = None
    idempotent_replay: bool = False


class LearningReadiness(BaseModel):
    status: Literal["insufficient_data", "ready_for_challenger"]
    usable_feedback: int
    unique_customers: int
    contacts: int
    acceptances: int
    rejections: int
    coverage_by_channel: dict[str, int]
    coverage_by_offer: dict[str, int]
    coverage_by_mt_stage: dict[str, int]
    rejection_reasons: dict[str, int]
    days_since_last_training: int
    thresholds: dict[str, int]
    reasons: list[str]
