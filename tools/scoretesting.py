import cv2
import numpy as np

# 1. Erstelle ein künstliches Testbild mit einem mathematisch perfekten Loch
img_w, img_h = 70, 70
true_cx, true_cy, true_r = 35.40, 35.40, 20.0

# Synthetisches Antialiasing-freies Loch erzeugen
y, x = np.ogrid[:img_h, :img_w]
dist_from_center = np.sqrt((x - true_cx)**2 + (y - true_cy)**2)
synthetic_hole = np.zeros((img_h, img_w), dtype=np.uint8)
synthetic_hole[dist_from_center <= true_r] = 255

# 2. Beide Methoden im 4x Supersampling vergleichen
scale = 4
roi_scaled = cv2.resize(synthetic_hole, (img_w * scale, img_h * scale), interpolation=cv2.INTER_NEAREST)

# Variante A: Ohne Offset
mask_a = np.zeros_like(roi_scaled)
cx_a = int(round(true_cx * scale))
cy_a = int(round(true_cy * scale))
cv2.circle(mask_a, (cx_a, cy_a), int(round(true_r * scale)), 255, -1, cv2.LINE_8)
cov_a = cv2.countNonZero(cv2.bitwise_and(mask_a, roi_scaled)) / cv2.countNonZero(mask_a) * 100.0

# Variante B: Mit Subpixel-Offset (+0.5)
mask_b = np.zeros_like(roi_scaled)
cx_b = int(round((true_cx + 0.5) * scale - 0.5))
cy_b = int(round((true_cy + 0.5) * scale - 0.5))
cv2.circle(mask_b, (cx_b, cy_b), int(round(true_r * scale)), 255, -1, cv2.LINE_8)
cov_b = cv2.countNonZero(cv2.bitwise_and(mask_b, roi_scaled)) / cv2.countNonZero(mask_b) * 100.0

print(f"Ergebnis bei Ground Truth ({true_cx}, {true_cy}):")
print(f"-> Deckung OHNE Offset   : {cov_a:.3f}%")
print(f"-> Deckung MIT Subpixel  : {cov_b:.3f}%")