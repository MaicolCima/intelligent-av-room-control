import threading
import time

import cv2

from av_control.core.events import log


class VideoStreamReader:
    STALL_TIMEOUT_S = 8.0

    def __init__(self, src: str):
        self.src = src
        self.frame = None
        self._lock = threading.Lock()
        self._stopped = False
        self.n_frames = 0                     
        self._open()
        self._last_good = time.time()
        self._t = threading.Thread(target=self._loop, daemon=True, name="rtsp")
        self._t.start()

    def _open(self):
        self.cap = cv2.VideoCapture(self.src)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def _loop(self):
        while not self._stopped:
            if not self.cap.isOpened():
                time.sleep(1)
                self.cap.release()
                self._open()
                continue
            ok, fr = self.cap.read()
            if not ok:
                if time.time() - self._last_good > self.STALL_TIMEOUT_S:
                    log("VIDEO", "stream RTSP bloccato: riconnessione")
                    self.cap.release()
                    self._open()
                    self._last_good = time.time()
                time.sleep(0.02)
                continue
            self._last_good = time.time()
            self.n_frames += 1
            with self._lock:
                self.frame = fr

    def read(self):
        with self._lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        self._stopped = True
        self._t.join(timeout=2)
        self.cap.release()
