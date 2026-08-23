# C2-P4 Completion Report — Experiment Proposal Boundary

**Authorization:** تفويض صريح ومحدود لـC2-P4 فقط  
**C2-P0/P1/P2/P3:** PASS / PRESERVED  
**C1:** Officially Closed + Frozen Baseline  
**Phase A/B:** Stable  
**C2-P5/P6:** Not Started / Not Authorized

## 1. Final Status

**C2-P4 = PASS**

تم تنفيذ Proposal Boundary typed/companion فقط. لا يوجد Experiment Execution أو scheduling أو publish/workflow/A-B integration أو persistence في JSONL/SQLite. الـBoundary explicit وin-memory، ولا يملك `execute` أو `schedule` methods.

## 2. Scope Analysis and Files

### Files added

| الملف | الغرض |
|---|---|
| `mindmargin/intelligence/c2_proposals.py` | `C2ExperimentProposal` و`C2ExperimentProposalBoundary` وvalidation/lineage/security |
| `tests/unit/intelligence/test_c2_proposals.py` | اختبارات P4 boundary والـgates والعزل والتوافق |
| `C2_P4_COMPLETION_REPORT.md` | هذا التقرير |

### Dependencies used

- `C2HypothesisRegistry` و`C2HypothesisRecord` من P3.
- `C2ReadOnlyEvidenceAccess` من P1.
- P0 `C2ConfidenceValue` vocabulary where relevant.
- `MetricRegistry` الحالي للتحقق من metric ownership.
- `DecisionStore` فقط داخل الاختبارات لقراءة records حقيقية؛ لم يُعدّل adapter أو ledger.

### Protected files not modified

لم تُعدّل C1 أو P0/P1/P2/P3 أو Phase A/B أو legacy APIs أو `DecisionStore`/`EventLedger` أو JSONL/SQLite architecture أو production paths أو `PiperSettings.model_path`.

حالة working tree تحتوي على تغييرات سابقة خارج P4؛ ملفات P4 الخاصة محصورة في الملفين الجديدين أعلاه.

## 3. Contract and APIs

### `C2ExperimentProposal`

Companion/versioned proposal contract يحمل:

- `proposal_id`.
- `hypothesis_id`.
- `supporting_evidence_ids`.
- `decision_ids`.
- `metric_name`.
- `variants` مع control/treatment.
- `population` و`eligibility`.
- `minimum_sample`.
- `success_rule`.
- `inconclusive_rule`.
- `safety_constraints`.
- `rollback_criteria`.
- pipeline/content/video/correlation lineage داخل envelope.
- deterministic `idempotency_key`.
- proposal status: `proposed`, `validated`, أو `rejected`.

لا يعيد contract تعريف أو تعديل legacy `ExperimentResult`.

### `C2ExperimentProposalBoundary`

| API | السلوك |
|---|---|
| `propose(...)` | ينشئ proposal typed في الذاكرة فقط؛ لا ينفذ شيئًا |
| `get(proposal_id)` | يعيد proposal من registry in-memory |
| `validate(proposal)` | يطبق جميع entry/safety/lineage gates |
| `approve(proposal)` | يغير الحالة إلى `validated` بعد اجتياز validation فقط؛ لا execution |
| `get_lineage(proposal_id)` | يعيد `complete`, `partial`, أو `not_found` مع edges/IDs/warnings |

لا توجد methods للحفظ أو التنفيذ أو الجدولة أو mutation في production.

## 4. Validation and Safety Gates

لا يُقبل proposal validated إلا إذا تحققت الشروط التالية:

- Hypothesis موجودة عبر P3 وstatus=`testable`.
- causality status للفرضية=`not_claimed` ولا توجد causal language.
- Evidence IDs مطابقة لـHypothesis وقابلة للحل عبر P1.
- Evidence `validation_status=valid` وprovenance موجودة.
- Observation linkage موجود وquality/freshness صالحتان.
- Decision IDs موجودة وقابلة للحل ومطابقة للـscope.
- metric موجود في `MetricRegistry`.
- `minimum_sample` موجب ولا يقل عن 2.
- variants عددها على الأقل 2، IDs فريدة، وكل variant له description، مع control وtreatment.
- population يحدد unit وscope.
- eligibility يحدد rule أو description.
- success rule يحدد metric/operator/threshold/window.
- inconclusive rule يحدد metric/operator/threshold/window، ويختلف عن success rule.
- safety constraints موجودة، ولكل constraint condition/action.
- rollback criteria موجودة، ولكل criterion condition أو criterion/action.
- scope والـlineage متطابقان ولا توجد fabricated edges.
- لا توجد causal claims في proposal payload.

