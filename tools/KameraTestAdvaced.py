import cv2
import time
import os
from datetime import datetime

# =====================================================================
# SICHERE KAMERA-DIAGNOSE (Mit Live-Zwischenspeicherung)
# =====================================================================
CAM_INDEX = 1  # Ggf. auf 0 anpassen
TEST_DURATION = 2.0  # Verkürzt auf 2 Sekunden pro Test für schnelleren Durchlauf

BACKENDS = [
    ("MSMF", cv2.CAP_MSMF),
    ("DSHOW", cv2.CAP_DSHOW)
]
INIT_MODES = ["Pre-Set", "Post-Set"] 
RESOLUTIONS = [(1920, 1080), (1280, 720)]
FPS_TARGETS = [30]  # Konzentrieren uns auf 30 FPS
CODECS = ["MJPG", "YUY2", "None"]

def decode_fourcc(v):
    try:
        v = int(v)
        res = "".join([chr((v >> 8 * i) & 0xFF) for i in range(4)]).strip()
        return res if res.isprintable() and len(res) > 0 else "Unbekannt"
    except Exception:
        return "Unbekannt"

def run_test_iteration(backend_name, backend_id, init_mode, w, h, fps_target, codec_str):
    print(f"Test: {backend_name} | {init_mode} | {w}x{h} | {codec_str}...", end=" ", flush=True)
    
    t0 = time.perf_counter()
    cap = None
    
    try:
        if init_mode == "Pre-Set":
            params = []
            if codec_str != "None":
                params.extend([cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*codec_str)])
            params.extend([
                cv2.CAP_PROP_FRAME_WIDTH, w,
                cv2.CAP_PROP_FRAME_HEIGHT, h,
                cv2.CAP_PROP_FPS, fps_target
            ])
            cap = cv2.VideoCapture(CAM_INDEX, backend_id, params)
        else:
            cap = cv2.VideoCapture(CAM_INDEX, backend_id)
            if cap.isOpened():
                if codec_str != "None":
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*codec_str))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                cap.set(cv2.CAP_PROP_FPS, fps_target)
                
        if not cap or not cap.isOpened():
            print("❌ FEHLSCHLAG (Öffnet nicht)")
            if cap: cap.release()
            return "FEHLSCHLAG", 0.0, 0, 0, 0, "N/A"
            
        ret, _ = cap.read()
        if not ret:
            print("❌ FEHLSCHLAG (Kein Bild)")
            cap.release()
            return "FEHLSCHLAG", 0.0, 0, 0, 0, "N/A"
            
        t_init = time.perf_counter() - t0
        
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fcc = decode_fourcc(cap.get(cv2.CAP_PROP_FOURCC))
        
        frames = 0
        t_start_measure = time.perf_counter()
        while (time.perf_counter() - t_start_measure) < TEST_DURATION:
            ret, _ = cap.read()
            if ret:
                frames += 1
                
        t_end = time.perf_counter() - t_start_measure
        real_fps = frames / t_end if t_end > 0 else 0
        
        status = "✅ OK" if real_fps > 5 else "⚠️ SEHR LANGSAM"
        print(f"{status} (Init: {t_init:.2f}s | Real-FPS: {real_fps:.1f})")
        
        cap.release()
        return status, t_init, real_fps, actual_w, actual_h, actual_fcc

    except Exception as e:
        print(f"❌ CRASH: {e}")
        if cap: cap.release()
        return "CRASH", 0.0, 0.0, 0, 0, "N/A"

if __name__ == "__main__":
    print("=" * 80)
    print("🚀 SICHERE KAMERA-DIAGNOSE STARTET (Schreibt live in Datei)")
    print("=" * 80)
    print()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    save_folder = os.path.abspath(os.path.join(base_dir, '..', 'savegames'))
    os.makedirs(save_folder, exist_ok=True)
    file_path = os.path.join(save_folder, "KameraTestErgebnisse.txt")

    header = f"{'Backend':<7} | {'Init':<8} | {'Req Res':<9} | {'Req FPS':<7} | {'Req Codec':<9} | {'Act Res':<9} | {'Real FPS':<8} | {'Act Codec':<9} | {'Init Zeit':<9} | {'Status'}"
    separator = "-" * len(header)

    # Datei initialisieren
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"=== KAMERA TEST LAUF - {datetime.now()} ===\n{header}\n{separator}\n")

    for backend_name, backend_id in BACKENDS:
        for init_mode in INIT_MODES:
            for w, h in RESOLUTIONS:
                for codec in CODECS:
                    for fps in FPS_TARGETS:
                        res = run_test_iteration(backend_name, backend_id, init_mode, w, h, fps, codec)
                        status, t_init, real_fps, act_w, act_h, act_fcc = res
                        
                        line = f"{backend_name:<7} | {init_mode:<8} | {w}x{h:<5} | {fps:<7} | {codec:<9} | {act_w}x{act_h:<5} | {real_fps:<8.1f} | {act_fcc:<9} | {t_init:<8.2f}s | {status}"
                        
                        # Sofort zeilenweise anhängen, damit man bei einem Hänger die Ergebnisse hat!
                        with open(file_path, "a", encoding="utf-8") as f:
                            f.write(line + "\n")
                            
                        time.sleep(0.3)

    print("\n" + "=" * 80)
    print(f"✅ Test beendet! Ergebnisse wurden live gespeichert in:\n   {file_path}")
    print("=" * 80)
    input("Drücke ENTER, um das Fenster zu schließen...")