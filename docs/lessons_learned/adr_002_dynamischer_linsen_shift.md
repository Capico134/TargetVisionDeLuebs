# Lesson Learned: Dynamische Linsenkorrektur bei Verschiebungskorrektur

**Datum:** 20.11.2026
**Status:** Verworfen (Over-Engineered / Verstoß gegen ELA)
**Thema:** Verschiebung des optischen Linsenzentrums bei Software-Bildstabilisierung

## 1. Ausgangssituation
Das System verfügt über eine robuste Verschiebungskorrektur (Bildstabilisierung). Wenn die Kamera durch einen mechanischen Ruck am Seilzug wackelt, verschiebt die Software das Rohbild um einen Vektor (`dx`, `dy`), um die Zielscheibe wieder exakt auf die alten Koordinaten zu legen. 
Gleichzeitig nutzt das System eine Linsenkorrektur (Koeffizienten für $r^2$ und $r^4$), um Kissen- und Tonnenverzerrungen auszugleichen. Der Nullpunkt für diese Verzerrung ist das optische Linsenzentrum der Kamera (`lens_cx`, `lens_cy`).

## 2. Die Überlegung (100-Punkte-Frage)
Da das Linsenzentrum physisch starr an der Kamera-Hardware fixiert ist, das Papier (und damit unser Software-Bild) aber um `dx, dy` verschoben wurde, wandert das Papier virtuell unter der Linse weg. 
Um mathematisch 100 % korrekt zu bleiben, müsste der Linsenmittelpunkt in der Software-Berechnung invers um exakt diesen Vektor mitverschoben werden, bevor die Pythagoras-Distanzen für die Ringwertung oder die Ellipsen-Zeichnung berechnet werden.

## 3. Warum es verworfen wurde
Obwohl die physikalische Überlegung absolut korrekt ist und die reine Code-Menge überschaubar wäre, wurde die Implementierung nach dem **ELA-Prinzip (Einfach, Lesbar, Allgemein)** verworfen:

1. **Fehlende Verhältnismäßigkeit (Praxisrelevanz):** Die mechanischen Toleranzen der Zielscheibenanlage (Papierrisse, Schattenwurf, Schwingungen des Seilzugs) verursachen Fehler, die um ein Vielfaches größer sind als der theoretische Linsenfehler. Ein Schuss, der durch den minimalen Offset auf der flachen Verzerrungskurve (nahe der Bildmitte) den Bruchteil eines Millimeters anders berechnet wird, geht im Grundrauschen der echten Welt vollständig unter.
2. **Architektonische Verschmutzung (Kopplung):** Um den `applied_shift` für eine irrelevante Nachkommastelle durch das System zu schleifen, müssten saubere, entkoppelte Methoden in `StateManager`, `DetectionDeLuebs` und den Renderern plötzlich spezifische Korrektur-Parameter entgegennehmen. Dies bläht die Methodensignaturen auf und schafft harte Abhängigkeiten zwischen eigentlich unabhängigen Modulen.

**Fazit:** Der Linsenmittelpunkt bleibt als starrer Config-Wert erhalten. Die minimale theoretische Ungenauigkeit wird zugunsten einer sauberen, wartbaren Code-Architektur bewusst in Kauf genommen.

---

## 4. Archivierte Code-Änderungen (Für eventuelle spätere Wiederaufnahme)

Falls das System in Zukunft (z.B. für extreme Weitwinkel-Fischaugen-Linsen) doch darauf angewiesen sein sollte, sind hier die notwendigen Code-Pfade dokumentiert, um den dynamischen Shift quer durch das System zu leiten:

### A) In `StateManagerDeLuebs.py` (Punkteberechnung)
Signatur und Linsenzentrum anpassen:
```python
def calculate_score(self, side, cx, cy, applied_shift=(0, 0)):
    # ...
    cx_linse_dyn = cx_linse + applied_shift[0]
    cy_linse_dyn = cy_linse + applied_shift[1]
    
    true_shot_x, true_shot_y = Helfer.undistort_point_mm(cx, cy, cx_linse_dyn, cy_linse_dyn, px_x, px_y, korrektur, korr_r4, r_limit_mm)
    true_null_x, true_null_y = Helfer.undistort_point_mm(nullpunkt[0], nullpunkt[1], cx_linse_dyn, cy_linse_dyn, px_x, px_y, korrektur, korr_r4, r_limit_mm)

def add_shot(self, side, cx, cy, cv_data=None):
    shift_vec = (cv_data.get('shift_x', 0), cv_data.get('shift_y', 0)) if cv_data else (0, 0)
    score, raw_score = self.calculate_score(side, cx, cy, applied_shift=shift_vec)
```

### B) In `DetectionDeLuebs.py` (Radiusberechnung)
Radius dynamisch anpassen:
```python
def get_local_caliber_radius(self, side, x_px, y_px, applied_shift=(0,0)):
    # ...
    lens_cx_dyn = lc['lens_cx'] + applied_shift[0]
    lens_cy_dyn = lc['lens_cy'] + applied_shift[1]
        
    dx_mm = (x_px - lens_cx_dyn) / lc['px_x']
    dy_mm = (y_px - lens_cy_dyn) / lc['px_y']

# In detect_new_shot (nach dem Alignment):
self.current_frame_shift = applied_shift
# ... Übergabe an get_local_caliber_radius und add_candidate ...
```

### C) In den Renderern (`TargetVisionRenderer.py` & `LaborRendererDeLuebs.py`)
Bevor `Helfer.draw_smart_ellipse` aufgerufen wird:
```python
# Live-Renderer:
dx, dy = self.tracker.detector.last_shift.get(side, (0, 0))
lens_cx += dx
lens_cy += dy

# Labor-Renderer:
cache_idx = current_frame_num - 1
if cache_idx in self.app.frame_cache.get(side, {}):
    dx, dy = self.app.frame_cache[side][cache_idx].get('shift', (0, 0))
    lens_cx += dx
    lens_cy += dy
```
*(Die zentrale `HelperDeLuebs.py` bleibt unangetastet, da sie `lens_cx` und `lens_cy` generisch verarbeitet).*