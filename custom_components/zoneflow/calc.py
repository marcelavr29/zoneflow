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
    pr_mid_inner = precip_rate(d_mid_inner, test_minutes)
    pr_mid_margin = precip_rate(d_mid_margin, test_minutes)
    pr_edge_margin = precip_rate(d_edge_margin, test_minutes)

    t_mid = target_mm / pr_mid_inner if pr_mid_inner > 0 else 0.0

    if pr_edge_margin > 0:
        deficit = target_mm - pr_mid_margin * t_mid
        t_edge = max(0.0, deficit / pr_edge_margin)
    else:
        t_edge = 0.0

    return t_mid, t_edge


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
