import os
import platform
import cv2
import threading
import time

class AsyncCamera:
    # ---> Anpassung der Argumente <---
    def __init__(self, cam_index, backend_str, width, height, fps_target, codec_str, init_modus, log_callback, name=""):
        if isinstance(cam_index, str):
            cam_index = cam_index.strip().strip('\'"').strip()
            
        self.cam_index = cam_index
        self.backend_str = backend_str
        self.codec_str = codec_str
        self.init_modus = init_modus
        self.width = width
        self.height = height
        self.fps_target = fps_target
        self.log = log_callback
        self.name = name

        # Unterscheidung: Physische USB-Kamera (int) vs. Stream/Videodatei (str)
        self.is_stream_or_file = isinstance(cam_index, str)
        self.is_local_file = self.is_stream_or_file and os.path.isfile(cam_index)

        self.cap = None
        self.latest_frame = None
        self.new_frame_available = False
        self.running = False
        self.lock = threading.Lock()
        self.thread = None
        
        self.actual_w, self.actual_h = 0, 0
        self.actual_fps, self.actual_exp = 0, 0
        self.actual_codec = "Unbekannt"
        self.playback_paused = False
        self.backend = None

    def toggle_pause(self):
        """Pausiert oder startet die Wiedergabe einer lokalen Videodatei."""
        if self.is_local_file:
            self.playback_paused = not self.playback_paused
            return self.playback_paused
        return False

    def start(self):
        """Öffnet die Kamera anhand der dynamischen Vorgaben aus der config.ini"""
        if self.is_stream_or_file:
            # Netzwerk-Streams (RTSP/HTTP) und lokale Videodateien laufen über FFmpeg (CAP_ANY)
            backends_to_try = [cv2.CAP_ANY]
        else:
            if platform.system() != 'Windows':
                backends_to_try = [cv2.CAP_ANY]
            else:
                # Übersetze den String aus der config.ini
                if self.backend_str == 'MSMF':
                    backends_to_try = [cv2.CAP_MSMF]
                elif self.backend_str == 'DSHOW':
                    backends_to_try = [cv2.CAP_DSHOW]
                else: # AUTO
                    backends_to_try = [cv2.CAP_MSMF, cv2.CAP_DSHOW]
        
        for current_backend in backends_to_try:
            
            # --- 1. Parameter vorbereiten (Pre-Set) ---
            params = []
            if self.init_modus == 'PRE' and not self.is_stream_or_file:
                if self.codec_str != 'AUTO' and self.codec_str != 'NONE':
                    params.extend([cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.codec_str)])
                
                params.extend([
                    cv2.CAP_PROP_FRAME_WIDTH, self.width,
                    cv2.CAP_PROP_FRAME_HEIGHT, self.height,
                    cv2.CAP_PROP_FPS, self.fps_target
                ])
                self.cap = cv2.VideoCapture(self.cam_index, current_backend, params)
            else:
                # Nacktes Öffnen (Post-Set)
                self.cap = cv2.VideoCapture(self.cam_index, current_backend)
                
            if not self.cap.isOpened():
                continue

            # --- 2. Parameter erzwingen (Post-Set oder Stream-Optimierung) ---
            if self.is_stream_or_file:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            elif self.init_modus == 'POST':
                if self.codec_str != 'AUTO' and self.codec_str != 'NONE':
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.codec_str))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_FPS, self.fps_target)

            self.cap.grab()
            self.cap.retrieve()
            
            self.actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            if self.actual_w > 0 and self.actual_h > 0:
                self.backend = current_backend
                break
            else:
                self.cap.release()
                
        if not self.cap or not self.cap.isOpened() or self.actual_w == 0:
            self.log("SYSTEM", f"Kamera {self.name} -> ⚠️ FEHLER: Quelle '{self.cam_index}' antwortet nicht!", True)
            return False

        self.actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.actual_exp = self.cap.get(cv2.CAP_PROP_EXPOSURE)
        
        try:
            fcc = int(self.cap.get(cv2.CAP_PROP_FOURCC))
            codec = "".join([chr((fcc >> 8 * i) & 0xFF) for i in range(4)]).strip()
            self.actual_codec = codec if codec and codec.isprintable() else "RAW/Stream"
        except:
            self.actual_codec = "Unbekannt"

        backend_name = "FILE" if self.is_local_file else ("STREAM" if self.is_stream_or_file else ("MSMF" if self.backend == cv2.CAP_MSMF else ("DSHOW" if self.backend == cv2.CAP_DSHOW else "ANY")))
        self.log("SYSTEM", f"Kamera {self.name} ({backend_name}) -> {self.actual_w}x{self.actual_h} | Codec: {self.actual_codec} | FPS: {self.actual_fps} | Exp: {self.actual_exp}", True)

        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        return True

    def _smart_set(self, prop, target_value):
        """Setzt einen OpenCV-Parameter nur, wenn er abweicht."""
        if self.cap and self.cap.get(prop) != target_value:
            self.cap.set(prop, target_value)
            
    def set_exposure(self, belichtung_str, is_windows=True):
        """Setzt die Belichtung zur Laufzeit (wird bei Streams/Dateien automatisch übersprungen)."""
        if self.is_stream_or_file or not self.cap or not self.cap.isOpened() or belichtung_str.strip().lower() == 'standard':
            return
            
        auto_mode_val = 1 if is_windows else 3
        manual_mode_val = 0 if is_windows else 1
            
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
        """Der Worker-Thread: Liest Bilder aus (inkl. Echtzeit-Bremse für Test-Videos)."""
        file_delay = 0.0
        if self.is_local_file:
            fps = self.actual_fps if (self.actual_fps and 0 < self.actual_fps < 120) else (self.fps_target if self.fps_target > 0 else 30.0)
            file_delay = 1.0 / fps

        while self.running:
            # ---> NEU: Wenn pausiert, tun wir einfach gar nichts und warten <---
            if self.playback_paused and self.is_local_file:
                time.sleep(0.05)
                continue
                
            t_start = time.perf_counter()
            ret, frame = self.cap.read()
            
            if ret:
                with self.lock:
                    self.latest_frame = frame
                    self.new_frame_available = True
                if self.is_local_file and file_delay > 0:
                    elapsed = time.perf_counter() - t_start
                    if elapsed < file_delay:
                        time.sleep(file_delay - elapsed)
            else:
                if self.is_local_file:
                    # Testvideo ist am Ende angekommen -> Nahtlos zurück auf Anfang!
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    time.sleep(0.01)

    def read(self):
        """Liefert eine Kopie des neuesten Bildes UND ob es frisch ist."""
        with self.lock:
            if self.latest_frame is None:
                return None, False
            
            is_new = self.new_frame_available
            self.new_frame_available = False
            return self.latest_frame.copy(), is_new

    def stop(self):
        """Beendet den Thread und gibt die Hardware frei."""
        self.running = False
        if self.thread:
            self.thread.join()
        if self.cap:
            self.cap.release()