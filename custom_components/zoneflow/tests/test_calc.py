"""Teste pentru modulul pur de calcul al irigației."""

import math
import os
import sys

import pytest

# Permite rularea cu `pytest` din rădăcina proiectului fără instalare.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calc import (  # noqa: E402
    overlap_delivered,
    precip_rate,
    runtime_simple,
    runtimes_overlap,
    target_mm,
    weekly_avg,
)


def test_precip_rate():
    assert precip_rate(10, 10) == 1.0
    assert precip_rate(0, 10) == 0.0
    assert precip_rate(5, 0) == 0.0  # durată invalidă


def test_runtime_simple_basic():
    # 10 mm adunate în 10 min => 1 mm/min => pentru 25 mm țintă => 25 min
    assert runtime_simple(25, 10, 10) == pytest.approx(25.0)


def test_runtime_simple_no_water():
    assert runtime_simple(25, 0, 10) == 0.0


def test_overlap_mid_uniform_edge_zero():
    # mid udă la fel pe interior și margine => edge nu e necesar
    t_mid, t_edge = runtimes_overlap(20, d_mid_inner=10, d_mid_margin=10, d_edge_margin=5, test_minutes=10)
    assert t_mid == pytest.approx(20.0)
    assert t_edge == pytest.approx(0.0)


def test_overlap_mid_weak_on_margin_needs_edge():
    # mid: 10mm/10min interior, dar doar 6mm/10min pe margine; edge: 8mm/10min pe margine
    q = 20.0
    t_mid, t_edge = runtimes_overlap(q, d_mid_inner=10, d_mid_margin=6, d_edge_margin=8, test_minutes=10)
    assert t_mid == pytest.approx(20.0)  # 20 / (10/10)
    assert t_edge > 0.0
    # ambele jumătăți trebuie să primească exact ținta
    inner, margin = overlap_delivered(t_mid, t_edge, 10, 6, 8, 10)
    assert inner == pytest.approx(q)
    assert margin == pytest.approx(q)


def test_overlap_clamp_negative():
    # mid supra-udă marginea => deficit negativ => edge clamp la 0
    t_mid, t_edge = runtimes_overlap(10, d_mid_inner=10, d_mid_margin=20, d_edge_margin=5, test_minutes=10)
    assert t_edge == 0.0


def test_overlap_edge_unreachable():
    # edge nu ajunge pe margine (0) => t_edge = 0 chiar dacă există deficit
    _, t_edge = runtimes_overlap(20, d_mid_inner=10, d_mid_margin=6, d_edge_margin=0, test_minutes=10)
    assert t_edge == 0.0


def test_weekly_avg():
    assert weekly_avg([20, 30]) == pytest.approx(25.0)
    assert weekly_avg([20, None, 30]) == pytest.approx(25.0)
    assert weekly_avg([None, None]) is None
    assert weekly_avg([]) is None


def test_target_mm():
    assert target_mm(25) == pytest.approx(25.0)
    assert target_mm(25, factor=0.8) == pytest.approx(20.0)
    assert target_mm(None) is None
    assert target_mm(-5, min_mm=0) == 0.0
    assert target_mm(40, max_mm=30) == 30.0


def test_target_then_runtime_end_to_end():
    # media 25°C => 25 L/m² => cu 10mm/10min => 25 min
    q = target_mm(weekly_avg([24, 26]))
    assert q == pytest.approx(25.0)
    assert runtime_simple(q, 10, 10) == pytest.approx(25.0)
    assert not math.isnan(q)
