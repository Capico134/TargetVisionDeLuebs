# 🎯 TargetVision DeLübs
Das intelligente Computer-Vision-System zur Treffererkennung für laufende und stehende Schießscheiben[cite: 7].

*TargetVision DeLübs* reiht sich in die DeLübs-Softwarefamilie ein und entstand als Vater-Sohn-Projekt, um normale Webcams in ein hochpräzises Trefferanalyse-System zu verwandeln[cite: 7]. Es überwindet die typischen Probleme von Kamerasystemen auf dem Schießstand (Schattenwurf, mechanisches Wackeln der Anlage) durch eine clevere Bildverarbeitungs-Logik[cite: 7].

## 📺 Media & Story
Folge dem Projekt auf YouTube, um über neue Funktionen informiert zu werden[cite: 7]. Hinterlasst auch gerne einen Kommentar in den Videos oder auf der Homepage[cite: 7]!
* 🎥 **YouTube-Shorts:** [https://www.youtube.com/@DeLuebs][cite: 7]
* ℹ️ **Homepage:** [https://DeLuebs.de/][cite: 7]

## 🏆 Training & Wettkampf
Neben der reinen Erkennung bietet das System Features für den echten Schießstand-Alltag:
* **Präzise Ringwertung:** Das System erkennt nicht nur das Loch, sondern berechnet auf Wunsch die exakte Ringwertung (inklusive 10.9 Zehntelwertung).
* **Flexible Zielscheiben-Typen:** Egal ob Luftgewehr oder Luftpistole – über die Konfiguration lassen sich verschiedene Zielscheiben-Profile mit exakten physikalischen Ring-Maßen (in mm) hinterlegen und jederzeit wechseln.
* **Zwei-Spieler-Modus:** Durch den Dual-Kamera Support (links und rechts) können zwei Schützen im direkten Duell gegeneinander antreten[cite: 7].
* **Highscore-System:** Die besten Ergebnisse und Serien werden gespeichert und sorgen für langanhaltende Motivation im Training.

## 🔬 High-Precision Engine
In diesem System stecken Algorithmen, die speziell für den rauen und optisch schwierigen Schießstand-Alltag entwickelt wurden[cite: 7]:
* **Akkumuliertes Schuss-Gedächtnis:** Zuvor geschossene Löcher werden in einer kontinuierlichen Maske gespeichert und mathematisch subtrahiert[cite: 7]. Alte Treffer stören die neue Erkennung somit nicht[cite: 7].
* **Farb-Differenz-Trick zur Trefferanalyse:** Die Differenz zwischen Referenz und Live-Bild wird hochpräzise in voller Farbe (RGB) berechnet, *bevor* sie in geglättete Graustufen umgewandelt wird[cite: 7]. So werden selbst neue Treffer zuverlässig erkannt, bei denen die rote Wand exakt dieselbe Helligkeit aufweist wie die braune Zielscheibe[cite: 7]!
* **Smart-Hybrid Zielerfassung:** Das System entscheidet pro Treffer dynamisch über den besten Erkennungs-Algorithmus[cite: 7]. Bei stark ausgefransten Löchern schaltet die Engine vollautomatisch auf einen komplexen Hough-Kreisbogen-Algorithmus um[cite: 7]. Ein innovatives Kombi-Ranking gleicht die gefundenen Kreise anschließend mit dem realen Riss ab, um Geistertreffer auszuschließen.
* **Anti-Verschiebungs-Filter (Aspect-Ratio):** Mechanische Ruckler der Zuganlage, die als unnatürlich lange Sicheln im Bild auftauchen, werden durch eine blitzschnelle Analyse des Seitenverhältnisses gnadenlos ignoriert.
* **Umgebungslicht-Normalisierung:** Helligkeitsschwankungen auf der Pappe werden vor der Analyse dynamisch ausgeglichen[cite: 7].
* **Intelligente Pausenerkennung:** Das System prüft den Wand-Hintergrund in allen 3 Farbkanälen[cite: 7]. Fährt die Scheibe weg, pausiert die Engine automatisch – das spart CPU-Ressourcen und verhindert Fehlerkennungen[cite: 7].
* **Selbstheilende Konfiguration:** Ein "Config-Spion" überwacht die Parameter im Hintergrund. Fehlende Werte werden durch sichere Fallbacks ersetzt und lückenlos für die Fehleranalyse protokolliert.
* **Visuelles Aufhübschen:** Für das Auge am Monitor können die Farben des Live-Bildes künstlich gesättigt werden, ohne dass die Algorithmen im Hintergrund beeinflusst werden[cite: 7].

## 🚀 Installation & Start
1. **Repo klonen** oder als ZIP herunterladen[cite: 7].
2. **Abhängigkeiten installieren:** `pip install -r requirements.txt` (enthält z.B. OpenCV und NumPy)[cite: 7].
3. **Konfiguration:** Die mitgelieferte `config.example.ini` beim ersten Start einfach ignorieren – das Programm erstellt automatisch eine frische `config.ini` mit hilfreichen Kommentaren für dein System[cite: 7].
4. **Starten:** Führe `StartTargetVisionDeLuebs.bat` aus oder starte direkt über `python TargetVisionDeLuebs.py`[cite: 7].

### 🎨 Praxistipp: Hintergrund-Farbwerte (RGB) exakt ermitteln
Damit die automatische Pausenerkennung perfekt funktioniert, benötigt das System die RGB-Farbwerte deiner Wand aus der Kamera-Perspektive[cite: 7].

> ⚠️ **Wichtiger Hinweis:** Wenn `darstellung_ohne_weissabgleich = yes` aktiviert ist, weichen die Farben auf dem Monitor vom Analysebild ab[cite: 7]. Screenshots des Hauptfensters liefern daher falsche Werte[cite: 7]!

**Der einfachste Weg zu den exakten Werten:**[cite: 7]
1. **Referenzbild erzeugen:** Lass die Zielscheibe wegfahren, sodass nur die leere Wand zu sehen ist, und klicke im Programm auf den **Reset-Button** der jeweiligen Kamera[cite: 7].
2. **Foto öffnen:** Das System speichert dabei automatisch das rohe Kamerabild im Ordner `debug_bilder/` als `referenz_left.jpg` bzw. `referenz_right.jpg`[cite: 7]. Öffne diese Datei in **Paint** (oder einem anderen Bildbearbeitungsprogramm)[cite: 7].
3. **Farbe abgreifen:** Wähle das **Pipetten-Werkzeug** und klicke mitten auf die Wandfläche[cite: 7].
4. **RGB-Werte ablesen:** Klicke oben auf **"Palette bearbeiten"** (Farben bearbeiten)[cite: 7]. Dort findest du auf der rechten Seite die exakten Werte für **Rot (R)**, **Grün (G)** und **Blau (B)**[cite: 7].
5. **In `config.ini` eintragen:** Übertrage die drei Zahlen in den Abschnitt `[Hintergrund_Links]` bzw. `[Hintergrund_Rechts]`[cite: 7].

## ⚙️ Dateistruktur
* `TargetVisionDeLuebs.py` – Die Haupt-Engine[cite: 7].
* `config.ini` – Wird beim Start generiert[cite: 7]. Hier stellst du Kameras, Crops, Wandfarben (RGB) und Erkennungstoleranzen ein[cite: 7]. *(Wird durch .gitignore nicht auf GitHub hochgeladen)*[cite: 7]
* `zielscheiben.json` – Hier sind die exakten physikalischen Ringmaße der unterschiedlichen Scheibentypen hinterlegt.
* `debug_bilder/` – Ein automatischer Ordner für die Fehleranalyse[cite: 7]. Hier legt das System Referenzbilder und Differenz-Masken ab, um Parameter besser einstellen zu können[cite: 7]. *(Ignoriert in Git)*[cite: 7]

## 🤝 Mitwirken & Support
* **Fehler & Neue Ideen:** Du hast Probleme bei bestimmten Lichtverhältnissen oder wünschst dir neue GUI-Features? Eröffne einfach ein GitHub Issue[cite: 7].
* **Pull Requests:** Gerne gesehen[cite: 7]! 

## ⚖️ Lizenz & Nutzungsrechte
Dieses Projekt ist ein Herzensprojekt und lizenziert unter **[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.de)**[cite: 7]. Weitere Details und meine persönlichen Anmerkungen zur Nutzung findest du in der Datei [**LICENSE.md**](./LICENSE.md)[cite: 7].

**Was mir wichtig ist:**[cite: 7]
* ✅ **Privat & Verein:** Ich habe das System für Freunde, Familie und meinen Schützenverein gebaut[cite: 7]. Ihr dürft es sehr gerne nachbauen, anpassen und für euer Training nutzen[cite: 7]!
* ❌ **Gewerbliche Nutzung:** Da extrem viel Freizeit und Herzblut in der Entwicklung steckt, möchte ich nicht, dass Firmen mein System ohne Rücksprache kommerziell vermarkten oder damit Profit erzielen[cite: 7].

**Du hast eine gewerbliche Idee?**[cite: 7]
Falls du TargetVision DeLübs über den privaten Bereich hinaus nutzen möchtest (z.B. Verkauf von Anlagen oder kommerzielle Events), melde dich einfach bei mir[cite: 7]. Wir finden sicher eine faire Lösung[cite: 7]. Kontaktiere mich dazu am besten über ein GitHub-Issue oder meine Homepage[cite: 7].