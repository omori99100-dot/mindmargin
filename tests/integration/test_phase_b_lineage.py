import json

from mindmargin.intelligence.contracts import DecisionStore, ExperimentResult, PipelineEvent
from mindmargin.intelligence import instrumentation
from mindmargin.intelligence.instrumentation import record_decision, record_event, record_experiment


def _store(monkeypatch, tmp_path):
    store = DecisionStore(tmp_path / "lineage.jsonl")
    monkeypatch.setattr(instrumentation, "_STORE", store)
    return store


def test_topic_selection_persists_options_scores_and_lineage(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    import mindmargin.analytics.memory as memory
    monkeypatch.setattr(memory, "get_top_opportunities", lambda limit=20: [
        {"topic": "A", "opportunity_score": 9.2, "confidence": 0.8},
        {"topic": "B", "opportunity_score": 7.1, "confidence": 0.6},
    ])
    monkeypatch.setattr(memory, "get_execution_log", lambda limit=100: [])

    from mindmargin.agents.decision_executor import select_topic
    selected = select_topic({}, {}, pipeline_id="pipe_topic")

    assert selected == "A"
    rows = store.decisions_for_pipeline("pipe_topic")
    assert len(rows) == 1
    assert rows[0]["decision_type"] == "topic_selection"
    assert rows[0]["selected_option"] == "A"
    assert rows[0]["options"][0]["score"] == 9.2
    assert rows[0]["pipeline_id"] == "pipe_topic"


def test_publish_failure_records_publish_and_packaging_decisions(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    out = tmp_path / "out"
    (out / "script").mkdir(parents=True)
    (out / "video").mkdir(parents=True)
    (out / "thumbnails").mkdir(parents=True)
    (out / "script" / "script.json").write_text(json.dumps({"word_count": 4, "hooks": []}))
    (out / "video" / "final_final.mp4").write_bytes(b"video")
    (out / "thumbnails" / "one.png").write_bytes(b"png")

    import mindmargin.integrations.youtube as youtube
    monkeypatch.setattr(youtube, "check_credentials", lambda: {"authenticated": True, "channel_name": "test"})
    monkeypatch.setattr(youtube, "upload_video", lambda **kwargs: {"status": "failed", "error": "quota"})
    import mindmargin.agents.metadata as metadata
    monkeypatch.setattr(metadata.MetadataAgent, "run", lambda self, topic, pipeline_id, script: {"metadata": {"best_title": "Title A", "all_titles": ["Title A", "Title B"], "description": "", "tags": []}})

    from mindmargin.agents.decision_executor import publish_video
    result = publish_video("topic", "pipe_publish", {"output_dir": str(out)})

    assert result["status"] == "failed"
    rows = store.decisions_for_pipeline("pipe_publish")
    types = {row["decision_type"] for row in rows}
    assert {"title_selection", "thumbnail_selection", "publish"}.issubset(types)
    assert any(row["status"] == "failed" for row in rows if row["decision_type"] == "publish")


def test_ab_inconclusive_and_winner_lifecycle_is_persisted(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    planned = ExperimentResult(
        experiment_id="exp_pipe_ab_title",
        hypothesis="title improves CTR",
        variable="title",
        variants=[{"index": 0}, {"index": 1}],
        success_metric="ctr",
        minimum_sample=100,
        sample_size=10,
        pipeline_id="pipe_ab",
        video_id="vid_ab",
    )
    record_experiment(planned)
    inconclusive = planned.declare_inconclusive({"reason": "not enough impressions"})
    record_experiment(inconclusive)
    record_decision("ab_winner_selection", pipeline_id="pipe_ab", experiment_id=planned.experiment_id, selected_option="INCONCLUSIVE", options=[{"option": 0}, {"option": 1}], rationale="minimum sample gate", evidence=[{"impressions": 10}], idempotency_key="pipe_ab:ab:title:inconclusive", source="test")
    record_event("experiment.inconclusive", "pipe_ab", experiment_id=planned.experiment_id, video_id="vid_ab")

    rows = store.ledger.read(pipeline_id="pipe_ab")
    assert any(row.get("record_type") == "experiment" and row.get("status") == "inconclusive" for row in rows)
    assert any(row.get("selected_option") == "INCONCLUSIVE" for row in rows)
    assert any(row.get("event_type") == "experiment.inconclusive" for row in rows)


def test_decision_idempotency_redaction_and_video_lineage_report(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    first = record_decision(
        "publish",
        pipeline_id="pipe_lineage",
        context={"api_key": "secret-value", "privacy": "private"},
        selected_option="publish",
        idempotency_key="pipe_lineage:publish:v1",
        source="test",
        video_id="vid_lineage",
    )
    second = record_decision(
        "publish",
        pipeline_id="pipe_lineage",
        context={"api_key": "secret-value", "privacy": "private"},
        selected_option="publish",
        idempotency_key="pipe_lineage:publish:v1",
        source="test",
        video_id="vid_lineage",
    )
    assert first["decision_id"] == second["decision_id"]
    assert len(store.decisions_for_pipeline("pipe_lineage")) == 1
    assert second["context"]["api_key"] == "[REDACTED]"

    record_event("publish.completed", "pipe_lineage", decision_id=first["decision_id"], video_id="vid_lineage", metadata={"authorization": "Bearer top-secret"})
    from mindmargin.intelligence.instrumentation import lineage_report
    report = lineage_report("pipe_lineage")
    assert report["decisions"][0]["video_id"] == "vid_lineage"
    assert report["events"][0]["metadata"]["authorization"] == "[REDACTED]"


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args, **_kwargs):
        return _Rows(self.rows)

    def commit(self):
        return None


def test_actual_ab_rotation_writes_inconclusive_record(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    rows = [
        {"id": 1, "pipeline_id": "pipe_cycle", "video_id": "vid_cycle", "variant_type": "title", "variant_index": 1, "variant_value": "A", "test_phase": "completed", "winner_flag": 0, "restored": 0, "ctr": 2.0, "watch_time_s": 10},
        {"id": 2, "pipeline_id": "pipe_cycle", "video_id": "vid_cycle", "variant_type": "title", "variant_index": 2, "variant_value": "B", "test_phase": "completed", "winner_flag": 0, "restored": 0, "ctr": 1.0, "watch_time_s": 9},
    ]
    import mindmargin.analytics.ab_testing as ab
    monkeypatch.setattr(ab, "get_active_ab_tests", lambda: [])
    monkeypatch.setattr(ab.memory, "_get_db", lambda: _Conn(rows))
    monkeypatch.setattr(ab, "_fetch_video_analytics", lambda video_id: {"impressions": 20, "views": 2, "ctr": 1.5, "watch_time_s": 9})

    result = ab.run_ab_rotation_cycle(dry_run=True)
    assert result["status"] == "completed"
    assert any(row.get("status") == "inconclusive" for row in store.ledger.read("experiment", "pipe_cycle"))
    assert any(row.get("selected_option") == "INCONCLUSIVE" for row in store.decisions_for_pipeline("pipe_cycle"))


def test_actual_ab_rotation_writes_winner_record(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    rows = [
        {"id": 3, "pipeline_id": "pipe_cycle2", "video_id": "vid_cycle2", "variant_type": "title", "variant_index": 1, "variant_value": "A", "test_phase": "completed", "winner_flag": 0, "restored": 0, "ctr": 4.0, "watch_time_s": 10},
        {"id": 4, "pipeline_id": "pipe_cycle2", "video_id": "vid_cycle2", "variant_type": "title", "variant_index": 2, "variant_value": "B", "test_phase": "completed", "winner_flag": 0, "restored": 0, "ctr": 2.0, "watch_time_s": 9},
    ]
    import mindmargin.analytics.ab_testing as ab
    monkeypatch.setattr(ab, "get_active_ab_tests", lambda: [])
    monkeypatch.setattr(ab.memory, "_get_db", lambda: _Conn(rows))
    monkeypatch.setattr(ab, "_fetch_video_analytics", lambda video_id: {"impressions": 200, "views": 50, "ctr": 4.0, "watch_time_s": 10})
    monkeypatch.setattr(ab, "set_ab_winner", lambda _id: None)
    monkeypatch.setattr(ab, "set_ab_restored", lambda _id: None)

    result = ab.run_ab_rotation_cycle(dry_run=True)
    assert result["status"] == "completed"
    assert any(row.get("winner") == "1" for row in store.ledger.read("experiment", "pipe_cycle2"))
    assert any(row.get("selected_option") == "1" for row in store.decisions_for_pipeline("pipe_cycle2"))


def test_connector_failure_is_not_false_success_and_is_instrumented(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    from mindmargin.integrations.youtube.connector import YouTubeConnector
    connector = YouTubeConnector(persist_dir=str(tmp_path / "connector"))
    connector._do_upload = lambda *args, **kwargs: {"status": "failed", "error": "quota"}
    result = connector.upload_video("missing.mp4", "Connector title", pipeline_id="pipe_connector", correlation_id="corr_connector")
    assert result["status"] == "failed"
    assert result["error"] == "quota"
    assert any(row["decision_type"] == "publish" and row["status"] == "failed" for row in store.decisions_for_pipeline("pipe_connector"))
    assert any(row.get("event_type") == "publish.failed" for row in store.ledger.read(pipeline_id="pipe_connector") if row.get("record_type") == "event")


def test_allowlist_redacts_unknown_nested_secrets_and_drops_raw_payload(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    record_event("outcome.recorded", "pipe_redact", metadata={
        "metrics": {"ctr": 4.2, "unknown_metric": "private payload", "secret_value": "do-not-write"},
        "unknown_payload": {"raw": "private payload"},
        "authorization": "Bearer very-secret",
    })
    row = store.ledger.read(pipeline_id="pipe_redact")[0]
    assert row["metadata"]["metrics"]["ctr"] == 4.2
    assert "unknown_payload" not in row["metadata"]
    assert "unknown_metric" not in row["metadata"]["metrics"]
    assert row["metadata"]["authorization"] == "[REDACTED]"
    assert "very-secret" not in json.dumps(row)


def test_completed_experiment_constructor_cannot_bypass_minimum_sample():
    import pytest
    with pytest.raises(ValueError):
        ExperimentResult(
            experiment_id="exp_invalid",
            hypothesis="invalid",
            variable="title",
            minimum_sample=100,
            sample_size=1,
            winner="1",
            status="completed",
        )


def test_lineage_report_distinguishes_not_found_and_partial(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    import mindmargin.analytics.lineage as lineage

    class _Row(dict):
        pass

    class _Result:
        def __init__(self, row):
            self.row = row
        def fetchone(self):
            return self.row

    class _Conn:
        def execute(self, query, params):
            if "youtube_video_id" in query:
                return _Result(None)
            if "COUNT" in query:
                return _Result({"count": 0})
            return _Result(None)

    monkeypatch.setattr(lineage, "_get_db", lambda: _Conn())
    assert lineage.get_video_lineage_report(video_id="missing") ["status"] == "not_found"

    store = instrumentation._STORE
    record_decision("topic_selection", pipeline_id="pipe_partial", selected_option="topic", options=[{"option": "topic"}], source="test")
    report = lineage.get_video_lineage_report(pipeline_id="pipe_partial")
    assert report["status"] == "partial"
    assert "publish_decision" in report["missing"]


def test_canonical_publish_entrypoint_writes_real_filesystem_lineage(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    out = tmp_path / "published"
    (out / "script").mkdir(parents=True)
    (out / "video").mkdir(parents=True)
    (out / "thumbnails").mkdir(parents=True)
    (out / "script" / "script.json").write_text(json.dumps({"word_count": 5, "hooks": []}))
    (out / "video" / "episode_final.mp4").write_bytes(b"video")
    (out / "thumbnails" / "thumb.png").write_bytes(b"png")

    import mindmargin.agents.decision_executor as executor
    import mindmargin.agents.metadata as metadata
    import mindmargin.integrations.youtube as youtube
    monkeypatch.setattr(youtube, "check_credentials", lambda: {"authenticated": True})
    monkeypatch.setattr(metadata.MetadataAgent, "run", lambda self, topic, pipeline_id, script: {"metadata": {"best_title": "E2E title", "all_titles": ["E2E title"], "description": "", "tags": []}})
    monkeypatch.setattr(youtube, "upload_video", lambda **kwargs: {"status": "completed", "video_id": "vid_e2e", "url": "https://youtu.be/vid_e2e"})
    monkeypatch.setattr(executor, "save_pipeline", lambda **kwargs: None)
    monkeypatch.setattr(executor, "save_titles", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "save_hooks", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "save_thumbnails", lambda *args, **kwargs: None)

    result = executor.publish_video("e2e topic", "pipe_e2e", {"output_dir": str(out)})
    assert result["status"] == "completed"
    rows = store.ledger.read(pipeline_id="pipe_e2e")
    assert any(row.get("record_type") == "decision" and row.get("decision_type") == "title_selection" for row in rows)
    assert any(row.get("record_type") == "event" and row.get("event_type") == "publish.completed" for row in rows)
    assert any(row.get("record_type") == "decision" and row.get("actual_outcome", {}).get("video_id") == "vid_e2e" for row in rows)
