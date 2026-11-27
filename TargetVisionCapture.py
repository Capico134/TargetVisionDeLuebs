import cv2
import threading
import time
import os
from datetime import datetime
from flask import Flask, Response, render_template_string

class TargetVisionCapture:
    def __init__(self, config, log_callback=None):
        self.config = config
        self.log = log_callback
        self.lock = threading.Lock()
        
        # Die Synergie: Ein einziger RAM-Puffer für Stream UND MP4-Aufnahme
        self.current_gui_frame = None
        
        # =========================================================
        # 1. STREAMING MODUL
        # =========================================================
        self.stream_active = config.getboolean('Anzeige', 'live_stream', fallback=False)
        if self.stream_active:
            self.stream_fps = config.getint('Anzeige', 'live_stream_fps', fallback=10)
            self.stream_port = config.getint('Anzeige', 'live_stream_port', fallback=8080)
            
            self.app = Flask(__name__)
            self._setup_routes()
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            
            if self.log:
                self.log("SYSTEM", f"🌐 Live-Stream gestartet auf Port {self.stream_port} ({self.stream_fps} FPS)")

        # =========================================================
        # 2. RECORDING MODUL (Platzhalter für den nächsten Schritt)
        # =========================================================
        self.is_recording_gui = False
        self.video_writer = None
        self.record_dim = (0, 0)
        # self.fps_limit = config.getint('Timing', 'fps_limit', fallback=30)

    def update_gui_frame(self, frame):
        """
        Der zentrale Flaschenhals: Die Hauptschleife ruft diese Funktion jeden Frame auf.
        Hier werden Stream und Aufzeichnung synchron gefüttert.
        """
        if frame is None:
            return
            
        with self.lock:
            self.current_gui_frame = frame.copy()
            
        # Synergie-Beispiel für später: 
        # Wenn aufgenommen wird, greifen wir direkt hier das Bild ab.
        # if self.is_recording_gui and self.video_writer is not None:
        #     self.video_writer.write(self.current_gui_frame)

    # =========================================================
    # INTERNE STREAMING FUNKTIONEN (Flask)
    # =========================================================
    def _generate_mjpeg(self):
        delay = 1.0 / self.stream_fps if self.stream_fps > 0 else 0.1
        
        while True:
            start_time = time.perf_counter()
            
            with self.lock:
                frame = self.current_gui_frame
                
            if frame is not None:
                ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            
            elapsed = time.perf_counter() - start_time
            if elapsed < delay:
                time.sleep(delay - elapsed)

    def _setup_routes(self):
        @self.app.route('/stream')
        def video_feed():
            return Response(self._generate_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')
            
        @self.app.route('/manifest.json')
        def manifest():
            manifest_json = '''{
                "name": "TargetVision Live",
                "short_name": "TargetVision",
                "start_url": "/",
                "display": "fullscreen",
                "background_color": "#111111",
                "theme_color": "#111111"
            }'''
            return Response(manifest_json, mimetype='application/json')
            
        @self.app.route('/')
        def index():
            html = """
            <!DOCTYPE html>
            <html>
                <head>
                    <title>TargetVision Live</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                    <link rel="manifest" href="/manifest.json">
                    <meta name="theme-color" content="#111111">
                    <meta name="mobile-web-app-capable" content="yes">
                    <meta name="apple-mobile-web-app-capable" content="yes">
                    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
                    <style>
                        body { background-color: #111; color: white; margin: 0; padding: 0; text-align: center; overflow: hidden; display: flex; align-items: center; justify-content: center; height: 100vh; touch-action: manipulation; }
                        img { max-width: 100%; max-height: 100%; object-fit: contain; cursor: pointer; }
                    </style>
                </head>
                <body>
                    <img src="/stream" id="stream" onclick="toggleFullScreen()" title="Tippen für Vollbild" />
                    <script>
                        function toggleFullScreen() {
                            if (!document.fullscreenElement) {
                                document.documentElement.requestFullscreen().catch(err => {
                                    console.log(`Fehler: ${err.message}`);
                                });
                            } else {
                                if (document.exitFullscreen) {
                                    document.exitFullscreen();
                                }
                            }
                        }
                    </script>
                </body>
            </html>
            """
            return render_template_string(html)

    def _run_server(self):
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        self.app.run(host='0.0.0.0', port=self.stream_port, debug=False, use_reloader=False)

    # =========================================================
    # INTERNE RECORDING FUNKTIONEN (Für später)
    # =========================================================
    # def toggle_gui_recording(self):
    #    ...