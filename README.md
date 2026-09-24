# 🎯 TargetVision DeLübs
[![TargetVision Regression Tests](https://github.com/Capico134/TargetVisionDeLuebs/actions/workflows/regression_tests.yml/badge.svg)](https://github.com/Capico134/TargetVisionDeLuebs/actions/workflows/regression_tests.yml)
Das intelligente Computer-Vision-System zur Treffererkennung für laufende und stehende Schießscheiben.

*TargetVision DeLübs* reiht sich in die DeLübs-Softwarefamilie ein und entstand als Vater-Sohn-Projekt, um normale Webcams in ein hochpräzises Trefferanalyse-System zu verwandeln. Es überwindet die typischen Probleme von Kamerasystemen auf dem Schießstand (Schattenwurf, mechanisches Wackeln der Anlage) durch eine clevere Bildverarbeitungs-Logik.

## 📺 Media & Story
Folge dem Projekt auf YouTube, um über neue Funktionen informiert zu werden. Hinterlasst auch gerne einen Kommentar in den Videos oder auf der Homepage!
* 🎥 **YouTube-Shorts:** [https://www.youtube.com/@DeLuebs]
* ℹ️ **Homepage:** [https://DeLuebs.de/]

## 🏆 Training & Wettkampf
Neben der reinen Erkennung bietet das System Features für den echten Schießstand-Alltag:
* **Präzise Ringwertung:** Das System erkennt nicht nur das Loch, sondern berechnet auf Wunsch die exakte Ringwertung (inklusive 10.9 Zehntelwertung).
* **Flexible Zielscheiben-Typen:** Egal ob Luftgewehr oder Luftpistole – über die Konfiguration lassen sich verschiedene Zielscheiben-Profile mit exakten physikalischen Ring-Maßen (in mm) hinterlegen und jederzeit wechseln.
* **Zwei-Spieler-Modus:** Durch den Dual-Kamera Support (links und rechts) können zwei Schützen im direkten Duell gegeneinander antreten.
* **Highscore-System:** Die besten Ergebnisse und Serien werden gespeichert und sorgen für langanhaltende Motivation im Training.

## 🔬 High-Precision Engine
In diesem System stecken Algorithmen, die speziell für den rauen und optisch schwierigen Schießstand-Alltag entwickelt wurden:
* **Akkumuliertes Schuss-Gedächtnis:** Zuvor geschossene Löcher werden in einer kontinuierlichen Maske gespeichert und mathematisch subtrahiert. Alte Treffer stören die neue Erkennung somit nicht.
* **Farb-Differenz-Trick zur Trefferanalyse:** Die Differenz zwischen Referenz und Live-Bild wird hochpräzise in voller Farbe (RGB) berechnet, *bevor* sie in geglättete Graustufen umgewandelt wird. So werden selbst neue Treffer zuverlässig erkannt, bei denen die rote Wand exakt dieselbe Helligkeit aufweist wie die braune Zielscheibe!
* **Subpixel-Genauigkeit durch Supersampling:** Durch ein unbestechliches binäres 4x4 Supersampling der Trefferkoordinaten eliminiert die Engine Rundungsfehler (ohne künstliche Kantenglättungs-Artefakte) und liefert höchste Präzision, was gleichzeitig die Performance steigert.
* **Smart-Hybrid Zielerfassung:** Das System entscheidet pro Treffer dynamisch über den besten Erkennungs-Algorithmus. Bei stark ausgefransten Löchern schaltet die Engine vollautomatisch auf einen komplexen Hough-Kreisbogen-Algorithmus um. Ein innovatives Kombi-Ranking gleicht die gefundenen Kreise anschließend mit dem realen Riss ab, um Geistertreffer auszuschließen.
* **Dynamische Farb-Bonus-Filterung:** Um ausgefranste Trefferränder auf der Zielscheibe von echten Veränderungen exakt unterscheiden zu können, kann ein Farb-Bonus-System (`farb_bonus_aktiv`) zugeschaltet werden, welches die Wandfarbe isoliert und Fehlerkennungen an intakten Papierrändern minimiert.
* **Anti-Verschiebungs-Filter (Aspect-Ratio):** Mechanische Ruckler der Zuganlage, die als unnatürlich lange Sicheln im Bild auftauchen, werden durch eine blitzschnelle Analyse des Seitenverhältnisses gnadenlos ignoriert.
* **Umgebungslicht-Normalisierung:** Helligkeitsschwankungen auf der Pappe werden vor der Analyse dynamisch ausgeglichen.
* **Intelligente Pausenerkennung:** Das System prüft den Wand-Hintergrund in allen 3 Farbkanälen. Fährt die Scheibe weg, pausiert die Engine automatisch – das spart CPU-Ressourcen und verhindert Fehlerkennungen.
* **Selbstheilende Konfiguration:** Ein "Config-Spion" überwacht die Parameter im Hintergrund. Fehlende Werte werden durch sichere Fallbacks ersetzt und lückenlos für die Fehleranalyse protokolliert.

## 🚀 Installation & Start
1. **Repo klonen** oder als ZIP herunterladen.
2. **Konfiguration:** Die mitgelieferte `config.example.ini` beim ersten Start einfach ignorieren – das Programm erstellt automatisch eine frische `config.ini` mit hilfreichen Kommentaren für dein System.
3. **Starten:** Führe einfach die `StartTargetVisionDeLuebs.bat` aus. Das Skript prüft und installiert automatisch alle benötigten Abhängigkeiten (`requirements.txt`)[cite: 6] und startet anschließend direkt das System[cite: 6].

### 🎨 Praxistipp: Hintergrund-Farbwerte (RGB) exakt ermitteln
Damit die automatische Pausenerkennung (und die optionale Treffererkennung mittels Farb-Bonus) perfekt funktioniert, benötigt das System die exakten RGB-Farbwerte deiner Wand.

**Der bequemste Weg zur perfekten Farbe:**
Das System bringt ein integriertes Labor-Werkzeug mit. 
Lass die Zielscheibe wegfahren, sodass nur die Wand im Bild ist, und nutze den eingebauten **"Farbe picken"**-Button in der grafischen Labor-Oberfläche. Ein Klick ins Bild überträgt die perfekten RGB-Werte automatisch in deine Konfiguration!

## ⚙️ Dateistruktur
* `TargetVisionDeLuebs.py` – Die Haupt-Engine.
* `LaborDeLuebs.py` – Die visuelle Labor-Umgebung zur Analyse von Schüssen und zur Parameter-Optimierung.
* `config.ini` – Wird beim Start generiert. Hier stellst du Kameras, Crops, Wandfarben (RGB) und Erkennungstoleranzen ein. *(Wird durch .gitignore nicht auf GitHub hochgeladen)*
* `zielscheiben.json` – Hier sind die exakten physikalischen Ringmaße der unterschiedlichen Scheibentypen hinterlegt.
* `debug_bilder/` – Ein automatischer Ordner für die Fehleranalyse. Hier legt das System Referenzbilder und Differenz-Masken ab, um Parameter besser einstellen zu können. *(Ignoriert in Git)*

## 🤝 Mitwirken & Support
* **Fehler & Neue Ideen:** Du hast Probleme bei bestimmten Lichtverhältnissen oder wünschst dir neue GUI-Features? Eröffne einfach ein GitHub Issue.
* **Pull Requests:** Gerne gesehen! 

## ⚖️ Lizenz & Nutzungsrechte
Dieses Projekt ist ein Herzensprojekt und lizenziert unter **[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.de)**. Weitere Details und meine persönlichen Anmerkungen zur Nutzung findest du in der Datei [**LICENSE.md**](./LICENSE.md).

**Was mir wichtig ist:**
* ✅ **Privat & Verein:** Ich habe das System für Freunde, Familie und meinen Schützenverein gebaut. Ihr dürft es sehr gerne nachbauen, anpassen und für euer Training nutzen!
* ❌ **Gewerbliche Nutzung:** Da extrem viel Freizeit und Herzblut in der Entwicklung steckt, möchte ich nicht, dass Firmen mein System ohne Rücksprache kommerziell vermarkten oder damit Profit erzielen.

**Du hast eine gewerbliche Idee?**
Falls du TargetVision DeLübs über den privaten Bereich hinaus nutzen möchtest (z.B. Verkauf von Anlagen oder kommerzielle Events), melde dich einfach bei mir. Wir finden sicher eine faire Lösung. Kontaktiere mich dazu am besten über ein GitHub-Issue oder meine Homepage.