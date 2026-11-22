# ADR 003: Einführung des FrameContext (Seiden-Muster) im Labor

**Datum:** 22.11.2026
**Status:** Akzeptiert & Implementiert
**Architektur-Pattern:** Model-View-Controller (MVC) Trennung & Single Source of Truth

## 1. Kontext & Problem
Die `LaborApp` hat historisch gewachsen sowohl die Steuerung (Controller) als auch die Datenhaltung (Model) übernommen. Bilder, Diffs und Masken wurden als lose Variablen (z. B. `last_live_img`, `last_raw_diff`) im GUI-Objekt gespeichert.
Mit der Einführung komplexer Features wie der **Verschiebungskorrektur** und dem **Lazy-Time-Travel Cache** führte dies zu "State Leakage": Der Renderer griff auf Variablen zu, die je nach Ausführungspfad (Vorwärtsspulen vs. Rückwärts-Zeitsprung) asynchron, unvollständig oder nicht korrekt linsenverschoben waren.

## 2. Entscheidung
Einführung des **"Seiden-Musters" (Strikte Kapselung in Daten-Pakete)**:
- **`FrameContext` (Dataclass):** Ein striktes, in sich geschlossenes Paket, das den exakten Zustand eines Frames zum Zeitpunkt X einfriert (Rohbild, verschobenes Bild, Masken, Diffs, Schuss-Liste).
- **`LaborContext` (Model):** Eine isolierte Klasse, die als einzige mit der Engine kommuniziert, die Daten aufbereitet, den Time-Travel-Cache pflegt und der GUI fertige `FrameContext`-Pakete übergibt.

## 3. Konsequenzen (Vorteile)
- **Zustandsloser Renderer:** Der `LaborRenderer` wurde von sämtlicher Geschäftslogik befreit. Er greift nur noch auf Eigenschaften des übergebenen `FrameContext` zu.
- **Saubere UI:** Die `LaborApp` hält keine Bild-Zustände mehr. Sie agiert als reiner Controller (Nimmt Klicks entgegen, ruft das Paket vom Model ab, reicht es an den Renderer weiter).
- **Sicherer Time-Travel:** Beim Zeitsprung in der Historie wird lediglich das komplett verschnürte Paket aus dem Cache geladen. Das manuelle, fehleranfällige Nachkonstruieren von alten Zuständen in der GUI entfällt.

## 4. Lessons Learned & Architektur-Stolperfallen
Bei zukünftigen Erweiterungen der Render-Ansichten oder des Caches ist zwingend auf Folgendes zu achten:

* **Stolperfalle 1: Lazy-Loading von rechenintensiven Layern (Modus 4)**
  Die Raw-Diff-Ansicht erfordert unberührte Rohbilder und ist extrem rechenintensiv. Die Werte (`raw_diff`, `thresh_raw`) werden daher beim *Fast-Forward* (dem schnellen, unsichtbaren Vorspulen mehrerer Frames) aus Performance-Gründen im Paket mit `None` initialisiert. 
  **Wichtig:** Beim Rückwärts-Springen (Laden aus dem Cache) auf einen solchen übersprungenen Frame müssen diese Werte *lazy* (nachträglich) berechnet und in das `FrameContext`-Paket injiziert werden, bevor sie an den Renderer gehen.

* **Stolperfalle 2: Das History-Masken Paradoxon**
  Die Maske der *vorherigen* Schüsse (`history_mask`) muss zwingend gesichert werden, **bevor** die Engine aufgerufen wird. Wird sie danach gesichert, beinhaltet sie bereits den aktuellen Treffer. Zieht der Renderer diese Maske dann vom Raw-Diff ab, löscht er den gerade gemachten Treffer aus der Anzeige.

* **Stolperfalle 3: Originalbilder mitführen**
  Modi wie die Roh-Ansicht (Modus 5) verlangen das unverschobene Originalbild, um die Arbeit der Verschiebungskorrektur sichtbar zu machen. Das `FrameContext`-Paket muss daher stets das absolute Rohbild (`orig_img`) neben dem verarbeiteten UI-Bild (`live_img`) mitführen.