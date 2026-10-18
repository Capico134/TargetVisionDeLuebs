import cv2
import time

def test_camera(backend_name, backend_id, force_mjpeg):
    print(f"\n{'='*50}\nStarte Test: {backend_name} | MJPEG erzwungen: {force_mjpeg}")
    
    # 0 ist meist die erste angeschlossene USB-Kamera
    cap = cv2.VideoCapture(1, backend_id)
    if not cap.isOpened():
        print("Fehler: Kamera konnte mit diesem Backend nicht geöffnet werden.")
        return

    # Wir klopfen wieder für MJPEG an
    if force_mjpeg:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)

    # Auslesen, was der Windows-Treiber uns WIRKLICH gegeben hat
    actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fcc_str = "".join([chr((fcc >> 8 * i) & 0xFF) for i in range(4)]) if fcc != 0 else "Unbekannt"
    
    print(f"Treiber antwortet: {actual_w}x{actual_h} | Format: {fcc_str}")
    print("Drücke 'q' im Videofenster für den nächsten Test...\n")

    prev_time = time.time()
    fps_filtered = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Kein Bild empfangen.")
            break
            
        curr_time = time.time()
        dt = curr_time - prev_time
        prev_time = curr_time
        
        # FPS glätten für saubere Anzeige
        if dt > 0:
            fps_filtered = fps_filtered * 0.9 + (1.0 / dt) * 0.1
            
        text = f"{backend_name} | MJPEG: {force_mjpeg} | FPS: {int(fps_filtered)}"
        cv2.putText(frame, text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)
        
        cv2.imshow("Kamera Debugger", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    print("Starte Kamera-Diagnose...")
    
    # Test 1: Der aktuelle TargetVision-Weg (DirectShow)
    test_camera("DirectShow (DSHOW)", cv2.CAP_DSHOW, force_mjpeg=True)
    
    # Test 2: Der modernere Windows-Weg (Media Foundation)
    test_camera("Media Foundation (MSMF)", cv2.CAP_MSMF, force_mjpeg=True)
    
    # Test 3: Die komplette OpenCV-Automatik (lässt Windows entscheiden)
    test_camera("OpenCV Automatik (ANY)", cv2.CAP_ANY, force_mjpeg=False)
    
    print("\nDiagnose beendet.")