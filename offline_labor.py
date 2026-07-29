import cv2
import numpy as np

# 1. Bilder aus dem Debug-Ordner laden
ref = cv2.imread('debug_bilder/referenz_left.jpg')
live = cv2.imread('debug_bilder/letzte_aufnahme_left.jpg')

if ref is None or live is None:
    print("Fehler: Bilder nicht gefunden! Liegen sie im Ordner 'debug_bilder'?")
    exit()

# 2. Weichzeichnen (exakt wie in der Haupt-Engine)
ref_blur = cv2.GaussianBlur(ref, (7, 7), 0)
live_blur = cv2.GaussianBlur(live, (7, 7), 0)

# 3. Differenz und Threshold (Spiel hier mit der hit_tolerance!)
hit_tolerance = 20
diff_bgr = cv2.absdiff(ref_blur, live_blur)
diff_gray = cv2.cvtColor(diff_bgr, cv2.COLOR_BGR2GRAY)
_, thresh_raw = cv2.threshold(diff_gray, hit_tolerance, 255, cv2.THRESH_BINARY)

# 4. Morphologisches Closing (Der "Kleber" - probiere 3x3, 5x5 oder 7x7)
kernel = np.ones((4, 4), np.uint8)
thresh_closed = cv2.morphologyEx(thresh_raw, cv2.MORPH_CLOSE, kernel)

# 5. Ergebnis zum direkten Vorher-Nachher-Vergleich anzeigen
cv2.imshow(f"1. Rohes Diff (Tolerance: {hit_tolerance})", thresh_raw)
cv2.imshow(f"2. Repariert mit Closing-Filter", thresh_closed)

print("Drücke eine beliebige Taste in einem der Bildfenster, um das Skript zu beenden.")
cv2.waitKey(0)
cv2.destroyAllWindows()