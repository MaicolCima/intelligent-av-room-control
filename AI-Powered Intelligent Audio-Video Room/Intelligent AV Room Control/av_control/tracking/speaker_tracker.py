import threading
import time

from av_control.core.events import log
from av_control.core.metrics import M
from av_control.tracking.detectors import (FaceDetectorYuNet, PersonDetectorYOLO, create_csrt, body_from_face, head_from_body)
from av_control.tracking.pid import PID, HysteresisAxis
from av_control.tracking.video import VideoStreamReader

MAX_JUMP = 0.30        
JUMP_CONFIRM = 2       
MAX_CSRT_FAILS = 90
YOLO_EVERY_S = 0.20


def _jump(c, o, w, h):
    return 0.0 if o is None else (((c[0] - o[0]) / w) ** 2 + ((c[1] - o[1]) / h) ** 2) ** 0.5


class SpeakerTracker:
    def __init__(self, cfg: dict, paths: dict, camera, beam_provider=None, beam_mover=None, on_locked=None, on_state=None):
        self.cfg, self.cam = cfg, camera
        self.t = cfg["tracking"]
        self.rtsp = cfg["camera"]["rtsp_url"]
        self.settle = cfg["camera"].get("settle_time_s", 2.0)
        self.beam_grace = self.t.get("beam_grace_s", 2.5)
        self.beam_fresh = cfg.get("beam", {}).get("hint_max_age_s", 5.0)
        self.beam_min_delta = cfg.get("beam", {}).get("hysteresis_deg", 10)
        self._init_rot, self._init_wait = None, 0.0
        self.beam_provider = beam_provider      
        self.on_locked = on_locked              
        self.beam_mover = beam_mover            
        self.on_state = on_state
        self.face = FaceDetectorYuNet(paths["yunet_model"])
        self.yolo = PersonDetectorYOLO(paths["yolo_model"], self.t.get("enable_yolo_fallback", True))
        self._thread = None
        self._stop = threading.Event()
        self.active = False

    def start(self, initial_rot=None, wait_s=0.0):
        """initial_rot/wait_s: se il Controller ha gia' girato la camera verso il beam, aspetto che arrivi."""
        if self.active:
            return
        self._init_rot, self._init_wait = initial_rot, wait_s
        self._stop.clear()
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="tracker")
        self._thread.start()

    def stop(self):
        if not self.active:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.active = False
        self.cam.stop()

    def _run(self):
        vmax, vmin = self.t["max_visca_speed"], self.t["min_visca_speed"]
        ty = self.t.get("center_target_y", 0.30)
        home_s = self.t["search_to_home_timeout_s"]
        pid_p, pid_t = PID(3.0, 0.0, 1.0, vmax), PID(2.2, 0.0, 0.8, vmax)
        ax_p, ax_t = HysteresisAxis(0.015, 0.040), HysteresisAxis(0.020, 0.050)

        def clamp(v):
            v = int(round(v))
            return 0 if v == 0 else (max(vmin, min(vmax, abs(v))) * (1 if v > 0 else -1))

        reader = VideoStreamReader(self.rtsp)
        while reader.read() is None and not self._stop.is_set():
            time.sleep(0.1)
        log("TRACK", "tracking attivo")

        csrt, fails = None, 0
        last_c = smooth = None
        pend_c, pend_n = None, 0
        lost_since = time.time() + self._init_wait
        home_sent = False
        last_yolo = 0.0
        resume_at = time.time() + self._init_wait
        applied_rot = self._init_rot
        lock_start, last_learn = None, 0.0
        beam_retry_at = 0.0
        last_t = time.time()
        fps_t0, fps_n0 = time.time(), reader.n_frames

        while not self._stop.is_set():
            frame = reader.read()
            if frame is None:
                time.sleep(0.01)
                continue
            now = time.time()
            dt, last_t = now - last_t, now
            t_loop = time.perf_counter()
            if now - fps_t0 >= 2.0:             
                M.record("stream_fps", (reader.n_frames - fps_n0) / (now - fps_t0), echo=False)
                fps_t0, fps_n0 = now, reader.n_frames
            h, w = frame.shape[:2]

            if now < resume_at:                
                time.sleep(0.03)
                continue

            bbox, is_face = None, False
            with M.timer("yunet_ms", echo=False):
                faces = self.face.detect(frame)
            if faces:
                if last_c is None:
                    bbox = max(faces, key=lambda f: f[2] * f[3])
                else:
                    bbox = min(faces, key=lambda f: _jump((f[0] + f[2] / 2, f[1] + f[3] / 2), last_c, w, h))
                is_face = True
                if csrt is None or fails > 0:
                    try:
                        csrt = create_csrt()
                        csrt.init(frame, body_from_face(bbox, w, h))
                    except Exception:
                        csrt = None
                fails = 0
            elif csrt is not None:
                with M.timer("csrt_ms", echo=False):
                    ok, bb = csrt.update(frame)
                if ok:
                    bbox = head_from_body(tuple(int(v) for v in bb))
                    fails = 0
                else:
                    fails += 1
                    if fails > MAX_CSRT_FAILS:
                        csrt = None
            if bbox is None and self.yolo.model is not None and last_c is not None \
                    and now - last_yolo > YOLO_EVERY_S:
                last_yolo = now
                with M.timer("yolo_ms", echo=False):
                    persons = self.yolo.detect(frame)
                maxd = 0.35
                cand = [p for p in persons if _jump((p[0] + p[2] / 2, p[1] + p[3] / 2), last_c, w, h) <= maxd]
                if cand:
                    bbox = head_from_body(min(cand, key=lambda p: _jump((p[0] + p[2] / 2, p[1] + p[3] / 2), last_c, w, h)))

            if bbox is not None:
                c = (bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2)
                if _jump(c, last_c, w, h) > MAX_JUMP:
                    if pend_c is not None and _jump(c, pend_c, w, h) < 0.08:
                        pend_n += 1
                    else:
                        pend_c, pend_n = c, 1
                    if pend_n >= JUMP_CONFIRM:
                        pend_c, pend_n = None, 0
                    else:
                        bbox = None
                else:
                    pend_c, pend_n = None, 0

            if bbox is not None:
                c = (bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2)
                last_c = c
                smooth = c if smooth is None else (0.18 * c[0] + 0.82 * smooth[0], 0.18 * c[1] + 0.82 * smooth[1])
                ex, ey = smooth[0] / w - 0.5, smooth[1] / h - ty
                ps = clamp(pid_p.update(ex, dt)) if ax_p.should_move(abs(ex)) else 0
                ts = clamp(pid_t.update(ey, dt)) if ax_t.should_move(abs(ey)) else 0
                if ps == 0:
                    pid_p.reset()
                if ts == 0:
                    pid_t.reset()
                self.cam.pan_tilt_drive(ps, ts)
                M.record("loop_ms", (time.perf_counter() - t_loop) * 1e3, echo=False)
                M.record("track_err", 0.0, echo=False, ex=round(ex, 4), ey=round(ey, 4), ps=ps, ts=ts)
                if is_face and len(faces) == 1 and abs(ex) < 0.06 and abs(ey) < 0.08 and ps == 0 and ts == 0:
                    lock_start = lock_start or now
                    if self.on_locked and now - lock_start >= 3.0 and now - last_learn >= 5.0:
                        last_learn = now
                        self.on_locked()
                else:
                    lock_start = None
                lost_since, home_sent = now, False
                applied_rot = None       
                continue

            pid_p.reset(); pid_t.reset()
            self.cam.stop()
            lost = now - lost_since
            rot, rot_ts = self.beam_provider() if self.beam_provider else (None, 0.0)
            usable = False
            if rot is not None and (now - rot_ts) <= self.beam_fresh:      
                usable = applied_rot is None or abs((rot - applied_rot + 180.0) % 360.0 - 180.0) > self.beam_min_delta
            if usable and not home_sent and lost >= self.beam_grace and self.beam_mover and now >= beam_retry_at:
                if self.beam_mover(rot):
                    applied_rot = rot
                    log("TRACK", f"bersaglio perso da {lost:.1f}s: mi giro verso il beam ({rot:.0f}°)")
                    csrt, last_c, smooth = None, None, None
                    lost_since = now
                    resume_at = now + self.settle
                    continue
                beam_retry_at = now + 5.0          
            if lost > home_s and not home_sent:
                log("TRACK", "nessuno trovato: torno a home (emergenza)")
                self.cam.recall_preset("home")
                csrt, last_c, smooth, home_sent = None, None, None, True
                resume_at = now + self.settle
            time.sleep(0.02)

        reader.stop()
        log("TRACK", "tracking fermato")