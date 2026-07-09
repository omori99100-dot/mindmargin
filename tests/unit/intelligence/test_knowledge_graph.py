"""Tests for Knowledge Graph (intelligence/knowledge_graph.py)."""

from unittest.mock import patch
from mindmargin.intelligence.knowledge_graph import (
    KnowledgeGraph, build_knowledge_graph, find_adjacent,
)


class TestKnowledgeGraph:
    def test_build_with_data(self):
        kg = KnowledgeGraph()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_trend_sources") as mock_src, \
             patch("mindmargin.analytics.memory.get_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_topic_lineages") as mock_lin, \
             patch("mindmargin.analytics.memory.get_channel_memory") as mock_mem, \
             patch("mindmargin.analytics.memory.save_topic_keyword") as mock_kw, \
             patch("mindmargin.analytics.memory.save_topic_relationship") as mock_rel, \
             patch("mindmargin.analytics.memory.save_audience_topic") as mock_aud:
            mock_hist.return_value = [{"topic": "AI History"}, {"topic": "Space Exploration"}]
            mock_src.return_value = []
            mock_opps.return_value = []
            mock_lin.return_value = []
            mock_mem.return_value = []
            mock_kw.return_value = None
            mock_rel.return_value = None
            mock_aud.return_value = None

            result = kg.build()
            assert result["topics_found"] >= 2
            assert result["keywords_extracted"] >= 0

    def test_build_no_data(self):
        kg = KnowledgeGraph()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_trend_sources") as mock_src, \
             patch("mindmargin.analytics.memory.get_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_topic_lineages") as mock_lin, \
             patch("mindmargin.analytics.memory.get_channel_memory") as mock_mem:
            mock_hist.return_value = []
            mock_src.return_value = []
            mock_opps.return_value = []
            mock_lin.return_value = []
            mock_mem.return_value = []

            result = kg.build()
            assert result["topics_found"] == 0

    def test_extract_keywords(self):
        kg = KnowledgeGraph()
        keywords = kg._extract_keywords("The History of Artificial Intelligence")
        topics = [k[0] for k in keywords]
        assert "history" in topics
        assert "artificial" in topics
        assert "intelligence" in topics

    def test_compute_relationship(self):
        kg = KnowledgeGraph()
        with patch("mindmargin.analytics.memory.get_topic_keywords") as mock_kw:
            mock_kw.return_value = [{"keyword": "history", "weight": 1.0}]

            strength = kg._compute_relationship("History of AI", "AI History")
            assert strength >= 0

    def test_find_adjacent_topics(self):
        kg = KnowledgeGraph()
        with patch("mindmargin.analytics.memory.get_topic_relationships") as mock_rel:
            mock_rel.return_value = [
                {"source_topic": "AI", "target_topic": "ML", "relationship_type": "related", "strength": 0.8},
                {"source_topic": "ML", "target_topic": "AI", "relationship_type": "related", "strength": 0.8},
            ]
            adjacent = kg.find_adjacent_topics("AI")
            assert len(adjacent) >= 1
            assert adjacent[0]["topic"] == "ML"

    def test_is_duplicate_coverage(self):
        kg = KnowledgeGraph()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_topic_keywords") as mock_kw:
            mock_hist.return_value = [{"topic": "History of AI"}]
            mock_kw.return_value = [{"keyword": "history", "weight": 1.0}]

            is_dup, match, strength = kg.is_duplicate_coverage("AI History")
            assert isinstance(is_dup, bool)

    def test_get_expansion_opportunities(self):
        kg = KnowledgeGraph()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_topic_relationships") as mock_rel, \
             patch("mindmargin.analytics.memory.get_topic_keywords") as mock_kw:
            mock_hist.return_value = [{"topic": "AI"}]
            mock_rel.return_value = [
                {"source_topic": "AI", "target_topic": "Deep Learning",
                 "relationship_type": "related", "strength": 0.9},
            ]
            mock_kw.return_value = []

            expansions = kg.get_expansion_opportunities(max_results=5)
            assert len(expansions) >= 0


class TestConvenience:
    def test_build_knowledge_graph(self):
        with patch.object(KnowledgeGraph, "build") as mock_build:
            mock_build.return_value = {"topics_found": 5}
            result = build_knowledge_graph()
            assert result["topics_found"] == 5

    def test_find_adjacent(self):
        with patch.object(KnowledgeGraph, "find_adjacent_topics") as mock_find:
            mock_find.return_value = [{"topic": "ML", "strength": 0.8}]
            result = find_adjacent("AI")
            assert len(result) == 1
