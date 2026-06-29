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

## Zone și circuite (configurabile)

Topologia e **dinamică**: definești **oricâte zone**, fiecare cu **oricâte circuite**. Fiecare
zonă are un **mod**:

- **Independentă** – fiecare circuit udă propria suprafață. Rulează cât să livreze ținta:
  `runtime = țintă / rată_precipitație`.
- **Suprapusă** – un circuit **primar** acoperă toată zona, plus **oricâte circuite „margine"**
  care completează sub-zone unde primarul udă insuficient:
  - zona **interioară** primește apă **doar** din primar → primarul rulează cât să atingă ținta
    acolo (`depth_inner`);
  - pe **margine**, primarul udă mai slab (`depth_margin`, sub țintă), iar fiecare circuit
    margine **completează deficitul** ca toată zona să primească aceeași cantitate.

  De aceea pentru o zonă suprapusă măsori caserolele **pe poziții**: primar-interior,
  primar-margine și fiecare margine pe sub-zona ei.

Cazul „mijloc + margine" e exact o zonă suprapusă cu **un singur** circuit margine.

Formulele trăiesc în [`calc.py`](custom_components/zoneflow/calc.py) (modul pur, testat).

## Instalare

1. Copiază `custom_components/zoneflow/` în `config/custom_components/` (sau via HACS).
2. Repornește Home Assistant.
3. **Setări → Dispozitive și servicii → Adaugă integrare → „ZoneFlow"** și alege entitatea
   *weather*, durata testului (implicit 10 min) și câte zile de prognoză mediezi (implicit 7).
4. Pe cardul integrării apasă **Configurează** și adaugă zonele și circuitele (vezi mai jos).

## Configurarea zonelor (butonul „Configurează")

Meniu cu: **Setări generale**, **Adaugă zonă**, **Editează / șterge zonă**, **Salvează și ieși**.
La fiecare zonă: redenumire/mod, **Adaugă circuit**, **Editează / șterge circuit**.
Pentru fiecare circuit introduci: nume, **switch** (supapa), **suprafață (m²)**, **rolul**
(la zone suprapuse: primar/margine) și **valorile caserolelor (mm)** corespunzătoare rolului.
Modificările se salvează la „Salvează și ieși", iar integrarea se reîncarcă și recalculează.

## Ce reglezi din dashboard (entități live)

| Tip | Entități |
| --- | --- |
| `number` | **Factor corecție** (scalează ținta) |
| `time` | **Ora de udare** |
| `switch` | **Irigație activă** + câte un comutator pentru fiecare zi (Luni…Duminică) |
| `button` | **Udă acum**, **Oprește udarea** |
| `binary_sensor` | **Udare în curs** |
| `sensor` | media temperaturii, ținta (L/m²), **durata fiecărui circuit** (generat dinamic), apă pe sesiune (L), următoarea udare |

Suprafețele și valorile caserolelor se setează în **Configurează** (nu din dashboard).

## Cum funcționează udarea

La **ora** setată, în **zilele** bifate, dacă **Irigație activă** e pornit, integrarea
recalculează timpii din ținta curentă și pornește circuitele **secvențial**, zonă cu zonă
(în fiecare zonă suprapusă primarul rulează înaintea circuitelor margine), pentru presiune
constantă. Butonul **Oprește udarea** (sau dezactivarea) anulează ciclul și închide toate
supapele. La pornirea HA, toate supapele sunt închise preventiv.

Servicii disponibile: `zoneflow.run_now`, `zoneflow.stop`.

## Teste

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pytest
pytest custom_components/zoneflow/tests/test_calc.py -q
```

## Presupuneri

- Un singur program global (aceeași oră/zile pentru toate zonele).
- Într-o zonă suprapusă, rata primarului pe margine (`depth_margin`) e considerată aceeași
  pentru toate circuitele margine (suficient pentru cazul real; per-margine se poate adăuga).
- „Săptămâna în curs" ≈ media prognozei pe următoarele N zile (configurabil).
- Fără *rain-skip* / senzor de ploaie (posibilă extindere).
