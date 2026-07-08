"""Calcule pure pentru integrarea de irigație.

Modul fără dependențe de Home Assistant, ca să poată fi testat independent cu pytest.

Convenții:
- adâncimea apei adunate în caserolă (mm) într-un test de `test_minutes` minute;
- 1 mm de apă = 1 L/m² (deci „țintă în mm" și „țintă în L/m²" sunt același număr);
- rata de precipitație PR = adâncime / durată  [mm/min].
"""

from __future__ import annotations

from collections.abc import Iterable


def precip_rate(depth_mm: float, test_minutes: float) -> float:
    """Rata de precipitație [mm/min] dintr-o măsurătoare de caserolă."""
    if test_minutes <= 0:
        return 0.0
    return depth_mm / test_minutes


def runtime_simple(target_mm: float, depth_mm: float, test_minutes: float) -> float:
    """Minutele necesare unui circuit fără suprapunere ca să livreze `target_mm`.

    runtime = target / PR = target * test_minutes / depth
    Returnează 0 dacă circuitul nu depune apă (depth <= 0).
    """
    pr = precip_rate(depth_mm, test_minutes)
    if pr <= 0:
        return 0.0
    return target_mm / pr


def runtimes_overlap(
    target_mm: float,
    d_mid_inner: float,
    d_mid_margin: float,
    d_edge_margin: float,
    test_minutes: float,
) -> tuple[float, float]:
    """Timpii (mid, edge) pentru zona cu suprapunere, ca acoperirea să fie uniformă.

    Jumătatea interioară primește apă DOAR de la circuitul `mid`, deci `mid` rulează
    cât să atingă ținta acolo. Pe jumătatea-margine `mid` udă mai slab (depunere sub
    țintă), iar `edge` completează deficitul.

        t_mid  = target / PR_mid_inner
        t_edge = max(0, (target - PR_mid_margin * t_mid) / PR_edge_margin)

    `max(0, …)` e doar o plasă de siguranță pentru valori imposibile.
    """
    t_mid = runtime_simple(target_mm, d_mid_inner, test_minutes)
    t_edge = runtime_edge(target_mm, t_mid, d_mid_margin, d_edge_margin, test_minutes)
    return t_mid, t_edge


def runtime_edge(
    target_mm: float,
    t_primary: float,
    primary_margin_depth: float,
    edge_depth: float,
    test_minutes: float,
) -> float:
    """Minutele unui circuit `edge` ca să completeze deficitul lăsat de primar pe sub-zona lui.

    Pe sub-zona acoperită de acest edge, primarul a depus deja `PR(primary_margin) * t_primary`
    (sub țintă). Edge-ul adaugă restul:

        t_edge = max(0, (target - PR(primary_margin) * t_primary) / PR(edge))

    Returnează 0 dacă edge-ul nu ajunge acolo (`edge_depth <= 0`) sau dacă primarul deja a
    atins/depășit ținta (deficit negativ — plasă de siguranță).
    """
    pr_edge = precip_rate(edge_depth, test_minutes)
    if pr_edge <= 0:
        return 0.0
    deficit = target_mm - precip_rate(primary_margin_depth, test_minutes) * t_primary
    return max(0.0, deficit / pr_edge)


def overlap_delivered(
    t_mid: float,
    t_edge: float,
    d_mid_inner: float,
    d_mid_margin: float,
    d_edge_margin: float,
    test_minutes: float,
) -> tuple[float, float]:
    """Apa livrată [mm] pe (interior, margine) pentru o pereche de timpi — pt. verificare."""
    inner = precip_rate(d_mid_inner, test_minutes) * t_mid
    margin = (
        precip_rate(d_mid_margin, test_minutes) * t_mid
        + precip_rate(d_edge_margin, test_minutes) * t_edge
    )
    return inner, margin


