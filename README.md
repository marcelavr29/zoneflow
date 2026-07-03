# ZoneFlow (custom_components/zoneflow)

Integrare Home Assistant pentru irigație, pe principiul **„rar și mult"** (vezi
[ghidul de irigare](docs/ghid-irigare.md)): cantitate fixă pe udare, frecvență după temperatură.

## Idee de bază

- **Cantitate fixă**: ~**15 L/m² pe udare** (setabilă), ca o ploaie abundentă → udă adânc 15-20 cm.
  **Nu** se calculează din temperatură.
- **Frecvența** vine din **temperatura medie** (interval automat): ≥25°C → la 3 zile (2×/săpt);
  10-25°C → la 7 zile (1×/săpt); <10°C → la 14 zile. (Sau interval manual.)
- **Durata pe circuit** = `țintă / rată`, unde rata vine din **testul cu caserole** (rulezi
  ~10 min, măsori mm). `1 mm = 1 L/m²`.
- **Cycle & soak** împarte udarea în reprize cu pauze, ca să intre fără băltire (global în
  Setări; opțional suprascris **per zonă** — gol = global, `0` = dezactivat pentru zona aia).

## Model: zone → grupuri

- **Zonă** = o parte a grădinii, cu **suprafață (m²)** și un **factor (%)** opțional
  (ex. front umbrit 70% → mai puțină apă). Opțional, o zonă poate avea propriile valori de
  **cycle & soak** (gol = folosește globalul din Setări; `0` = fără reprize în zona aia).
- **Grup** = una sau mai multe **supape care pornesc deodată** (măsurate împreună la testul cu
  caserole), cu o singură **rată (mm/test)**. Un circuit care pornește singur = grup cu o supapă.
- **Grupurile rulează secvențial** (presiune constantă); **supapele dintr-un grup, simultan**.
  Durata fiecărui grup = `țintă_zonă / rata lui` (metoda caserolei). Uniformitatea se reglează
  din aspersoare, nu din software.

Exemple:
- **Față** (2 supape care stropesc tot, pornite deodată): 1 grup cu ambele supape + o rată.
- **Spate** (mijloc + margine): 2 grupuri separate; fiecare rulează după rata lui (ambele udă).

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
- **Zone** — editorul: adaugi zone (nume + **m²** + **factor %**) și **grupuri** (nume,
  **supapele** care pornesc deodată, o **rată (mm)**). Adaugă/șterge inline, apoi **Salvează zonele**.
- **Setări** — weather, durata test, zile prognoză, **Țintă (L/m²)**, ajustare globală, ora,
  **interval automat/manual**, compensare ploaie, **cycle & soak** (minute max/ciclu + pauză).
- **Ajutor** — principiul „rar și mult", grup / rată / testul cu caserole, pragurile de interval.
- **Rapoarte** — apă azi/7z/30z, nr. udări, sesiuni sărite, defalcare pe zonă și istoricul sesiunilor.

În timpul udării, tab-ul **Stare** arată live: zona/grupul curent, **cât mai rămâne** (cronometru),
faza (udare/soak + repriza) și ce urmează. Tot de aici: **Sări următoarea udare** și, în editorul
de **Zone**, un buton **Test** (rulează o zonă N minute, să verifici aspersoarele).

Exemplu *Față*: un grup cu ambele supape + o rată; zonă cu factor 70% dacă e umbrită.
Exemplu *Spate*: două grupuri (C1, C2), fiecare rulează după rata lui.

> Butonul **Configurează** de pe cardul integrării rămâne, dar doar pentru setările generale —
> zonele se editează în panou.

## Ce reglezi din dashboard (entități live)

| Tip | Entități |
| --- | --- |
| `number` | **Țintă apă (L/m²)**, **Ajustare globală**, **Interval manual**, **Minute max/ciclu**, **Pauză infiltrare** |
| `time` | **Ora de udare** |
| `switch` | **Irigație activă**, **Compensare ploaie**, **Interval automat**, **Notificări** |
| `button` | **Udă acum**, **Oprește udarea**, **Udă la următoarea oră**, **Sări următoarea udare** |
| `binary_sensor` | **Udare în curs** |
| `sensor` | media temperaturii, ținta, ploaie 24h, țintă după ploaie, durata fiecărui grup, apă pe sesiune, ultima/următoarea udare, **Apă total** (`total_increasing` → grafice native HA), **Udări sărite**, **Durata ultimei udări** |

Suprafața/factorul zonei și ratele se setează în panou → **Zone** (nu din dashboard).

## Furnizor de prognoză

ZoneFlow nu integrează direct un furnizor — consumă o entitate **`weather.*`** aleasă în Setări.
Recomandat **Met.no** (built-in în HA, fără cheie, oferă prognoză `daily` + `hourly` cu
precipitații). Adaugi integrarea Met.no, apoi o alegi în panou → Setări. Dacă „Media temperaturii"
rămâne goală, entitatea aleasă nu oferă prognoză cu temperatură; butonul **Reîmprospătează** din
tab-ul Stare forțează re-interogarea prognozei.

## Compensarea ploii

Ploaia luată în calcul are două componente (1 mm ploaie = 1 L/m²):

- **Prognoza pe 24h** (orară, ponderată cu probabilitatea — ex. 10 mm la 50% = 5 mm).
- **Registrul ploii căzute**: în fiecare oră, ZoneFlow notează precipitația estimată pentru ora
  curentă (nowcast) — sau valoarea reală, dacă ai configurat un **senzor de ploaie** în Setări.
  Ploaia căzută în ultimele **48h** (de la ultima udare) se scade și ea din țintă.

Țintă efectivă = `țintă − prognoză − ploaie căzută`. Dacă totalul ≥ țintă, sesiunea se **sare**;
iar dacă **ploaia căzută singură** atinge ținta, ea **contează ca o udare completă** (următoarea
sesiune se mută cu un interval întreg — nu se mai udă a doua zi peste solul ud).

Comutatorul **Compensare ploaie** dezactivează tot mecanismul. Vezi în panou „Ploaie prevăzută
(24h)" și „Ploaie căzută (48h)".

## Cum funcționează udarea

La **ora** setată, dacă au trecut cel puțin **intervalul** de la ultima udare reală și
**Irigație activă** e pornit, integrarea recalculează timpii și parcurge **grupurile secvențial**.
Intervalul vine din temperatură (automat) sau e fix (manual). Dacă o sesiune se sare din ploaie,
intervalul se numără de la următoarea udare efectivă.
La fiecare grup pornește **toate supapele lui simultan** pe durata calculată (eventual în reprize
**cycle & soak** cu pauze de infiltrare), apoi le oprește și trece la grupul următor. Butonul **Oprește udarea** (sau dezactivarea) anulează
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
- Cantitate fixă pe udare; **temperatura decide frecvența**, nu cantitatea (cf. [ghid](docs/ghid-irigare.md)).
- Uniformitatea în zonă se reglează **din aspersoare**, nu din software (fiecare grup udă după rata lui;
  zonele cu suprapunere primesc ceva mai mult — acceptabil pentru „rar și mult").
