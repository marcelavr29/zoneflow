# ZoneFlow (custom_components/zoneflow)

Integrare Home Assistant care calculează automat cât și cât timp udă fiecare circuit,
pornind de la **media temperaturii săptămânale** și de la **testul cu caserole** (rata de
precipitație măsurată pe teren).

## Idee de bază

- Faci testul cu caserole: pui caserole pe gazon, pornești un circuit ~10 minute și măsori
  **adâncimea apei** adunate (mm). `1 mm = 1 L/m²`.
- Ținta de apă a fiecărei udări = **media temperaturii** săptămânii: media 25 °C → 25 L/m².
  (Sursa temperaturii e o integrare *weather* prin prognoză; poți scala cu un *factor*.)
- Timpul de rulare = `țintă / rată_precipitație`.

## Cele 2 zone × 2 circuite

- **Zona A** – două circuite normale, fără suprapunere. Fiecare rulează cât să livreze ținta
  pe suprafața lui.
- **Zona B** – circuit **mijloc** + circuit **margine** care se suprapun pe jumătatea de la
  margine:
  - jumătatea **interioară** primește apă **doar** din *mijloc* → *mijloc* rulează cât să
    atingă ținta acolo;
  - pe **margine**, *mijloc* udă mai slab (sub țintă), așa că *margine* **completează
    deficitul** ca toată zona să primească aceeași cantitate.

  De aceea testul cu caserole pentru zona B se face **pe poziții**: *mijloc-interior*,
  *mijloc-margine* și *margine*.

Formulele trăiesc în [`calc.py`](custom_components/zoneflow/calc.py) (modul pur, testat).

## Instalare

1. Copiază `custom_components/zoneflow/` în `config/custom_components/` din instanța ta HA.
2. Repornește Home Assistant.
3. **Setări → Dispozitive și servicii → Adaugă integrare → „ZoneFlow"**.
4. Completează:
   - entitatea *weather*, durata testului cu caserole (implicit 10 min), câte zile de
     prognoză mediezi (implicit 7);
   - switch-urile pentru cele 2 circuite ale **zonei A**;
   - switch-urile pentru **mijloc** și **margine** ale **zonei B**.

## Ce reglezi din interfață (entități create de integrare)

| Tip | Entități |
| --- | --- |
| `number` | suprafață (m²) × 4 circuite; caserole (mm) pentru A1, A2; caserole pe poziții pentru zona B (mijloc-interior, mijloc-margine, margine); factor de corecție |
| `time` | **Ora de udare** |
| `switch` | **Irigație activă** + câte un comutator pentru fiecare zi (Luni…Duminică) |
| `button` | **Udă acum**, **Oprește udarea** |
| `binary_sensor` | **Udare în curs** |
| `sensor` | media temperaturii, ținta (L/m²), durata fiecărui circuit, apă pe sesiune (L), următoarea udare |

Toate valorile reglabile sunt **persistente** (supraviețuiesc restartului).

## Cum funcționează udarea

La **ora** setată, în **zilele** bifate, dacă **Irigație activă** e pornit, integrarea
recalculează timpii din ținta curentă și pornește circuitele **secvențial**
(`mijloc` și `margine` ale zonei B se string corect, pentru presiune constantă).
Butonul **Oprește udarea** (sau dezactivarea) anulează ciclul și închide toate supapele.
La pornirea HA, toate supapele sunt închise preventiv.

Servicii disponibile: `zoneflow.run_now`, `zoneflow.stop`.

## Teste

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pytest
pytest custom_components/zoneflow/tests/test_calc.py -q
```

## Presupuneri (v1)

- Un singur program global (aceeași oră/zile pentru ambele zone).
- Zona A: circuitele nu se suprapun.
- „Săptămâna în curs" ≈ media prognozei pe următoarele N zile (configurabil).
- Fără *rain-skip* / senzor de ploaie (posibilă extindere).
