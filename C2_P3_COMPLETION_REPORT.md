# C2-P3 Completion Report — Hypothesis Registry

**Authorization:** تفويض صريح ومحدود لـC2-P3 فقط  
**C2-P0:** PASS / CLOSED / PRESERVED  
**C2-P1:** PASS / CLOSED / PRESERVED  
**C2-P2:** PASS / CLOSED / PRESERVED  
**C1:** OFFICIALLY CLOSED + FROZEN BASELINE  
**Phase A/B:** STABLE  
**C2-P4 وما بعده:** NOT STARTED / NOT AUTHORIZED

## 1. Final Status

**C2-P3 = PASS**

تم تنفيذ Hypothesis Registry مستقل ومحدود فوق P0/P1/P2. الـRegistry in-memory فقط، explicit، evidence-backed، ولا يملك persistence أو production coupling أو autonomous behavior. لا ينشئ `supported` من observational evidence، ولا ينفذ Experiment أو Knowledge أو Strategy أو causal inference.

## 2. Scope Analysis

### Files added

| الملف | الغرض |
|---|---|
| `mindmargin/intelligence/c2_hypothesis.py` | `C2HypothesisRegistry` وvalidation وlineage وin-memory idempotency |
| `tests/unit/intelligence/test_c2_hypothesis.py` | اختبارات P3 للـentry criteria وlifecycle وlineage وsecurity وlegacy coexistence |
| `C2_P3_COMPLETION_REPORT.md` | تقرير الإغلاق |

### Dependencies read and used

استخدم P3 فقط:

- `C2ReadOnlyEvidenceAccess` من P1 للقراءة typed/read-only.
- `LineageScope` وP1 lineage view.
- `C2HypothesisRecord` و`C2ConfidenceValue` من P0 دون تعديل.
- validated `C2DiagnosisRecord` من P2 عند المسار diagnosis-backed.
- legacy contracts للـcompatibility verification دون تحويل تلقائي.

### Protected files not modified

لم تُعدّل C1 code/contracts/tests، أو P0/P1/P2 modules، أو Phase A/B، أو legacy APIs، أو `DecisionStore`/`EventLedger`، أو JSONL/SQLite architecture، أو production paths، أو `PiperSettings.model_path`.

تغييرات working tree السابقة خارج P3 بقيت كما هي ولم تُعتبر جزءًا من تنفيذ P3. ملفات P3 الجديدة محصورة في الملفين أعلاه.

## 3. APIs Implemented

### `C2HypothesisRegistry.propose(...)`

ينشئ `C2HypothesisRecord` companion/versioned من P0 ويسجله داخل Registry في الذاكرة فقط. يفرض statement، supporting Evidence IDs، measurable prediction، falsification condition، inconclusive condition، expected direction، limitations، confidence، scope، وoptional diagnosis IDs.

لا يقوم `propose` بالتحويل من legacy hypothesis strings، ولا يقرأ raw JSONL مباشرة، ولا يكتب ledger.

### `register(...)` و`get(...)`

`register` يقبل P0 HypothesisRecord موجودًا ويمنع duplicate logical identity في registry. `get` يعيد record الموجود داخل الذاكرة فقط.

### `validate(...)`

يتحقق من entry criteria التالية:

- supporting Evidence IDs غير فارغة وقابلة للحل عبر P1.
- Evidence `validation_status=valid`.
- Evidence provenance موجودة.
- Observation IDs قابلة للحل وObservation quality valid.
- Observation freshness معروفة.
- scope تطابق pipeline/content/video/correlation.
- lineage complete ولا توجد missing أو invalid edges.
- diagnosis IDs قابلة للحل عند وجودها.
- Diagnosis status `validated` وليست invalid، وEvidence linkage صحيح.
- statement/prediction/falsification/inconclusive conditions غير فارغة.
- expected direction صالح وفق P0 vocabulary.
- causality status يساوي `not_claimed`.
- confidence من `C2ConfidenceValue` وlimitations موجودة.
- alternatives evidence-linked وغير سببية.

الفشل يعيد `HypothesisValidation(valid=False, status="rejected")` ولا يحوّل record إلى testable.

