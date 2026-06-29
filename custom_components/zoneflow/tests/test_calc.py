"""Teste pentru modulul pur de calcul al irigației."""

import math
import os
import sys

import pytest

# Permite rularea cu `pytest` din rădăcina proiectului fără instalare.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calc import (  # noqa: E402
    coverage,
    effective_target,
    overlap_delivered,
    precip_rate,
    runtime_edge,
    runtime_simple,
    runtimes_overlap,
    solve_runtimes,
    target_mm,
    weekly_avg,
    weighted_precipitation,
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


def test_runtime_edge_matches_overlap():
    # runtime_edge trebuie să dea același t_edge ca runtimes_overlap (1 edge)
    t_mid, t_edge = runtimes_overlap(20, d_mid_inner=10, d_mid_margin=6, d_edge_margin=8, test_minutes=10)
    assert runtime_edge(20, t_mid, 6, 8, 10) == pytest.approx(t_edge)


def test_runtime_edge_no_reach():
    assert runtime_edge(20, t_primary=20, primary_margin_depth=6, edge_depth=0, test_minutes=10) == 0.0


def test_overlap_two_edges_uniform():
    # Un primar + 2 circuite margine pe sub-zone diferite; toate sub-zonele primesc ținta.
    q = 20.0
    t_primary = runtime_simple(q, 10, 10)  # interior: 1mm/min -> 20 min
    assert t_primary == pytest.approx(20.0)
    # primar pe margine: 6mm/10min = 0.6 mm/min -> depune 12 mm în 20 min, deficit 8 mm
    t_e1 = runtime_edge(q, t_primary, primary_margin_depth=6, edge_depth=8, test_minutes=10)
    t_e2 = runtime_edge(q, t_primary, primary_margin_depth=6, edge_depth=4, test_minutes=10)
    assert t_e1 == pytest.approx(10.0)  # 8 / 0.8
    assert t_e2 == pytest.approx(20.0)  # 8 / 0.4
    # verificare livrare pe fiecare sub-zonă
    for edge_depth, t_edge in ((8, t_e1), (4, t_e2)):
        delivered = precip_rate(6, 10) * t_primary + precip_rate(edge_depth, 10) * t_edge
        assert delivered == pytest.approx(q)


def test_solve_single_group():
    # 1 porțiune, 1 grup: 8mm/10min = 0.8 mm/min, țintă 20 -> 25 min
    rt = solve_runtimes([[0.8]], 20)
    assert rt == pytest.approx([25.0])
    assert coverage([[0.8]], rt) == pytest.approx([20.0])


def test_solve_two_groups_same_section_sum():
    # Fața: 1 porțiune, 2 grupuri (ambele 0.8) -> împart, însumează ținta
    rt = solve_runtimes([[0.8, 0.8]], 20)
    assert coverage([[0.8, 0.8]], rt) == pytest.approx([20.0])
    assert rt[0] == pytest.approx(rt[1])  # simetric


def test_solve_two_sections_mid_margin():
    # Spate: porțiuni [interior, margine], grupuri [mijloc, margine]
    A = [[1.0, 0.0], [0.6, 0.8]]
    rt = solve_runtimes(A, 20)
    assert rt == pytest.approx([20.0, 10.0])
    assert coverage(A, rt) == pytest.approx([20.0, 20.0])


def test_solve_diagonal_independent():
    rt = solve_runtimes([[1.0, 0.0], [0.0, 0.5]], 20)
    assert rt == pytest.approx([20.0, 40.0])


def test_solve_clamps_negative():
    # Soluția exactă ar cere un timp negativ -> grupul respectiv devine 0
    A = [[1.0, 1.0], [1.0, 2.0]]
    rt = solve_runtimes(A, 20)
    assert rt[1] == 0.0
    assert rt[0] >= 0.0


def test_solve_no_groups_or_zero_target():
    assert solve_runtimes([], 20) == []
    assert solve_runtimes([[0.8, 0.5]], 0) == [0.0, 0.0]
    assert solve_runtimes([[0.8, 0.5]], None) == [0.0, 0.0]


def test_weighted_precipitation():
    # 10mm la 50% -> 5; 4mm la 100% (None) -> 4; total 9
    assert weighted_precipitation([(10, 50), (4, None)]) == pytest.approx(9.0)
    # valori lipsă / negative ignorate
    assert weighted_precipitation([(None, 80), (-2, 100), (6, 100)]) == pytest.approx(6.0)
    assert weighted_precipitation([]) == 0.0
    # probabilitate clamp la [0,100]
    assert weighted_precipitation([(10, 150)]) == pytest.approx(10.0)


def test_effective_target():
    assert effective_target(25, 8) == pytest.approx(17.0)
    assert effective_target(25, 30) == 0.0  # plouă mai mult decât ținta -> skip
    assert effective_target(25, 0) == pytest.approx(25.0)
    assert effective_target(None, 5) is None
    assert effective_target(25, -3) == pytest.approx(25.0)  # ploaie negativă ignorată


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
