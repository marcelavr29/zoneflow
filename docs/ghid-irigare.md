# Ghid de irigare a gazonului — referință ZoneFlow

Rezumat al recomandărilor după care e ghidat ZoneFlow. Sursă: **semintegazon.ro/sfaturi-tehnice**.
Principiul director: **udare rară și abundentă** (rădăcini adânci, gazon rezistent).

## Cifre cheie

| Aspect | Recomandare |
| --- | --- |
| **Cantitate / udare** | **15-20 L/m²** (echivalentul unei ploi abundente). ZoneFlow default **15**. |
| **Adâncime umezire** | **15-20 cm** în sol (rezervă de apă pentru 3-4, chiar 7 zile pe caniculă). |
| **Frecvență** | **Max 2×/săptămână** vara; ~**la 3-4 zile**; doar când suprafața s-a uscat bine. |
| **Infiltrare sol** | **~20-25 L/m² pe oră** (sol mediu-greu). Peste → băltire/scurgere → folosește **cycle & soak**. |
| **Ora** | Cât mai aproape de răsărit (**3-6 AM**) la sisteme fixe; manual: după-amiază, cu 2-3 ore înainte de apus. |
| **Uniformitate** | Se reglează **din aspersoare** (cursă, jet, duză), nu din software. |

## Frecvența după temperatura medie a zilei (infografic)

| Temperatura medie | Frecvență | Interval ZoneFlow (auto) |
| --- | --- | --- |
| **≥ 25 °C** (vârf de vară) | 2×/săptămână | **3 zile** |
| **10-25 °C** (primăvară/toamnă) | 1×/săptămână | **7 zile** |
| **< 10 °C** (rece) | după necesități | **14 zile** |

`O irigare = 15 L/m².` Setezi frecvența astfel încât solul să fie **bine uscat la suprafață**
înainte de următoarea udare.

## Testul cu caserole (cum afli durata)

1. Pui **3-4 caserole la 100 m²** (ideal caserole cu pereți drepți).
2. Pornești sistemul **10 minute** și măsori mm adunați (media caserolelor).
3. `20 mm într-o caserolă = 20 L/m²`. Durata necesară = **țintă / rată**
   (ex. țintă 15 L/m², rată 9 mm/10 min → 15 / (9/10) ≈ **16,7 min**).

## Cum aplică ZoneFlow aceste reguli

- **Cantitate fixă** (Țintă L/m², default 15) — **nu** din temperatură.
- **Frecvența** vine din temperatură (tabelul de mai sus), cu opțiune de interval manual.
- **Durata per grup** = țintă_zonă / rata măsurată (metoda caserolei).
- **Factor per zonă** (%) pentru zone umbrite/care cer mai puțin (ex. 70%).
- **Cycle & soak** împarte udarea în reprize cu pauze, ca să intre 15 L/m² fără băltire.
- **Compensare ploaie**: scade ploaia prevăzută (24h) din țintă.

## Linkuri sursă
- Irigarea corectă: https://www.semintegazon.ro/sfaturi-tehnice/cum-irigam-corect-gazonul
- Testul cu caserole: https://www.semintegazon.ro/sfaturi-tehnice/cate-minute-irigam-gazonul
- Index sfaturi: https://www.semintegazon.ro/sfaturi-tehnice