### `mark_testable(...)`

ينقل hypothesis من `proposed` إلى `testable` فقط بعد نجاح validation. لا ينشئ `tested` أو `supported` أو `rejected` أو `inconclusive` تشغيليًا من P3.

### `register_from_diagnosis(...)`

يقبل فقط P2 `C2DiagnosisRecord` بحالة `validated`، ويربط Diagnosis وEvidence وObservation صراحةً، ثم يعيد proposed/testable outcome حسب validation. لا يحول legacy DiagnosisRecord تلقائيًا.

### `transition(...)`

يسمح في P3 فقط بالانتقال إلى `testable`. أي transition مستقبلي مرتبط بنتيجة اختبار أو governance يرفع رفضًا صريحًا؛ لا يبدأ Experiment أو Result flow.

### `get_lineage(...)`

يعيد:

- `complete`.
- `partial`.
- `not_found`.
- `resolved_edges`.
- `missing_ids`.
- `invalid_edges`.
- `quality_warnings`.
- `records_by_type` بما يشمل hypothesis وdiagnosis عند resolution.

لا ينشئ edges مفقودة، ولا يعتبر pipeline ID وحده lineage كاملًا.

## 4. Lifecycle and Invariants

يلتزم P3 بعقد P0:

```text
proposed → testable
```

أما `tested`, `supported`, `rejected`, `inconclusive`, و`superseded` فتبقى transitions محجوزة لنتيجة خارجية أو مرحلة مستقبلية، باستثناء أن validation failure يعيد `HypothesisValidation` بحالة `rejected` دون إنتاج lifecycle transition تشغيلي جديد من P3.

ولا يمكن في P3:

- إنتاج `supported` من observational Evidence.
- رفع confidence بسبب retry أو duplicate read أو تكرار نفس Evidence.
- إنشاء causal confidence أو probability of cause.
- اعتبار correlation أو observational evidence إثباتًا سببيًا.
- اعتبار partial/missing/invalid Evidence دعمًا صالحًا.

## 5. Evidence → Diagnosis → Hypothesis Lineage

في المسار evidence-backed المباشر، يستخدم Hypothesis supporting Evidence IDs وsource/parent IDs صريحة. وفي المسار diagnosis-backed، يتم حفظ diagnosis IDs مع Evidence IDs وtarget Observation IDs، والتحقق من أن Diagnosis validated وأن Evidence مشتركة فعليًا.

`get_lineage` يستعمل P1 read-only lineage view، ثم يضيف edges صريحة من Evidence إلى Hypothesis ومن Diagnosis إلى Hypothesis. إذا كان أي ID مفقودًا أو scope غير متطابق، تكون النتيجة `partial` مع `missing_ids` و`invalid_edges`. إذا لم يُحل Hypothesis ID فالحالة `not_found`.

## 6. Confidence and Semantics

يستخدم P3 `C2ConfidenceValue` من P0 مع dimension وbasis وlimitations. لا يضيف `causal_confidence` أو `probability_of_cause`. Hypothesis هي testable claim وليست fact أو causal claim.

الصياغات causal في statement أو prediction أو falsification أو inconclusive condition أو alternatives تُرفض. كما يمنع P0 أي `causality_status` غير `not_claimed`.

## 7. Idempotency

الـlogical identity deterministic من:

- statement.
- scope.
- supporting Evidence IDs.
- measurable prediction.
- falsification condition.

نفس identity تعيد نفس Hypothesis ID داخل Registry نفسه. Evidence مختلفة أو prediction مختلفة تنتج identity مختلفة. transition حقيقي لا يعامل كduplicate؛ وهو محجوز أصلًا خارج P3. لم يتم الادعاء بـdurability بعد restart لأن P3 in-memory فقط.

## 8. Security and Redaction

يعتمد P3 على allow-list serialization في P0 ولا يضيف raw payload fields. اختبارات adversarial تغطي `api_key`, `token`, `secret`, `password`, `authorization`, Bearer values، `raw_payload`, وnested metadata داخل statement وlimitations.

