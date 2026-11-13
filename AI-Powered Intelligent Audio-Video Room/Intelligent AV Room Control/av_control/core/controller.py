import threading
import time

from av_control.core.events import log
from av_control.core.state_store import update_state


AUTO_MAX_RESIDUAL_DEG = 25.0   


def _diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


class Controller:
    def __init__(self, camera, tracker, beam_filter=None, beam_cfg=None, settle_s=2.0, panmap=None):
        self.cam, self.tracker, self.beam, self.panmap = camera, tracker, beam_filter, panmap
        cfg = beam_cfg or {}
        self.min_interval = float(cfg.get("min_switch_interval_s", 4.0))
        self.hint_max_age = float(cfg.get("hint_max_age_s", 5.0))
        self.min_delta = float(cfg.get("hysteresis_deg", 10))
        self.settle = settle_s
        self.mode = "IDLE"
        self._zone = None
        self._rot = None            
        self._zone_ts = 0.0
        self._applied_rot = None    
        self._cam_zone = None
        self._last_move = 0.0
        self._lock = threading.RLock()
        self._actions = {
            "track_start": self._track_start,
            "track_stop": self._track_stop,
            "follow_speaker": self._follow_speaker,
            "preset": self._preset,
            "beam_calibrate": self._beam_calibrate,
            "beam_clear": self._beam_clear,
        }


    def on_voice_command(self, cmd: dict):
        fn = self._actions.get(cmd.get("action"))
        if not fn:
            log("CTRL", f"azione sconosciuta: {cmd.get('action')}")
            return
        with self._lock:
            fn(cmd)

    def on_beam_sample(self, sample):
        if not self.beam:
            return
        zone = self.beam.feed(sample)
        if zone is None:
            return
        with self._lock:
            if self._zone is None or zone.name != self._zone.name:
                log("BEAM", f"parla in zona: {zone.name} (rot {sample.rotation:.0f}°, elev {sample.elevation})")
            self._zone, self._rot, self._zone_ts = zone, self.beam.rotation, time.time()
            if self.mode == "SPEAKER":
                self._speaker_follow()


    def beam_rotation(self, max_age=None):
        if self._rot is None:
            return None, None
        age = time.time() - self._zone_ts
        return (self._rot, age) if age <= (max_age or self.hint_max_age) else (None, None)

    def beam_hint_ts(self):
        return (self._rot, self._zone_ts) if self._rot is not None else (None, 0.0)

    def goto_rotation(self, rot: float) -> bool:
        if self.panmap is None or not self.panmap.ready:
            log("CTRL", "mappa mic->camera non calibrata: di' 'piero calibra' da 2 posizioni diverse")
            return False
        pan = self.panmap.pan_for(rot)
        log("CTRL", f"beam {rot:.0f}° -> pan {pan}")
        return self.cam.move_absolute(pan)

    def _speaker_follow(self):
        now = time.time()
        if now - self._last_move < self.min_interval or self._rot is None:
            return
        if self.panmap is not None and self.panmap.ready:
            if self._applied_rot is not None and _diff(self._rot, self._applied_rot) <= self.min_delta:
                return
            if self.goto_rotation(self._rot):
                self._applied_rot, self._last_move = self._rot, now
        elif self._zone is not None and self._zone.preset is not None and self._zone.name != self._cam_zone:
            self.cam.recall_preset(self._zone.preset)        # senza calibrazione: vecchio metodo a preset
            self._cam_zone, self._last_move = self._zone.name, now

    def _set_mode(self, m: str):
        self.mode = m
        log("CTRL", f"modalita': {m}")
        try:
            update_state({"mode": m, "tracking_enabled": m == "TRACK"})
        except Exception:
            pass

    def _stop_tracker(self):
        if self.tracker.active:
            self.tracker.stop()

    def _track_start(self, cmd):
        """1) capisce il beam e gira la camera  2) poi attiva il tracker."""
        self._cam_zone = self._applied_rot = None
        rot, age = self.beam_rotation()
        init_rot, wait = None, 0.0
        if rot is None:
            log("CTRL", "seguimi: nessun beam recente, parto dall'inquadratura attuale")
        else:
            log("CTRL", f"seguimi: il mic ti ha sentito a {rot:.0f}° ({age:.1f}s fa)")
            if self.goto_rotation(rot):
                init_rot, wait = rot, self.settle
        self._set_mode("TRACK")
        self.tracker.start(initial_rot=init_rot, wait_s=wait)

    def _track_stop(self, cmd):
        self._stop_tracker()
        self.cam.stop()
        self._cam_zone = self._applied_rot = None
        self._set_mode("IDLE")

    def _follow_speaker(self, cmd):
        self._stop_tracker()
        self._set_mode("SPEAKER")
        self._cam_zone = self._applied_rot = None
        self._last_move = 0.0
        self._speaker_follow()

    def _preset(self, cmd):
        self._stop_tracker()
        self._set_mode("PRESET")
        self._cam_zone = self._applied_rot = None
        self.cam.recall_preset(cmd["preset"])

    def _beam_calibrate(self, cmd):
        if self.panmap is None:
            return
        rot, age = self.beam_rotation(max_age=3.0)
        if rot is None:
            log("CALIB", "nessun beam recente: parla (restando fermo) e ripeti il comando")
            return
        pt = self.cam.get_pan_tilt()
        if pt is None:
            log("CALIB", "la camera NON risponde alla richiesta di posizione VISCA (81 09 06 12 FF): "
                         "il movimento assoluto non e' possibile con questa camera/porta")
            return
        self.panmap.add_point(rot, pt[0])

    def on_tracker_locked(self):
        if self.panmap is None:
            return
        rot, _ = self.beam_rotation(max_age=1.5)          
        if rot is None:
            return
        pt = self.cam.get_pan_tilt()
        if pt is None:
            return
        if self.panmap.ready and self.panmap.residual_deg(rot, pt[0]) > AUTO_MAX_RESIDUAL_DEG:
            log("CALIB", "campione automatico scartato (incoerente con la mappa: forse parla un altro)")
            return
        self.panmap.add_point(rot, pt[0])

    def _beam_clear(self, cmd):
        if self.panmap is not None:
            self.panmap.clear()