import os
import re
import platform
import cv2
import threading
import time
import numpy as np

# Optionale Imports für Window-Capture (mss) und Hidden-Window-Capture (win32)
try:
    import pygetwindow as gw
    GW_AVAILABLE = True
except ImportError:
    GW_AVAILABLE = False

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    import win32gui
    import win32ui
    import ctypes
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


class AsyncCamera:
    def __init__(self, cam_index, backend_str, width, height, fps_target, codec_str, init_modus, log_callback, name=""):
        if isinstance(cam_index, str):
            cam_index = cam_index.strip().strip('\'"').strip()

        self.backend_str = backend_str
        self.codec_str = codec_str
        self.init_modus = init_modus
        self.width = width
        self.height = height
        self.fps_target = fps_target
        self.log = log_callback
        self.name = name

        # ---> Universelle Filter: |top,bottom,left,right (Crop) & @Breite,Höhe (Resize) <---
        self.win_offsets = (0, 0, 0, 0)  # (top, bottom, left, right)
        self.win_resize = None           # Optionales (target_w, target_h)
        self.capture_mode = None         # None, 'MSS' oder 'WIN32'
        self.win_title = ""
        self._cached_hwnd = None

        raw_source = str(cam_index).strip()

        # In beliebiger Reihenfolge am Ende des Strings nach @W,H und |T,B,L,R suchen
        # (Kollidiert dank $-Anker am Ende NIEMALS mit rtsp://user:pass@ip!)
        for _ in range(2):
            m_resize = re.search(r'@(\d+)\s*,\s*(\d+)$', raw_source)
            if m_resize:
                rw, rh = int(m_resize.group(1)), int(m_resize.group(2))
                if rw > 10 and rh > 10:
                    self.win_resize = (rw, rh)
                raw_source = raw_source[:m_resize.start()].strip()

            m_crop = re.search(r'\|(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)$', raw_source)
            if m_crop:
                self.win_offsets = tuple(int(m_crop.group(i)) for i in range(1, 5))
                raw_source = raw_source[:m_crop.start()].strip()

        # Quell-Typ bestimmen (WINDOW:, WIN32:, USB-Index oder Datei/Stream)
        upper_src = raw_source.upper()
        if upper_src.startswith("WINDOW:"):
            self.capture_mode = "MSS"
            self.win_title = raw_source[7:].strip()
            self.cam_index = raw_source
        elif upper_src.startswith("WIN32:"):
            self.capture_mode = "WIN32"
            self.win_title = raw_source[6:].strip()
            self.cam_index = raw_source
        else:
            # Falls eine USB-Kamera mit Zusatz versehen wurde (z.B. "0@960,720"), wieder in int(0) wandeln!
            if raw_source.isdigit() or (raw_source.startswith('-') and raw_source[1:].isdigit()):
                self.cam_index = int(raw_source)
            else:
                self.cam_index = raw_source

        self.is_window_capture = self.capture_mode is not None

        # Unterscheidung: Physische USB-Kamera (int) vs. Stream/Videodatei (str)
        self.is_stream_or_file = isinstance(self.cam_index, str) and not self.is_window_capture
        self.is_local_file = self.is_stream_or_file and os.path.isfile(self.cam_index)

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

    def _post_process_frame(self, frame, apply_crop=True):
        """
        Wendet für ALLE Kameraquellen zuerst die Format-Entzerrung (@Breite,Höhe)
        und DANACH den Vorab-Zuschnitt (|top,bottom,left,right) an.
        """
        if frame is None:
            return None

        # 1. ZUERST: Seitenverhältnis / Auflösung korrigieren (@Breite,Höhe)
        if self.win_resize is not None:
            frame = cv2.resize(frame, self.win_resize, interpolation=cv2.INTER_AREA)

        # 2. DANACH: Ränder auf dem bereits entzerrten Bild abschneiden (|top,bottom,left,right)
        if apply_crop and self.win_offsets != (0, 0, 0, 0):
            h, w = frame.shape[:2]
            off_t, off_b, off_l, off_r = self.win_offsets
            y1 = max(0, off_t)
            y2 = max(0, h - off_b)
            x1 = max(0, off_l)
            x2 = max(0, w - off_r)
            if y2 > y1 and x2 > x1:
                frame = frame[y1:y2, x1:x2]

        return frame

    def _resolve_hwnd(self):
        """Sucht das Fenster-Handle (HWND) und cacht es, um EnumWindows-Spam zu vermeiden."""
        if WIN32_AVAILABLE and self._cached_hwnd:
            if win32gui.IsWindow(self._cached_hwnd):
                return self._cached_hwnd
            self._cached_hwnd = None

        if not GW_AVAILABLE:
            return None
        try:
            wins = gw.getWindowsWithTitle(self.win_title)
            if wins:
                self._cached_hwnd = wins[0]._hWnd
                return self._cached_hwnd
        except Exception:
            pass
        return None

    def _get_window_bbox(self):
        """Ermittelt live die aktuellen Bildschirmkoordinaten des Zielfensters für MSS."""
        hwnd = self._resolve_hwnd()
        if not hwnd:
            return None

        try:
            if WIN32_AVAILABLE:
                if win32gui.IsIconic(hwnd):
                    return None
                left, top, right, bot = win32gui.GetWindowRect(hwnd)
                win_w = right - left
                win_h = bot - top
            else:
                wins = gw.getWindowsWithTitle(self.win_title)
                if not wins or wins[0].isMinimized:
                    return None
                left, top, win_w, win_h = wins[0].left, wins[0].top, wins[0].width, wins[0].height
        except Exception:
            self._cached_hwnd = None
            return None

        # WICHTIG: Wenn @Resize aktiv ist, müssen wir erst das VOLLE Fenster greifen,
        # es auf @Breite,Höhe entzerren und dürfen erst DANACH in _post_process_frame zuschneiden!
        if self.win_resize is not None:
            off_t, off_b, off_l, off_r = (0, 0, 0, 0)
        else:
            off_t, off_b, off_l, off_r = self.win_offsets

        c_top = top + off_t
        c_left = left + off_l
        c_width = win_w - off_l - off_r
        c_height = win_h - off_t - off_b

        if c_width <= 10 or c_height <= 10:
            return None

        return {"top": int(c_top), "left": int(c_left), "width": int(c_width), "height": int(c_height)}

    def _grab_win32_frame(self):
        """Liest den Fensterinhalt via PrintWindow aus (funktioniert auch bei verdecktem Fenster)."""
        if not WIN32_AVAILABLE:
            return None
        hwnd = self._resolve_hwnd()
        if not hwnd:
            return None

        try:
            if win32gui.IsIconic(hwnd):
                return None
            left, top, right, bot = win32gui.GetWindowRect(hwnd)
        except Exception:
            self._cached_hwnd = None
            return None

        w = right - left
        h = bot - top
        if w <= 10 or h <= 10:
            return None

        hwndDC = None
        mfcDC = None
        saveDC = None
        saveBitMap = None

        try:
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
            saveDC.SelectObject(saveBitMap)

            # Flag 2 = PW_RENDERFULLCONTENT (zwingt DirectComposition zum Zeichnen)
            #res = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
            res = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)
            if res == 0:
                ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)

            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
            frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            # Erst @Resize, danach |Crop!
            frame = self._post_process_frame(frame, apply_crop=True)
            return frame.copy()

        except Exception:
            return None
        finally:
            if saveBitMap:
                try:
                    win32gui.DeleteObject(saveBitMap.GetHandle())
                except Exception:
                    pass
            if saveDC:
                try:
                    saveDC.DeleteDC()
                except Exception:
                    pass
            if mfcDC:
                try:
                    mfcDC.DeleteDC()
                except Exception:
                    pass
            if hwndDC:
                try:
                    win32gui.ReleaseDC(hwnd, hwndDC)
                except Exception:
                    pass

    def start(self):
        """Öffnet die Kamera anhand der dynamischen Vorgaben aus der config.ini"""
        if self.is_window_capture:
            if not GW_AVAILABLE:
                self.log("SYSTEM", f"Kamera {self.name} -> ⚠️ FEHLER: Bitte 'pip install pygetwindow' ausführen!", True)
                return False

            if self.capture_mode == "MSS":
                if not MSS_AVAILABLE:
                    self.log("SYSTEM", f"Kamera {self.name} -> ⚠️ FEHLER: Bitte 'pip install mss' ausführen!", True)
                    return False

                bbox = self._get_window_bbox()
                if not bbox:
                    self.log("SYSTEM", f"Kamera {self.name} -> ⚠️ FEHLER: Fenster '{self.win_title}' nicht gefunden oder minimiert!", True)
                    return False

                if self.win_resize:
                    rw, rh = self.win_resize
                    off_t, off_b, off_l, off_r = self.win_offsets
                    self.actual_w = max(1, rw - off_l - off_r)
                    self.actual_h = max(1, rh - off_t - off_b)
                else:
                    self.actual_w = bbox["width"]
                    self.actual_h = bbox["height"]
                self.actual_codec = "WIN_MSS"

            elif self.capture_mode == "WIN32":
                if not WIN32_AVAILABLE:
                    self.log("SYSTEM", f"Kamera {self.name} -> ⚠️ FEHLER: Bitte 'pip install pywin32' ausführen!", True)
                    return False

                frame = self._grab_win32_frame()
                if frame is None:
                    self.log("SYSTEM", f"Kamera {self.name} -> ⚠️ FEHLER: WIN32-Fenster '{self.win_title}' nicht gefunden oder minimiert!", True)
                    return False

                self.actual_h, self.actual_w = frame.shape[:2]
                self.latest_frame = frame
                self.new_frame_available = True
                self.actual_codec = "WIN_32"

            self.actual_fps = self.fps_target if self.fps_target > 0 else 30
            self.log("SYSTEM", f"Kamera {self.name} ({self.actual_codec} '{self.win_title}') -> {self.actual_w}x{self.actual_h} | FPS-Ziel: {self.actual_fps}", True)

            self.running = True
            self.thread = threading.Thread(target=self._update, daemon=True)
            self.thread.start()
            return True

        # --- Reguläre Kamera- / Stream- / Datei-Initialisierung ---
        if self.is_stream_or_file:
            backends_to_try = [cv2.CAP_ANY]
        else:
            if platform.system() != 'Windows':
                backends_to_try = [cv2.CAP_ANY]
            else:
                if self.backend_str == 'MSMF':
                    backends_to_try = [cv2.CAP_MSMF]
                elif self.backend_str == 'DSHOW':
                    backends_to_try = [cv2.CAP_DSHOW]
                else: # AUTO
                    backends_to_try = [cv2.CAP_MSMF, cv2.CAP_DSHOW]
        
        for current_backend in backends_to_try:
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
                self.cap = cv2.VideoCapture(self.cam_index, current_backend)
                
            if not self.cap.isOpened():
                continue

            if self.is_stream_or_file:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            elif self.init_modus == 'POST':
                if self.codec_str != 'AUTO' and self.codec_str != 'NONE':
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.codec_str))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_FPS, self.fps_target)

            self.cap.grab()
            ret, first_frame = self.cap.retrieve()
            
            if ret and first_frame is not None:
                first_frame = self._post_process_frame(first_frame, apply_crop=True)
                self.actual_h, self.actual_w = first_frame.shape[:2]
                self.latest_frame = first_frame
                self.new_frame_available = True
            else:
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
        except Exception:
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
        """Setzt die Belichtung zur Laufzeit (wird bei Streams/Dateien/Fenstern automatisch übersprungen)."""
        if self.is_window_capture or self.is_stream_or_file or not self.cap or not self.cap.isOpened() or belichtung_str.strip().lower() == 'standard':
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
        """Der Worker-Thread: Liest Bilder aus (für MSS, WIN32, lokale Videos oder Hardware-Kameras)."""
        if self.is_window_capture:
            target_fps = self.fps_target if (self.fps_target and 0 < self.fps_target <= 120) else 30.0
            frame_delay = 1.0 / target_fps

            if self.capture_mode == "MSS":
                with mss.mss() as sct:
                    while self.running:
                        t_start = time.perf_counter()
                        bbox = self._get_window_bbox()
                        if bbox and self.running:
                            try:
                                raw_img = np.array(sct.grab(bbox))
                                frame = cv2.cvtColor(raw_img, cv2.COLOR_BGRA2BGR)
                                # Wenn win_resize aktiv war, hat _get_window_bbox noch NICHT gecroppt -> jetzt nachholen!
                                frame = self._post_process_frame(frame, apply_crop=(self.win_resize is not None))
                                with self.lock:
                                    self.latest_frame = frame
                                    self.new_frame_available = True
                            except Exception:
                                pass
                        else:
                            time.sleep(0.05)

                        elapsed = time.perf_counter() - t_start
                        if elapsed < frame_delay and self.running:
                            time.sleep(frame_delay - elapsed)

            elif self.capture_mode == "WIN32":
                while self.running:
                    t_start = time.perf_counter()
                    frame = self._grab_win32_frame()
                    if frame is not None and self.running:
                        with self.lock:
                            self.latest_frame = frame
                            self.new_frame_available = True
                    else:
                        time.sleep(0.05)

                    elapsed = time.perf_counter() - t_start
                    if elapsed < frame_delay and self.running:
                        time.sleep(frame_delay - elapsed)
            return

        # --- Reguläre Schleife für VideoCapture (USB, MP4, RTSP) ---
        file_delay = 0.0
        if self.is_local_file:
            fps = self.actual_fps if (self.actual_fps and 0 < self.actual_fps < 120) else (self.fps_target if self.fps_target > 0 else 30.0)
            file_delay = 1.0 / fps

        while self.running:
            if self.playback_paused and self.is_local_file:
                time.sleep(0.05)
                continue
                
            t_start = time.perf_counter()
            ret, frame = self.cap.read()
            
            if ret:
                frame = self._post_process_frame(frame, apply_crop=True)
                with self.lock:
                    self.latest_frame = frame
                    self.new_frame_available = True
                if self.is_local_file and file_delay > 0:
                    elapsed = time.perf_counter() - t_start
                    if elapsed < file_delay and self.running:
                        time.sleep(file_delay - elapsed)
            else:
                if self.is_local_file:
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
        """Beendet den Thread sicher ohne GUI-Deadlock und gibt die Hardware frei."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass