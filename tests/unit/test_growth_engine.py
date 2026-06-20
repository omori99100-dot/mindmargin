"""Unit tests for analytics.growth_engine — growth intelligence."""

import pytest
from mindmargin.analytics.growth_engine import (
    expand_topic_tree, cluster_published_topics,
    identify_growth_opportunities, analyze_portfolio_balance,
    run_growth_analysis,
)


class TestExpandTopicTree:
    def test_returns_candidates(self):
        candidates = expand_topic_tree("ftx")
        assert isinstance(candidates, list)
        if candidates:
            assert "parent" in candidates[0]
            assert "child" in candidates[0]
            assert "confidence" in candidates[0]

    def test_unknown_topic(self):
        candidates = expand_topic_tree("nonexistent_topic_xyz")
        assert isinstance(candidates, list)


class TestClusterPublishedTopics:
    def test_returns_clusters(self):
        clusters = cluster_published_topics()
        assert isinstance(clusters, list)
        if clusters:
            assert "cluster" in clusters[0]
            assert "count" in clusters[0]


class TestIdentifyGrowthOpportunities:
    def test_returns_ranked_opportunities(self):
        ops = identify_growth_opportunities()
        assert isinstance(ops, list)
        if len(ops) > 1:
            assert ops[0]["score"] >= ops[1]["score"]

    def test_opportunity_structure(self):
        ops = identify_growth_opportunities()
        if ops:
            op = ops[0]
            assert "topic" in op
            assert "type" in op
            assert "score" in op
            assert "rationale" in op


class TestAnalyzePortfolioBalance:
    def test_returns_balance_report(self):
        balance = analyze_portfolio_balance()
        assert balance["status"] in ("completed", "insufficient_data")
        if balance["status"] == "completed":
            assert "cluster_distribution" in balance
            assert "concentration_index" in balance
            assert "recommendation" in balance


class TestRunGrowthAnalysis:
    def test_full_analysis(self):
        report = run_growth_analysis()
        assert report["status"] == "completed"
        assert "clusters" in report
        assert "opportunities" in report
        assert "portfolio_balance" in report
        assert "top_recommendations" in report
