import socket
import threading
import time

from av_control.core.events import log


class MinrrayVISCA:
    def __init__(self, ip: str, port: int, presets: dict, max_speed: int = 24):
        self.ip, self.port = ip, port
        self.presets = {k.lower(): int(v) for k, v in presets.items()}
        self.max_speed = max_speed
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._lock = threading.RLock()
        self._last_pt = (None, None)

    def _send(self, hex_cmd: str) -> None:
        try:
            with self._lock:
                self._sock.sendto(bytes.fromhex(hex_cmd), (self.ip, self.port))
        except Exception as e:
            log("CAM", f"errore VISCA: {e}")

    def pan_tilt_drive(self, pan: int, tilt: int, force: bool = False) -> None:
        if not force and (pan, tilt) == self._last_pt:
            return
        self._last_pt = (pan, tilt)
        pv, tv = min(abs(pan), self.max_speed), min(abs(tilt), self.max_speed)
        pd = 0x03 if pv == 0 else (0x02 if pan > 0 else 0x01)
        td = 0x03 if tv == 0 else (0x02 if tilt > 0 else 0x01)
        self._send(f"81010601{pv:02x}{tv:02x}0{pd:x}0{td:x}FF")

    def stop(self) -> None:
        self.pan_tilt_drive(0, 0, force=True)

    def recall_preset(self, preset) -> bool:
        if isinstance(preset, str) and not preset.isdigit():
            num = self.presets.get(preset.lower())
            if num is None:
                log("CAM", f"preset sconosciuto: {preset}")
                return False
        else:
            num = int(preset)
        self.stop()
        self._send(f"8101043f02{num:02x}FF")
        self._last_pt = (None, None)
        log("CAM", f"preset {preset} (n.{num}) richiamato")
        return True


    @staticmethod
    def _s16(n: int) -> int:
        return n - 0x10000 if n >= 0x8000 else n

    @staticmethod
    def _nibbles(v: int) -> str:
        return "".join(f"0{c}" for c in f"{v & 0xFFFF:04x}")

    def get_pan_tilt(self, timeout: float = 1.0):
        with self._lock:
            s = self._sock
            s.settimeout(0.0)
            try:                                   
                while True:
                    s.recv(512)
            except OSError:
                pass
            try:
                s.sendto(bytes.fromhex("81090612FF"), (self.ip, self.port))
            except OSError:
                return None
            end = time.time() + timeout
            while time.time() < end:
                s.settimeout(max(0.05, end - time.time()))
                try:
                    h = s.recv(512).hex()
                except OSError:
                    break
                i = h.find("9050")                 
                if i >= 0 and len(h) >= i + 20:
                    n = [int(h[i + 4 + 2 * k + 1], 16) for k in range(8)]
                    pan = self._s16(n[0] << 12 | n[1] << 8 | n[2] << 4 | n[3])
                    tilt = self._s16(n[4] << 12 | n[5] << 8 | n[6] << 4 | n[7])
                    return pan, tilt
            return None

    def move_absolute(self, pan: int, tilt=None, speed=None) -> bool:
        if tilt is None:
            pt = self.get_pan_tilt()
            if pt is None:
                log("CAM", "posizione non leggibile: movimento assoluto annullato")
                return False
            tilt = pt[1]
        sp = max(1, min(speed or self.max_speed, self.max_speed))
        self.stop()
        self._send(f"81010602{sp:02x}{min(sp, 20):02x}{self._nibbles(int(pan))}{self._nibbles(int(tilt))}FF")
        self._last_pt = (None, None)
        log("CAM", f"vado a pan={int(pan)} tilt={int(tilt)}")
        return True