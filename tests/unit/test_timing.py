"""Tests for core/timing.py — Timer."""

import json
from unittest.mock import patch

import pytest

from mindmargin.core.timing import Timer


class TestTimerStart:
    def test_start_initializes(self):
        t = Timer()
        t.start("init")
        assert t._start is not None
        assert t._current_label == "init"
        assert len(t._laps) == 1
        assert t._laps[0]["label"] == "init"

    def test_start_default_label(self):
        t = Timer()
        t.start()
        assert t._laps[0]["label"] == "start"


class TestTimerLap:
    def test_lap_records_elapsed(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[100.0, 103.5]):
            t = Timer()
            t.start("begin")
            entry = t.lap("mid")
        assert entry["label"] == "mid"
        assert entry["elapsed_s"] == 3.5

    def test_lap_appends_to_laps(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[0.0, 1.0, 2.5]):
            t = Timer()
            t.start()
            t.lap("a")
            t.lap("b")
        assert len(t._laps) == 3


class TestTimerStop:
    def test_stop_records_final_lap(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[10.0, 12.0]):
            t = Timer()
            t.start()
            entry = t.stop("done")
        assert entry["label"] == "done"
        assert entry["elapsed_s"] == 2.0

    def test_stop_clears_start(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[10.0, 12.0]):
            t = Timer()
            t.start()
            t.stop()
        assert t._start is None


class TestTimerTotalS:
    def test_total_s_with_multiple_laps(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[10.0, 11.5, 13.0]):
            t = Timer()
            t.start()
            t.lap("a")
            t.lap("b")
        assert t.total_s == 3.0

    def test_total_s_less_than_two_laps_returns_zero(self):
        t = Timer()
        t.start()
        assert t.total_s == 0.0

    def test_total_s_no_data_returns_zero(self):
        t = Timer()
        assert t.total_s == 0.0


class TestTimerSummary:
    def test_summary_returns_lap_deltas(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[10.0, 12.0, 13.5]):
            t = Timer()
            t.start("start")
            t.lap("step1")
            t.lap("step2")
        assert t.summary() == "step1: 2.0s | step2: 1.5s"

    def test_summary_no_data(self):
        t = Timer()
        assert t.summary() == "no timing data"

    def test_summary_single_lap_no_data(self):
        t = Timer()
        t.start()
        assert t.summary() == "no timing data"


class TestTimerElapsedMonotonic:
    def test_elapsed_increases_between_laps(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[10.0, 11.0, 13.0]):
            t = Timer()
            t.start()
            lap1 = t.lap("first")
            lap2 = t.lap("second")
        assert lap1["elapsed_s"] < lap2["elapsed_s"]


class TestTimerRoundTrip:
    def test_serialize_deserialize(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[10.0, 11.2, 12.8]):
            t = Timer()
            t.start("init")
            t.lap("mid")
            t.stop("end")
        data = {
            "laps": t._laps,
            "current_label": t._current_label,
        }
        restored = Timer()
        restored._laps = data["laps"]
        restored._current_label = data["current_label"]
        restored._start = None
        assert len(restored._laps) == 3
        assert restored._laps[-1]["label"] == "end"
        assert restored.total_s == 2.8
        assert restored.summary() != "no timing data"

    def test_round_trip_json(self):
        with patch("mindmargin.core.timing.time.time", side_effect=[10.0, 10.5, 11.0]):
            t = Timer()
            t.start()
            t.lap("a")
            t.lap("b")
        raw = json.dumps(t._laps)
        laps = json.loads(raw)
        restored = Timer()
        restored._laps = laps
        restored._start = None
        assert restored.total_s == 1.0
        assert "a: 0.5s | b: 0.5s" in restored.summary()
