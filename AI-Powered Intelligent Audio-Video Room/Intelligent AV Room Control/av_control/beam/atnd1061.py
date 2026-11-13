import socket
import threading
import time

from av_control.beam.zones import parse_notice, BeamSample
from av_control.core.events import log

REQUEST = b"g_camera_control_notice O 0000 00 NC \r"


class ATND1061Listener:
    def __init__(self, cfg: dict, on_sample):
        self.cfg, self.on_sample = cfg, on_sample
        self._stop = threading.Event()
        self.last_sample: BeamSample | None = None

    def start(self):
        threading.Thread(target=self._udp, daemon=True, name="beam-udp").start()
        threading.Thread(target=self._tcp, daemon=True, name="beam-tcp").start()

    def stop(self):
        self._stop.set()

    def _tcp(self):
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.cfg["mic_ip"], self.cfg.get("tcp_port", 17300)), timeout=5) as s:
                    s.settimeout(2.0)
                    s.sendall(REQUEST)
                    log("BEAM", "TCP connesso al mic")
                    last_req = time.time()
                    while not self._stop.is_set():
                        try:
                            if not s.recv(4096):
                                break
                        except socket.timeout:
                            pass
                        if time.time() - last_req > 30:
                            s.sendall(REQUEST)
                            last_req = time.time()
            except OSError as e:
                log("BEAM", f"TCP: {e} (riprovo tra 3s)")
            time.sleep(3)

    def _udp(self):
        while not self._stop.is_set():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("", self.cfg.get("udp_port", 17000)))
                mreq = socket.inet_aton(self.cfg["multicast_group"]) + socket.inet_aton(self.cfg["local_ip"])
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                sock.settimeout(1.0)
                log("BEAM", f"UDP in ascolto su {self.cfg['multicast_group']}:{self.cfg.get('udp_port', 17000)}")
                while not self._stop.is_set():
                    try:
                        data, _ = sock.recvfrom(8192)
                    except socket.timeout:
                        continue
                    msg = data.decode("utf-8", errors="replace")
                    if "camera_control_notice" not in msg:
                        continue            # scarta level_meter_notice ecc. (sono 10 msg/s inutili)
                    s = parse_notice(msg)
                    if s:
                        if s.rotation is not None:
                            s.rotation = (s.rotation + self.cfg.get("rotation_offset_deg", 0)) % 360.0
                        if s.status:  
                            log("BEAM", f"raw: rot={s.rotation:.0f} elev={s.elevation}")
                        self.last_sample = s
                        self.on_sample(s)
            except OSError as e:
                log("BEAM", f"UDP errore: {e} - controlla local_ip/firewall (riprovo tra 3s)")
                time.sleep(3)
            finally:
                sock.close()