def weekly_avg(temps: Iterable[float | None]) -> float | None:
    """Media temperaturilor, ignorând valorile lipsă. None dacă nu există valori."""
    vals = [float(t) for t in temps if t is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def solve_runtimes(rate_matrix: list[list[float]], target: float | None) -> list[float]:
    """Timpii de rulare [min] per grup, ca fiecare porțiune să primească `target` (mm).

    `rate_matrix` = o listă de rânduri (câte una per porțiune); fiecare rând conține rata de
    precipitație PR (mm/min) a fiecărui grup pe acea porțiune, în aceeași ordine de grupuri
    (0 dacă grupul nu udă porțiunea). Se rezolvă sistemul `A · t = target` în sens
    least-squares, cu constrângerea `t ≥ 0` (un grup nu poate rula timp negativ).

    Generalizează totul:
    - 1 porțiune / 1 grup  → `t = target / PR`;
    - matrice diagonală    → fiecare grup independent;
    - sisteme 2×2          → cazul mijloc/margine (acoperire uniformă).
    """
    n_groups = len(rate_matrix[0]) if rate_matrix and rate_matrix[0] else 0
    if n_groups == 0 or target is None or target <= 0:
        return [0.0] * n_groups

    import numpy as np

    full = np.array(rate_matrix, dtype=float)
    b = np.full(full.shape[0], float(target))
    active = list(range(n_groups))
    result = [0.0] * n_groups

    # Active-set simplu: rezolvă, iar dacă un timp iese negativ scoate grupul și re-rezolvă.
    while active:
        sol, *_ = np.linalg.lstsq(full[:, active], b, rcond=None)
        if np.all(sol >= -1e-9):
            for idx, group in enumerate(active):
                result[group] = max(0.0, float(sol[idx]))
            break
        worst_local = int(np.argmin(sol))
        active.pop(worst_local)

    return result


def coverage(rate_matrix: list[list[float]], runtimes: list[float]) -> list[float]:
    """Apa livrată [mm] pe fiecare porțiune pentru timpii dați (= A · t) — pt. diagnostic."""
    if not rate_matrix or not rate_matrix[0]:
        return []
    import numpy as np

    return (np.array(rate_matrix, dtype=float) @ np.array(runtimes, dtype=float)).tolist()


def split_cycles(runtime_min: float, max_cycle_min: float) -> list[float]:
    """Împarte o durată în reprize egale ≤ max_cycle (cycle & soak).

    Ex.: `split_cycles(30, 12)` → `[10, 10, 10]`. Dacă `max_cycle <= 0` sau durata e mai mică,
    întoarce o singură repriză. Reprizele sunt egale ca să livreze exact `runtime_min` total.
    """
    if runtime_min <= 0:
        return []
    if max_cycle_min <= 0 or runtime_min <= max_cycle_min:
        return [runtime_min]
    import math

    n = math.ceil(runtime_min / max_cycle_min)
    return [runtime_min / n] * n


def interval_from_temp(avg_temp: float | None) -> int:
    """Frecvența (zile între udări) din temperatura medie a zilei — model „rar și mult".

    Praguri (fidel ghidului semintegazon.ro):
    - ≥ 25 °C  → 3 zile (≈ 2×/săptămână, vârf de vară);
    - 10–25 °C → 7 zile (1×/săptămână);
    - < 10 °C  → 14 zile (după necesități, sezon rece).
    `None` → 7 (presupunere prudentă de sezon moderat).
    """
    if avg_temp is None:
        return 7
    if avg_temp >= 25:
        return 3
    if avg_temp >= 10:
        return 7
    return 14


def weighted_precipitation(entries: Iterable[tuple]) -> float:
    """Suma precipitațiilor prevăzute (mm), ponderate cu probabilitatea.

    `entries` = iterabil de tupluri `(precipitation_mm, probability_pct)`. O probabilitate
    `None` e tratată ca 100%. Valorile lipsă / negative sunt ignorate.
    Ex.: (10 mm, 50%) contribuie cu 5 mm.
    """
    total = 0.0
    for precip, prob in entries:
        if precip is None:
            continue
        try:
            p = float(precip)
        except (TypeError, ValueError):
            continue
        if p <= 0:
            continue
        weight = 1.0 if prob is None else max(0.0, min(1.0, float(prob) / 100.0))
        total += p * weight
    return total


def effective_target(target_mm: float | None, rain_mm: float) -> float | None:
    """Ținta rămasă de udat după scăderea ploii prevăzute (1 mm ploaie = 1 L/m²)."""
    if target_mm is None:
        return None
    return max(0.0, target_mm - max(0.0, rain_mm))


def effective_after_rain(
    gross_mm: float | None,
    fallen_mm: float,
    forecast_mm: float,
    forecast_weight_pct: float,
) -> float | None:
    """Ținta rămasă (L/m²) după ploaia CĂZUTĂ + o parte din cea PROGNOZATĂ.

    Ploaia căzută (reală) se scade întreagă. Prognoza poate anula cel mult `p%` din
    necesarul rămas după ploaia căzută — deci sub 100% prognoza REDUCE dar nu poate
    anula complet o udare (rămâne mereu ceva de udat dacă solul real n-a primit ținta).

    - p = 100 → `max(0, gross − fallen − forecast)` (comportamentul clasic, prognoza
      poate anula complet).
    - 0 ≤ p < 100 → prognoza tăie cel mult `deficit·p/100` → udare minimă garantată.
    - p = 0 → prognoza ignorată complet (doar ploaia căzută contează).
    """
    if gross_mm is None:
        return None
    deficit = gross_mm - max(0.0, fallen_mm)
    if deficit <= 0:
        return 0.0  # ploaia căzută singură a acoperit ținta
    p = min(100.0, max(0.0, forecast_weight_pct)) / 100.0
    cap = deficit * p
    deficit -= min(max(0.0, forecast_mm), cap)
    return max(0.0, deficit)


def target_mm(
    avg_temp: float | None,
    factor: float = 1.0,
    min_mm: float = 0.0,
    max_mm: float | None = None,
) -> float | None:
    """Ținta sesiunii (L/m² = mm) din media temperaturii: target = avg_temp * factor.

    Cu `factor=1.0`, media 25°C → 25 L/m². `min_mm`/`max_mm` limitează rezultatul.
    """
    if avg_temp is None:
        return None
    q = avg_temp * factor
    if q < min_mm:
        q = min_mm
    if max_mm is not None and q > max_mm:
        q = max_mm
    return q
