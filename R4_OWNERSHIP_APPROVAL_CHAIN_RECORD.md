# R4 Ownership / Approval Chain Record

**Scope:** Production Authorization Readiness only  
**Reference Release Candidate:** `r4-rc-e1990e48a2c9109f714d`  
**Candidate immutable reference:** `release_candidates/r4-rc-e1990e48a2c9109f714d/release_snapshot.tar.gz`  
**Production Authorization:** `NOT_GRANTED`  
**Production Rollout:** `NOT_GRANTED`

## Approved Role Assignments

بناءً على التفويض الصريح الحالي، تم توثيق أن المسؤول الوحيد عن المشروع حاليًا هو **عمر محمد**، وأن التعيينات التالية معتمدة ضمن نطاق readiness فقط:

| Role | Named owner | Separation statement |
|---|---|---|
| Release Owner | عمر محمد | يملك تعريف الإصدار وإدارة candidate readiness |
| Technical Reviewer | عمر محمد | يراجع الاتساق التقني والاختبارات والـevidence |
| Production Approver | عمر محمد | يملك قرار الموافقة الإنتاجية، لكن هذا السجل لا يمنح الموافقة نفسها |
| Operator / Escalation Owner | عمر محمد | يملك التشغيل والتصعيد عند وجود تفويض تشغيل مستقل |

## Approval Chain

الترتيب المنطقي المفصول للصلاحيات هو:

1. **Release Owner:** عمر محمد يملك الإصدار وcandidate governance.
2. **Technical Reviewer:** عمر محمد يراجع candidate identity والـhashes والـreadiness evidence.
3. **Production Approver:** عمر محمد يملك قرار Production Authorization، لكن القرار غير ممنوح في هذا السجل.
4. **Operator / Escalation Owner:** عمر محمد يملك التشغيل والتصعيد فقط عند وجود authorization تشغيلية مستقلة.

تطابق الشخص بين الأدوار الأربعة موثق كحالة ملكية فردية للمشروع، ولا يلغي الفصل الوظيفي أو القيود الحوكمية بين الأدوار.

## Readiness Status

- `candidate_id`: `r4-rc-e1990e48a2c9109f714d`
- `candidate_status`: `CREATED_IMMUTABLE_SNAPSHOT`
- `source_reference`: `git:9bde981e5602446fb2fd9ec8bb741c986656f4cd`
- `approval_chain_status`: `READINESS_CHAIN_COMPLETE_PENDING_PRODUCTION_AUTHORIZATION`
- `ownership_chain_status`: `COMPLETE_FOR_READINESS`
- `production_authorization`: `NOT_GRANTED`
- `production_rollout`: `NOT_GRANTED`
- `piper_settings_model_path`: `ACCEPTED-RISK / DEFERRED-REMEDIATION`

## Integrity Constraints

هذا السجل منفصل عن immutable candidate ولا يغيره. لم تتغير candidate identity أو source reference أو artifact hashes أو snapshot contents. لا يمنح هذا السجل Production Authorization أو Production Rollout، ولا يسمح باستخدام production credentials أو traffic أو publish أو scheduler أو Workflow أو A/B activation.

تبقى C1 وC2-P0–P9 وPhase A/B وlegacy APIs و`ExperimentResult` وDecisionStore/EventLedger وJSONL/SQLite وWorkflow/SQLite remediation و`PiperSettings.model_path` محمية دون تعديل.

## Updated Gate Decision

# READY FOR SEPARATE PRODUCTION AUTHORIZATION

هذا القرار يعني أن **متطلب Ownership / Approval Chain أصبح مكتملًا ضمن readiness** وأنه يمكن طلب Production Authorization في مراجعة منفصلة. لا يعني أن Production Authorization مُنحت، ولا يعني بدء Production Rollout.
