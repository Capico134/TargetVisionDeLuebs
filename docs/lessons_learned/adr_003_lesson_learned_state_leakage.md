# Lesson Learned: State Leakage & Separation of Concerns im Labor

**Datum:** 21.11.2026
**Status:** Analysiert & Dokumentiert
**Thema:** Architektur-Schulden durch parallele Bildverwaltung im Labor (Verschiebungskorrektur & Cache)

## 1. Ausgangssituation
Mit der Einführung der **Verschiebungskorrektur (Image Alignment)** und des **Lazy Timeline Caches** im Labor kam es zu schwer aufspürbaren Bugs bei der visuellen Darstellung (z.B. falsche Diffs in Ansicht 4, fehlende History-Masken beim Rückwärts-Springen). Um diese Fehler zu beheben, mussten im Labor-Code manuell Variablen wie `clean_live_img` nachverschoben oder `history_mask` aus dem Cache rekonstruiert werden.

## 2. Das Problem (Warum es sich "holprig" anfühlte)
Das ELA-Prinzip (Einfach, Lesbar, Allgemein) wurde hier schleichend verletzt, weil die Grenzen zwischen der Engine (`DetectionDeLuebs`) und der UI (`LaborDeLuebs`) verwischt sind:

1. **Wissen, das am falschen Ort liegt:** Das Labor (die UI) musste plötzlich wissen, *dass* die Engine Bilder verschiebt und *wie* sie das tut. Das Labor musste aktiv `detector._shift_image_exact(clean_live_img, dx, dy)` aufrufen. Die UI hat also Aufgaben der Bildverarbeitung übernommen.
2. **Parallele Wahrheiten:** Die Engine verarbeitet rohe Bilder, aber das Labor pflegte parallel eigene Bild-Kopien (`live_img`, `clean_live_img`), um sie später dem Renderer zu übergeben. Wenn die Engine das Bild dreht oder schiebt, weiß die parallele Kopie im Labor nichts davon.
3. **Cache-Mocking:** Der Lazy Time-Travel Cache speicherte nicht das offizielle Endergebnis der Engine, sondern musste mühsam Einzelteile (`mask`, `shots`, `shift`) puffern und die Engine-Logik beim Zurückspringen nachbauen (z.B. *„Wenn ich zurückspringe, muss ich mir die Maske vom vorherigen Frame holen“*).

## 3. Die ELA-Analyse
Wenn Zahnräder wie Seide ineinandergreifen sollen, darf ein Zahnrad (Labor) nicht in das Getriebegehäuse des anderen (Engine) greifen.
* **Einfach:** Das Labor sollte nur ein Bild in die Blackbox (Engine) werfen und ein fertiges Paket zurückbekommen.
* **Lesbar:** Keine manuellen Nachkorrekturen (`if i == target_idx: shift...`) im GUI-Code.
* **Allgemein:** Die Engine sollte gar nicht wissen, ob sie vom Live-System oder vom Labor aufgerufen wird. Beide Konsumenten sollten exakt denselben Output verarbeiten.

## 4. Lessons Learned für die Zukunft (Das "Seiden"-Muster)
Um solche Schlaglöcher bei zukünftigen Erweiterungen (z.B. Perspektivkorrektur, Soft-Templates) zu vermeiden, müssen wir in Zukunft auf das **"Frame Result Pattern" (Daten-Pakete)** setzen:

Anstatt dass die Engine nur `True/False` zurückgibt und das Labor sich die Diffs über den `DateiManager` (`d_dm.debug_images`) zusammensucht, sollte die Engine ein standardisiertes Container-Objekt zurückliefern:

```python
# Zukünftiges ELA-Idealbild:
result = detector.process_frame(raw_image, side)

# result enthält ALLES, was die UI oder der Cache jemals brauchen könnte:
# result.shifted_raw_image
# result.clean_diff_image
# result.history_mask
# result.found_shots
```

**Konsequenz für den Cache:**
Der Lazy Cache speichert dann einfach nur dieses *eine* `result`-Objekt. Wenn der Nutzer zurückspringt, holt das Labor einfach `result = cache[index]` und gibt `result.history_mask` an den Renderer. Das Labor muss nie wieder wissen, woher die Maske kommt oder ob das Bild verschoben wurde.

**Fazit:** Der aktuelle Fix funktioniert technisch einwandfrei, ist aber architektonisch ein "Patch". Für den anstehenden 50m-Praxistest frieren wir dieses funktionierende System exakt so ein (Golden Master). Bei künftigen großen Refactorings wissen wir nun, dass wir die Schnittstelle zwischen Engine und Labor durch strikte Daten-Pakete (`FrameResults`) entkoppeln müssen.