النتيجة: لا تصل الأسرار إلى serialized Hypothesis، والحقول الخام غير المسموح بها لا تبقى في payload. كما يثبت اختبار العزل أن Registry لا يضيف rows إلى ledger ولا يغير production state.

## 9. Legacy Compatibility

تم التحقق من coexistence مع legacy `ExperimentResult.hypothesis` string. يتم حفظ legacy experiment كما هو، ولا يوجد conversion تلقائي إلى `C2HypothesisRecord`. لم تُعدّل legacy DiagnosisRecord أو legacy hypothesis fields أو legacy APIs.

## 10. Tests Added

اختبارات P3 تغطي:

1. valid Evidence → testable Hypothesis.
2. validated P2 Diagnosis → linked testable Hypothesis.
3. missing Evidence → rejection.
4. invalid Evidence → rejection.
5. stale Observation/Evidence path → rejection.
6. missing provenance → rejection.
7. Diagnosis scope mismatch → rejection.
8. missing measurable prediction.
9. missing falsification condition.
10. missing inconclusive condition.
11. invalid expected direction.
12. causal claim language.
13. non-`not_claimed` causality status.
14. alternatives + limitations.
15. complete/partial/not_found lineage.
16. missing lineage edges.
17. deterministic idempotency and retry no duplicate.
18. confidence semantics.
19. supported/tested transitions blocked in P3.
20. legacy hypothesis string not auto-converted.
21. adversarial secret/redaction.
22. no ledger persistence or production mutation.

## 11. Test Results

| الاختبار | النتيجة |
|---|---:|
| P3 + P2 + P1 + P0 tests | **43 passed, 0 failed** |
| P3/P2/P1/P0 + Phase A/B/C1 targeted regression | **88 passed, 0 failed, 1 warning** |
| Full project suite | **1632 passed, 0 failed, 2 warnings** |
| `python3 -m compileall -q mindmargin` | **PASS** |

التحذير الأول هو `PiperSettings.model_path`، ولم تتم معالجته التزامًا بالنطاق. التحذير الثاني هو `PytestUnhandledThreadExceptionWarning` من workflow thread موجود في baseline أثناء `test_start_unknown` بسبب `FileNotFoundError` في resource temporary path؛ لم تتم معالجته لأنه خارج P3 ويمس production/workflow baseline.

## 12. Remaining Issues and Deferred Decisions

لا توجد High أو Medium issues ناتجة عن P3 نفسه. توجد قرارات مؤجلة قبل P4:

| القرار | سبب التأجيل |
|---|---|
| persistence/durable idempotency | P3 in-memory فقط، وأي ledger integration يحتاج تفويضًا مستقلًا |
| tested/supported/rejected/inconclusive transitions | تحتاج نتيجة اختبار أو governance مستقبلية، وممنوعة في P3 |
| public package exports | لم يُعدّل `__init__.py` أو public API surface |
| lexical causal vocabulary | detector bounded وليس causal inference؛ يلزم vocabulary governance لاحقًا |
| workflow thread warning | خارج P3، ولا يجوز إصلاحه ضمن هذا التفويض |

## 13. Governance Confirmation

- **C1 = FROZEN / UNCHANGED**.
- **P0/P1/P2 = PRESERVED**.
- **Phase A/B = UNCHANGED**.
- **Legacy APIs/contracts = UNCHANGED**.
- **DecisionStore/EventLedger/JSONL/SQLite = UNCHANGED**.
- **Production paths = UNCHANGED**.
- **PiperSettings.model_path = NOT ADDRESSED**.
- **Experiment Proposal/Execution = NOT STARTED**.
- **Knowledge = NOT STARTED**.
- **Strategy = NOT STARTED**.
- **Causal inference = NOT IMPLEMENTED**.
- **Autonomous agent = NOT IMPLEMENTED**.
- **C2-P4 = NOT STARTED / NOT AUTHORIZED**.

## Final Decision

# C2-P3 = PASS

تم تنفيذ Hypothesis Registry ضمن التفويض المحدود فقط، مع إبقاء كل قدرات P4 وما بعدها خارج النطاق وغير مصرح بها.
