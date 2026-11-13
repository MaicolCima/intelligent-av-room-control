import os

import cv2

from av_control.core.events import log


class FaceDetectorYuNet:
    def __init__(self, model_path: str, score=0.75):
        self.score, self.det = score, None
        if not os.path.exists(model_path):
            log("DET", f"YuNet non trovato: {model_path}")
            return
        self.det = cv2.FaceDetectorYN.create(model_path, "", (320, 320), score_threshold=score,
                                             nms_threshold=0.3, top_k=5000)

    def detect(self, frame):
        if self.det is None:
            return []
        h, w = frame.shape[:2]
        self.det.setInputSize((w, h))
        _, res = self.det.detect(frame)
        out = []
        if res is not None:
            for f in res:
                x, y, bw, bh = map(int, f[:4])
                if bw > 0 and bh > 0:
                    out.append((x, y, bw, bh))
        return out


class PersonDetectorYOLO:
    def __init__(self, model_path: str, enabled=True, conf=0.45):
        self.model, self.conf = None, conf
        if not enabled:
            return
        try:
            from ultralytics import YOLO
            self.model = YOLO(model_path)
            log("DET", "YOLOv8n caricato (fallback persona attivo)")
        except Exception as e:
            log("DET", f"YOLO non disponibile ({e}): solo YuNet+CSRT")

    def detect(self, frame):
        if self.model is None:
            return []
        r = self.model.predict(frame, classes=[0], conf=self.conf, verbose=False)
        out = []
        if r and r[0].boxes is not None:
            for b in r[0].boxes:
                x1, y1, x2, y2 = b.xyxy[0].tolist()
                out.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1)))
        return out


def create_csrt():
    return cv2.TrackerCSRT_create() if hasattr(cv2, "TrackerCSRT_create") else cv2.legacy.TrackerCSRT_create()


def body_from_face(face, fw, fh, wm=2.2, hm=4.5):
    x, y, bw, bh = face
    nw, nh = bw * wm, bh * hm
    nx = max(0.0, min(x + bw / 2 - nw / 2, fw - nw))
    ny = max(0.0, min(float(y), fh - nh))
    return (int(nx), int(ny), int(min(nw, fw - nx)), int(min(nh, fh - ny)))


def head_from_body(body, ratio=0.22):
    x, y, bw, bh = body
    return (x, y, bw, max(1, int(bh * ratio)))