## 5. Lineage

يدعم P4 المسار:

```text
Evidence → Hypothesis → Experiment Proposal
Decision ────────────────────────┘
```

`get_lineage()` يعرض:

- `complete` عند حل Hypothesis وEvidence وDecision وسلامة P1 lineage.
- `partial` عند وجود missing أو invalid edges أو scope mismatch.
- `not_found` عند عدم حل proposal ID.
- `resolved_edges`.
- `missing_ids`.
- `invalid_edges`.
- `quality_warnings`.

لا يعتبر وجود `pipeline_id` وحده lineage مكتملًا، ولا ينشئ edges مفقودة.

## 6. Sampling and Result Rules

P4 يفرض minimum sample gate كشرط proposal مسبق، لكنه لا يجمع samples ولا يحسب results. كما يفرض success/inconclusive rules محددين مسبقًا، لكنه لا يقرر supported/rejected/inconclusive outcome ولا يطلق ExperimentResult.

> **Experiment Execution = NOT IMPLEMENTED**

## 7. Security and Compatibility

تم تطبيق allow-list serialization داخل companion contract. الاختبارات adversarial تغطي `api_key`, `token`, `secret`, `password`, `authorization`, Bearer values، و`raw_payload` داخل eligibility/nested metadata. الأسرار لا تظهر في serialized proposal، والحقول غير المسموح بها تُسقط.

تم الحفاظ على legacy `ExperimentResult` دون تعديل أو تحويل تلقائي. P4 لا يقرأ legacy hypothesis strings كـC2 HypothesisRecord ولا يكتب legacy experiment records.

## 8. Tests Added

اختبارات P4 تغطي:

1. valid proposal.
2. missing hypothesis/evidence/decision/metric.
3. insufficient minimum sample.
4. missing success/inconclusive rules.
5. missing safety/rollback.
6. invalid variants and missing control/treatment.
7. invalid eligibility/population.
8. scope/lineage mismatch.
9. causal claim rejection.
10. no experiment execution.
11. no production mutation.
12. legacy compatibility boundary.
13. security/redaction.
14. deterministic idempotency.
15. complete/partial/not_found lineage.

## 9. Test Results

| الاختبار | النتيجة |
|---|---:|
| P4 + P0/P1/P2/P3 tests | **55 passed, 0 failed** |
| P4/P0/P1/P2/P3 + Phase A/B/C1 targeted regression | **100 passed, 0 failed, 1 warning** |
| Full project suite | **1644 passed, 0 failed, 1 warning** |
| `python3 -m compileall -q mindmargin` | **PASS** |

التحذير الوحيد هو `PiperSettings.model_path` المعروف، ولم تتم معالجته التزامًا بالنطاق.

## 10. Governance and Deferred Decisions

- **C1:** FROZEN / UNCHANGED.
- **P0/P1/P2/P3:** PRESERVED دون تعديل دلالي.
- **Phase A/B:** UNCHANGED.
- **Legacy APIs/ExperimentResult:** UNCHANGED.
- **JSONL/SQLite:** UNCHANGED.
- **DecisionStore/EventLedger:** UNCHANGED.
- **Production paths:** UNCHANGED.
- **PiperSettings.model_path:** NOT ADDRESSED.
- **Experiment Execution:** NOT IMPLEMENTED.
- **Knowledge/Strategy:** NOT STARTED.
- **C2-P5/P6:** NOT STARTED / NOT AUTHORIZED.

قرارات مؤجلة قبل أي مرحلة لاحقة تشمل persistence/durable proposal identity، integration مع ExperimentResult، execution approval، ونتائج success/inconclusive الفعلية. جميعها خارج P4 وتحتاج authorization مستقلًا.

## Final Decision

# C2-P4 = PASS

تم إنجاز Proposal Boundary فقط، ولم يبدأ أي تنفيذ للتجارب أو Knowledge أو Strategy أو P5/P6.
