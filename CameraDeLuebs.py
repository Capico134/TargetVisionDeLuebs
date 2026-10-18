import cv2
import threading
import time

class AsyncCamera:
    def __init__(self, cam_index, backend, width, height, fps_target, log_callback, name=""):
        self.cam_index = cam_index
        self.backend = backend
        self.width = width
        self.height = height
        self.fps_target = fps_target
        self.log = log_callback
        self.name = name

        self.cap = None
        self.latest_frame = None
        self.new_frame_available = False  # <--- NEU
        self.running = False
        self.lock = threading.Lock()
        self.thread = None
        
        self.actual_w = 0
        self.actual_h = 0
        self.actual_fps = 0
        self.actual_exp = 0
        self.codec_str = "Unbekannt"

    def start(self):
        """Öffnet die Kamera und startet den Auslese-Thread."""
        self.cap = cv2.VideoCapture(self.cam_index, self.backend)
        if not self.cap.isOpened():
            self.log("SYSTEM", f"Kamera {self.name} -> ⚠️ FEHLER: Hardware antwortet nicht auf Index {self.cam_index}!", True)
            return False

        # WICHTIG: Die Reihenfolge unter MSMF muss EXAKT so lauten: Auflösung -> FPS -> Codec
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps_target)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))

        # Fallback-Prüfung
        if self.cap.get(cv2.CAP_PROP_FPS) < self.fps_target - 1:
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            
        # Warm-up (Erzwingt Aushandlung)
        self.cap.grab()
        self.cap.retrieve()
        
        # Status auslesen
        self.actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.actual_exp = self.cap.get(cv2.CAP_PROP_EXPOSURE)
        
        fourcc_int = int(self.cap.get(cv2.CAP_PROP_FOURCC))
        try:
            codec = "".join([chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)]).strip()
            if not codec or not codec.isprintable() or '\x00' in codec:
                codec = "RAW/YUV (Unkomprimiert)"
            self.codec_str = codec
        except Exception:
            pass

        self.log("SYSTEM", f"Kamera {self.name} -> {self.actual_w}x{self.actual_h} | Codec: {self.codec_str} | FPS: {self.actual_fps} | Exp: {self.actual_exp}", True)

        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        return True

    def _smart_set(self, prop, target_value):
        """Setzt einen OpenCV-Parameter nur, wenn er abweicht."""
        if self.cap and self.cap.get(prop) != target_value:
            self.cap.set(prop, target_value)
            
    def set_exposure(self, belichtung_str, is_windows=True):
        """Setzt die Belichtung zur Laufzeit."""
        if not self.cap or not self.cap.isOpened() or belichtung_str.strip().lower() == 'standard':
            return
            
        auto_mode_val = 1 if is_windows else 3
        manual_mode_val = 0 if is_windows else 1
            
        # ---> DER FIX: Immun gegen Groß-/Kleinschreibung <---
        if belichtung_str.strip().lower() == 'auto':
            self._smart_set(cv2.CAP_PROP_AUTO_EXPOSURE, auto_mode_val)
        else:
            try:
                exp_val = int(belichtung_str)
                if self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE) != manual_mode_val:
                    self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, manual_mode_val)
                    time.sleep(0.05)
                self._smart_set(cv2.CAP_PROP_EXPOSURE, exp_val)
            except ValueError:
                pass

    def _update(self):
        """Der Worker-Thread: Liest Bilder aus und hisst die Flagge."""
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.latest_frame = frame
                    self.new_frame_available = True  # <--- BILD IST NEU!
            else:
                time.sleep(0.01)

    def read(self):
        """Liefert eine Kopie des neuesten Bildes UND ob es frisch ist."""
        with self.lock:
            if self.latest_frame is None:
                return None, False
            
            is_new = self.new_frame_available
            self.new_frame_available = False  # Flagge wieder einholen
            return self.latest_frame.copy(), is_new

    def stop(self):
        """Beendet den Thread und gibt die Hardware frei."""
        self.running = False
        if self.thread:
            self.thread.join()
        if self.cap:
            self.cap.release()