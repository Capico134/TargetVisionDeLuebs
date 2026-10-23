# ADR-001: Zentraler Supersampling-Cache vs. Lokaler ROI-Zuschnitt

**Datum:** 23. Oktober 2026  
**Status:** 🔴 Verworfen / Abgelehnt  
**Kontext:** Performance-Optimierung der Computer-Vision-Engine (TargetVision)  

---

## 1. Ausgangslage & Problemstellung
In der `DetectionDeLuebs.py` wertet die Funktion `calculate_hole_score` Treffer-Kandidaten (Battle Royale) mittels eines 4x-Supersamplings aus. Dazu wird eine kleine Bounding Box (ROI) um den Kandidaten ausgeschnitten, per `cv2.resize` (INTER_NEAREST) vierfach vergrößert, mit einer Subpixel-genauen OpenCV-Kreismaske (`cv2.circle`) überlagert und über Bitwise-Operationen (`cv2.bitwise_and`, `cv2.countNonZero`) die exakte Überdeckung berechnet.

**Das vermutete Bottleneck:**
Bei glasklaren Aufnahmen (z. B. Match87) findet der Hough-Algorithmus an den messscharfen Abrisskanten oft dutzende Kandidaten (ø 36,9 pro Schuss). Da das 4x-Supersampling für *jeden* dieser Kandidaten einzeln in einer Schleife ausgeführt wurde, wurde vermutet, dass die ständigen Aufrufe von `cv2.resize` massiv CPU-Zeit fressen.
Basis-Messung (Match87): **6.54 Sekunden**.

## 2. Der Optimierungs-Ansatz (Texture Atlasing / Super-Puffer)
Um die redundanten `cv2.resize`-Aufrufe zu eliminieren, wurde ein "Super-Puffer" konzipiert. 
Die Idee: Anstatt 40 kleine ROIs einzeln hochzuskalieren, wird vor der Schleife **einmalig** ein riesiger Bildausschnitt generiert, der alle denkbaren Kandidaten abdeckt (Größe basierend auf `discard_big_hits`). Dieser Super-Puffer wird nur ein einziges Mal per `cv2.resize` vergrößert. 
Innerhalb der Kandidaten-Schleife greift `calculate_hole_score` dann auf diesen großen High-Res-Puffer zu und schneidet sich per Numpy-Slicing (`puffer[y1:y2, x1:x2]`) in 0,0 Sekunden seinen eigenen, winzigen High-Res-Bereich heraus.

## 3. Die Code-Implementierung (Archiv)

**A) Vorbereitung des Super-Puffers in `detect_new_shot`:**
```python
if self.erkennungs_methode == 'C':
    # 1. Den Super-Puffer berechnen (Einmalig für alle Kandidaten)
    limit_discard = current_caliber_radius * self.discard_big_hits
    puffer_px = int(limit_discard + current_caliber_radius) + 2
    
    super_x1 = max(0, int(rx) - puffer_px)
    super_y1 = max(0, int(ry) - puffer_px)
    super_x2 = min(thresh_new.shape[1], int(rx + rw) + puffer_px)
    super_y2 = min(thresh_new.shape[0], int(ry + rh) + puffer_px)
    
    super_w, super_h = super_x2 - super_x1, super_y2 - super_y1
    scale = 4
    
    # 2. Nur EINMAL hochskalieren!
    super_new_hr = cv2.resize(thresh_new[super_y1:super_y2, super_x1:super_x2], 
                              (super_w * scale, super_h * scale), interpolation=cv2.INTER_NEAREST)
    super_raw_hr = cv2.resize(thresh_raw[super_y1:super_y2, super_x1:super_x2], 
                              (super_w * scale, super_h * scale), interpolation=cv2.INTER_NEAREST)
```

**B) Slicing in der `calculate_hole_score`:**
```python
def calculate_hole_score(self, cx, cy, radius, super_new_hr, super_raw_hr, super_x1, super_y1, scale=4):
    r_int = int(radius) + 2
    
    # Absolute Koordinaten für Kandidaten
    abs_x1, abs_y1 = int(cx) - r_int, int(cy) - r_int
    abs_x2, abs_y2 = int(cx) + r_int, int(cy) + r_int
    
    # Relative Koordinaten INNERHALB des Super-Puffers berechnen
    crop_x1 = max(super_x1, abs_x1)
    crop_y1 = max(super_y1, abs_y1)
    crop_x2 = min(super_x1 + (super_new_hr.shape[1] // scale), abs_x2)
    crop_y2 = min(super_y1 + (super_new_hr.shape[0] // scale), abs_y2)
    
    rel_x1, rel_y1 = crop_x1 - super_x1, crop_y1 - super_y1
    rel_x2, rel_y2 = crop_x2 - super_x1, crop_y2 - super_y1
    
    # Numpy-Slicing ohne Kopieraufwand (0 CPU-Last)
    hr_x1, hr_x2 = rel_x1 * scale, rel_x2 * scale
    hr_y1, hr_y2 = rel_y1 * scale, rel_y2 * scale
    
    roi_new_hr = super_new_hr[hr_y1:hr_y2, hr_x1:hr_x2]
    roi_raw_hr = super_raw_hr[hr_y1:hr_y2, hr_x1:hr_x2]
    
    # ... Bitwise-Operationen und Pixel-Zählen folgen ...
```

## 4. Ergebnis & Fazit
*   **Zeit vorher (Lokales Resize pro Kandidat):** 6.54 Sekunden
*   **Zeit nachher (Super-Puffer & Slicing):** 6.49 Sekunden
*   **Gewinn:** ~50 Millisekunden (unter 1 % Verbesserung)

**Erkenntnis:** 
Die Optimierung war algorithmisch korrekt (Numpy-Views kosten keine Zeit, `cv2.resize` wurde reduziert), der Flaschenhals lag jedoch woanders. Ein einzelner `cv2.resize`-Aufruf für eine 40x40-Matrix kostet in C++ vernachlässigbar wenig Zeit. Der eigentliche Rechenaufwand entsteht durch die pure Masse an verarbeiteten Pixeln bei den anschließenden Bitwise-Operationen (`cv2.bitwise_and` und `cv2.countNonZero`) auf dem 4x-Raster, welcher bei beiden Methoden identisch bleibt.

**Entscheidung:**
Die minimale Performance-Einsparung rechtfertigt in keiner Weise die deutlich gestiegene Code-Komplexität (Verschachtelung der relativen und absoluten Koordinaten, Risiko von Rundungs- und Offset-Fehlern bei Subpixel-Verschiebungen).
Der Code wird auf den ursprünglichen Zustand zurückgerollt: Jeder Kandidat extrahiert und skaliert seine eigene ROI.