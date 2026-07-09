"""Tests for Experiment Engine (intelligence/experiments.py)."""

from unittest.mock import patch, MagicMock
from mindmargin.intelligence.experiments import (
    ExperimentGenerator, ExperimentEvaluator, run_experiment_cycle,
)


class TestExperimentGenerator:
    def test_generate_all_with_opportunities(self):
        gen = ExperimentGenerator()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.save_experiment") as mock_save, \
             patch("mindmargin.analytics.memory.get_experiments") as mock_existing, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist:
            mock_opps.return_value = [{"topic": "AI Revolution", "opportunity_score": 85}]
            mock_existing.return_value = []
            mock_hist.return_value = []
            mock_save.return_value = None

            result = gen.generate_all()
            assert len(result) >= 1
            assert result[0]["topic"] == "AI Revolution"

    def test_generate_all_without_opportunities(self):
        gen = ExperimentGenerator()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_experiments") as mock_existing, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist:
            mock_opps.return_value = []
            mock_existing.return_value = []
            mock_hist.return_value = []

            result = gen.generate_all()
            assert result == []

    def test_hypothesis_structure(self):
        gen = ExperimentGenerator()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.save_experiment") as mock_save, \
             patch("mindmargin.analytics.memory.get_experiments") as mock_existing, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist:
            mock_opps.return_value = [{"topic": "Test", "opportunity_score": 80}]
            mock_existing.return_value = []
            mock_hist.return_value = []
            mock_save.return_value = None

            result = gen.generate_all()
            assert len(result) > 0
            for exp in result:
                assert "experiment_id" in exp
                assert "hypothesis" in exp
                assert "experiment_type" in exp
                assert "topic" in exp
                assert "variant_a" in exp
                assert "variant_b" in exp

    def test_all_experiment_types_generated(self):
        gen = ExperimentGenerator()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.save_experiment") as mock_save, \
             patch("mindmargin.analytics.memory.get_experiments") as mock_existing, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist:
            mock_opps.return_value = [{"topic": "Test", "opportunity_score": 80}]
            mock_existing.return_value = []
            mock_hist.return_value = [{"topic": "Published Video", "views": 100}]
            mock_save.return_value = None

            result = gen.generate_all()
            types = set(e["experiment_type"] for e in result)
            assert "topic_angle" in types
            assert "title_style" in types
            assert "shorts_vs_long" in types
            assert "thumbnail_style" in types
            assert "hook_variation" in types
            assert "upload_timing" in types


class TestExperimentEvaluator:
    def test_evaluate_treatment_wins(self):
        evaluator = ExperimentEvaluator()
        with patch.object(evaluator, "_find_video_for_pipeline") as mock_find, \
             patch.object(evaluator, "_get_latest_analytics") as mock_stats:
            mock_find.side_effect = ["vid_a", "vid_b"]
            mock_stats.side_effect = [
                {"views": 100, "ctr": 0.05, "retention": 0.4, "engagement_rate": 0.02},
                {"views": 300, "ctr": 0.08, "retention": 0.6, "engagement_rate": 0.05},
            ]
            result = evaluator._evaluate_single({
                "experiment_id": "test_1",
                "control_pipeline_id": "pipe_a",
                "treatment_pipeline_id": "pipe_b",
                "affected_metric": "views",
            })
            assert result is not None
            assert result["winner"] == "treatment"

    def test_evaluate_not_enough_data(self):
        evaluator = ExperimentEvaluator()
        result = evaluator._evaluate_single({
            "experiment_id": "test_2",
            "control_pipeline_id": "",
            "treatment_pipeline_id": "",
        })
        assert result is None

    def test_evaluate_tie(self):
        evaluator = ExperimentEvaluator()
        with patch.object(evaluator, "_find_video_for_pipeline") as mock_find, \
             patch.object(evaluator, "_get_latest_analytics") as mock_stats:
            mock_find.side_effect = ["vid_a", "vid_b"]
            mock_stats.side_effect = [
                {"views": 100, "ctr": 0.05},
                {"views": 105, "ctr": 0.051},
            ]
            result = evaluator._evaluate_single({
                "experiment_id": "test_3",
                "control_pipeline_id": "pipe_a",
                "treatment_pipeline_id": "pipe_b",
                "affected_metric": "views",
            })
            assert result is not None
            assert result["winner"] == "tie"


class TestRunExperimentCycle:
    def test_full_cycle(self):
        with patch.object(ExperimentGenerator, "generate_all") as mock_gen, \
             patch.object(ExperimentEvaluator, "evaluate_all") as mock_eval:
            mock_gen.return_value = [{"experiment_id": "e1"}]
            mock_eval.return_value = [{"experiment_id": "e1", "winner": "treatment"}]

            result = run_experiment_cycle()
            assert result["new_hypotheses"] == 1
            assert result["experiments_completed"] == 1
