# 🎯 TargetVision DeLübs
Das intelligente Computer-Vision-System zur Treffererkennung für laufende und stehende Schießscheiben.

*TargetVision DeLübs* reiht sich in die DeLübs-Softwarefamilie ein und entstand als Vater-Sohn-Projekt, um normale Webcams in ein hochpräzises Trefferanalyse-System zu verwandeln. Es überwindet die typischen Probleme von Kamerasystemen auf dem Schießstand (Schattenwurf, mechanisches Wackeln der Anlage) durch eine clevere Bildverarbeitungs-Logik.

## 📺 Media & Story
Folge dem Projekt auf YouTube, um über neue Funktionen informiert zu werden. Hinterlasst auch gerne einen Kommentar in den Videos oder auf der Homepage!
* 🎥 **YouTube-Shorts:** [https://www.youtube.com/@DeLuebs]
* ℹ️ **Homepage:** [https://DeLuebs.de/]

## 🔬 High-Precision Engine
In diesem System stecken Algorithmen, die speziell für den rauen und optisch schwierigen Schießstand-Alltag entwickelt wurden:
## 🔬 High-Precision Engine

In diesem System stecken Algorithmen, die speziell für den rauen und optisch schwierigen Schießstand-Alltag entwickelt wurden:
* **Akkumuliertes Schuss-Gedächtnis:** Zuvor geschossene Löcher werden in einer kontinuierlichen Maske gespeichert und mathematisch subtrahiert. Alte Treffer stören die neue Erkennung somit nicht.
* **Farb-Differenz-Trick zur Trefferanalyse:** Die Schusserkennung verlässt sich nicht auf simples Schwarz-Weiß. Die Differenz zwischen Referenz und Live-Bild wird hochpräzise in voller Farbe (RGB) berechnet, *bevor* sie in geglättete Graustufen umgewandelt wird. So werden selbst neue Treffer zuverlässig erkannt, bei denen die rote Wand exakt dieselbe Helligkeit aufweist wie die braune Zielscheibe!
* **Smart-Hybrid Zielerfassung:** Das System entscheidet pro Treffer dynamisch über den besten Erkennungs-Algorithmus. Während saubere Schüsse blitzschnell und ressourcenschonend berechnet werden, schaltet die Engine bei stark ausgefransten Löchern oder Doppelschüssen vollautomatisch auf einen komplexen Hough-Kreisbogen-Algorithmus um. So wird das exakte Zentrum des Schusses selbst bei völlig zerrissener Pappe zielsicher gefunden.
* **Intelligente Pausenerkennung:** Das System prüft den Wand-Hintergrund in allen 3 Farbkanälen. Fährt die Scheibe weg, pausiert die Engine automatisch – das spart massiv CPU-Ressourcen und verhindert Fehlerkennungen.
* **Umgebungslicht-Normalisierung:** Helligkeitsschwankungen auf der Pappe werden vor der Analyse dynamisch ausgeglichen.
* **Dual-Kamera Support:** Unterstützt zwei Kameras (z.B. linke und rechte Seite) gleichzeitig über Multithreading.
* **Visuelles Aufhübschen:** Für das Auge am Monitor können die Farben des Live-Bildes künstlich gesättigt werden, ohne dass die Algorithmen im Hintergrund beeinflusst werden.

## 🚀 Installation & Start
1. **Repo klonen** oder als ZIP herunterladen.
2. **Abhängigkeiten installieren:** `pip install -r requirements.txt` (enthält z.B. OpenCV und NumPy).
3. **Konfiguration:** Die mitgelieferte `config.example.ini` beim ersten Start einfach ignorieren – das Programm erstellt automatisch eine frische `config.ini` mit hilfreichen Kommentaren für dein System.
4. **Starten:** Führe `StartTargetVisionDeLuebs.bat` aus oder starte direkt über `python TargetVisionDeLuebs.py`.

### 🎨 Praxistipp: Hintergrund-Farbwerte (RGB) exakt ermitteln

Damit die automatische Pausenerkennung perfekt funktioniert, benötigt das System die RGB-Farbwerte deiner Wand aus der Kamera-Perspektive.

> ⚠️ **Wichtiger Hinweis:** Wenn `darstellung_ohne_weissabgleich = yes` aktiviert ist, weichen die Farben auf dem Monitor vom Analysebild ab. Screenshots des Hauptfensters liefern daher falsche Werte!

**Der einfachste Weg zu den exakten Werten:**
1. **Referenzbild erzeugen:** Lass die Zielscheibe wegfahren, sodass nur die leere Wand zu sehen ist, und klicke im Programm auf den **Reset-Button** der jeweiligen Kamera.
2. **Foto öffnen:** Das System speichert dabei automatisch das rohe Kamerabild im Ordner `debug_bilder/` als `referenz_left.jpg` bzw. `referenz_right.jpg`. Öffne diese Datei in **Paint** (oder einem anderen Bildbearbeitungsprogramm).
3. **Farbe abgreifen:** Wähle das **Pipetten-Werkzeug** und klicke mitten auf die Wandfläche.
4. **RGB-Werte ablesen:** Klicke oben auf **"Palette bearbeiten"** (Farben bearbeiten). Dort findest du auf der rechten Seite die exakten Werte für **Rot (R)**, **Grün (G)** und **Blau (B)**.
5. **In `config.ini` eintragen:** Übertrage die drei Zahlen in den Abschnitt `[Hintergrund_Links]` bzw. `[Hintergrund_Rechts]`.

## ⚙️ Dateistruktur
* `TargetVisionDeLuebs.py` – Die Haupt-Engine.
* `config.ini` – Wird beim Start generiert. Hier stellst du Kameras, Crops, Wandfarben (RGB) und Erkennungstoleranzen ein. *(Wird durch .gitignore nicht auf GitHub hochgeladen)*
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