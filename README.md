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

## Model: zone → porțiuni + grupuri

Un singur mod de gândire, valabil pentru orice grădină:

- **Zonă** = o parte a grădinii, împărțită în una sau mai multe **porțiuni** (sub-zone care
  trebuie să primească aceeași țintă `Q`). De obicei o singură porțiune („Toată zona"); uneori
  2–3 (ex. „interior" și „margine").
- **Grup** = una sau mai multe **supape care pornesc deodată** și pe care le-ai măsurat
  împreună la testul cu caserole. Pentru fiecare grup dai **rata (mm/test) pe fiecare porțiune**
  (0 dacă nu ajunge acolo).
- **Grupurile rulează secvențial** (pentru presiune constantă); **supapele dintr-un grup rulează
  simultan**. ZoneFlow calculează cât rulează fiecare grup astfel încât **fiecare porțiune** să
  primească ținta (mic sistem liniar, rezolvat automat).

Acoperă orice configurație:
- **Față** (2 supape care stropesc tot dreptunghiul, pornite deodată, testate împreună):
  1 porțiune + **1 grup** cu ambele supape și o rată → grupul rulează cât să dea ținta.
- **Spate** (mijloc + margine): 2 porțiuni („interior", „margine") + 2 grupuri (mijloc; margine)
  → acoperire uniformă, rulate pe rând.
- **Circuite separate**: câte un grup (și o porțiune) fiecare.

Formulele trăiesc în [`calc.py`](custom_components/zoneflow/calc.py) (modul pur, testat).

## Instalare

1. Copiază `custom_components/zoneflow/` în `config/custom_components/` (sau via HACS).
2. Repornește Home Assistant.
3. **Setări → Dispozitive și servicii → Adaugă integrare → „ZoneFlow"** și alege entitatea
   *weather*, durata testului (implicit 10 min) și câte zile de prognoză mediezi (implicit 7).
4. Configurează zonele din **panoul „ZoneFlow"** apărut în bara laterală (vezi mai jos).

## Panoul ZoneFlow (bara laterală)

După instalare apare o pagină proprie **ZoneFlow** în meniul din stânga, cu tab-uri:

- **Stare** — media temperaturii, ținta, ploaia prevăzută, următoarea udare, durata fiecărui
  grup, plus butoane **Udă acum / Oprește**.
- **Zone** — editorul: adaugi zone, fiecare cu **porțiuni** (nume + m²) și **grupuri** (nume,
  **supapele** care pornesc deodată, **rata (mm)** pe fiecare porțiune). Adaugă/șterge inline,
  apoi **Salvează zonele**.
- **Setări** — weather, durata test, zile prognoză, ora, **intervalul între udări**, factor, compensare ploaie.
- **Ajutor** — explicații pentru porțiune / grup / rată / testul cu caserole.

Exemplu *Față*: o porțiune; un grup cu ambele supape; o rată (cea măsurată cu ambele pornite).
Exemplu *Spate*: două porțiuni (Interior, Margine); grup „Mijloc" cu rată în ambele, grup
„Margine" cu rată doar în Margine.

> Butonul **Configurează** de pe cardul integrării rămâne, dar doar pentru setările generale —
> zonele se editează în panou.

## Ce reglezi din dashboard (entități live)

| Tip | Entități |
| --- | --- |
| `number` | **Factor corecție**, **Interval între udări (zile)** |
| `time` | **Ora de udare** |
| `switch` | **Irigație activă**, **Compensare ploaie** |
| `button` | **Udă acum**, **Oprește udarea** |
| `binary_sensor` | **Udare în curs** |
| `sensor` | media temperaturii, ținta (L/m²), **ploaie prevăzută 24h**, **țintă efectivă (după ploaie)**, **durata fiecărui grup** (generat dinamic), apă pe sesiune (L), următoarea udare |

Porțiunile (m²) și ratele caserolelor se setează în **Configurează** (nu din dashboard).

## Compensarea ploii

Dacă se anunță ploaie, integrarea o **scade din țintă** (1 mm ploaie = 1 L/m²). Folosește
prognoza **orară** a entității weather pe **următoarele 24h**, ponderând cantitatea cu
probabilitatea (ex. 10 mm la 50% = 5 mm luați în calcul). Țintă efectivă = `țintă − ploaie`.
Dacă ploaia prevăzută ≥ țintă, sesiunea se **sare** complet (toate duratele devin 0).

Comutatorul **Compensare ploaie** o poate dezactiva (atunci se udă mereu la ținta din
temperatură). Vezi `sensor` „Ploaie prevăzută (24h)" și „Țintă efectivă (după ploaie)".
Se folosește doar prognoza (ploaia deja căzută nu e scăzută).

## Cum funcționează udarea

La **ora** setată, dacă au trecut cel puțin **intervalul** (zile) de la ultima udare reală și
**Irigație activă** e pornit, integrarea recalculează timpii din ținta curentă și parcurge
**grupurile secvențial**, zonă cu zonă. Punctul de start e momentul activării; dacă o sesiune
se sare din ploaie, intervalul se numără de la următoarea udare efectivă.
La fiecare grup pornește **toate supapele lui simultan**, așteaptă durata calculată, apoi le
oprește și trece la grupul următor. Butonul **Oprește udarea** (sau dezactivarea) anulează
ciclul și închide toate supapele. La pornirea HA, toate supapele sunt închise preventiv.

Servicii disponibile: `zoneflow.run_now`, `zoneflow.stop`.

## Teste

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pytest
pytest custom_components/zoneflow/tests/test_calc.py -q
```

## Presupuneri

- Un singur program global (aceeași oră/interval pentru toate zonele).
- Grupurile rulează secvențial; doar supapele din același grup pornesc simultan.
- „Săptămâna în curs" ≈ media prognozei pe următoarele N zile (configurabil).
- Acoperirea uniformă se rezolvă în sens least-squares; la configurații imposibile (o porțiune
  pe care n-o atinge niciun grup) rezultatul e aproximativ — vezi durata fiecărui grup.
