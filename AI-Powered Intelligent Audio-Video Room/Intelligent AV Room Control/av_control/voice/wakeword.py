import json
import queue
import threading
import time

import sounddevice as sd
from vosk import Model, KaldiRecognizer, SetLogLevel

from av_control.core.events import log
from av_control.core.metrics import M
from av_control.voice.matcher import CommandMatcher, normalize

SetLogLevel(-1)


class VoiceListener:
    def __init__(self, model_path, wake_word, matcher: CommandMatcher, on_command,
                 wake_timeout_s=8.0, sample_rate=16000, on_wake=None, on_miss=None):
        self.model = Model(model_path)
        self.rec = KaldiRecognizer(self.model, sample_rate)
        self.wake = normalize(wake_word)
        self.matcher, self.on_command = matcher, on_command
        self.on_wake, self.on_miss = on_wake, on_miss
        self.timeout, self.rate = wake_timeout_s, sample_rate
        self._armed_until = 0.0
        self._last_part, self._last_part_t = "", None      
        self._stop = threading.Event()
        self._q: "queue.Queue[bytes]" = queue.Queue(maxsize=50)

    def _audio_cb(self, indata, frames, t, status):
        try:
            self._q.put_nowait(bytes(indata))
        except queue.Full:
            pass

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="voice").start()

    def stop(self):
        self._stop.set()

    def _arm(self):
        if time.time() > self._armed_until:
            log("VOICE", f"'{self.wake}' sentito: dimmi il comando...")
            if self.on_wake:
                self.on_wake()
        self._armed_until = time.time() + self.timeout

    def _armed(self) -> bool:
        return time.time() < self._armed_until

    def _after_wake(self, text: str) -> str:
        words = normalize(text).split()
        if self.wake in words:
            return " ".join(words[words.index(self.wake) + 1:])
        return " ".join(words)

    def _handle_final(self, text: str, dec_ms: float = 0.0):
        t_final = time.perf_counter()
        endpoint_ms = None if self._last_part_t is None else (t_final - self._last_part_t) * 1e3
        self._last_part, self._last_part_t = "", None
        text = normalize(text)
        if not text:
            return
        has_wake = self.wake in text.split()
        if not has_wake and not self._armed():
            return                                  
        cmd_text = self._after_wake(text)
        if not cmd_text:                           
            self._arm()
            return
        t0 = time.perf_counter()
        res = self.matcher.match(cmd_text)
        match_ms = (time.perf_counter() - t0) * 1e3
        self._armed_until = 0.0
        if res:
            cmd, score = res
            log("VOICE", f"'{cmd_text}' -> {cmd['name']} ({score:.0f}%)")
            t1 = time.perf_counter()
            self.on_command(cmd)
            disp_ms = (time.perf_counter() - t1) * 1e3
            if endpoint_ms is not None:
                M.record("voce_endpoint_ms", endpoint_ms, echo=False)
                M.record("voce_decode_ms", dec_ms, echo=False)
                M.record("matcher_ms", match_ms, echo=False)
                M.record("cmd_dispatch_ms", disp_ms, echo=False)
                M.record("voce_fine_frase_azione_ms", endpoint_ms + dec_ms + match_ms + disp_ms,
                         cmd=cmd["name"], score=round(score))
        else:
            log("VOICE", f"comando non riconosciuto: '{cmd_text}'")
            if self.on_miss:
                self.on_miss(cmd_text)

    def _run(self):
        while not self._stop.is_set():
            try:
                with sd.RawInputStream(samplerate=self.rate, blocksize=4000, dtype="int16",
                                       channels=1, callback=self._audio_cb):
                    log("VOICE", f"in ascolto (wake word: '{self.wake}')")
                    while not self._stop.is_set():
                        try:
                            data = self._q.get(timeout=0.5)
                        except queue.Empty:
                            continue
                        t0 = time.perf_counter()
                        fin = self.rec.AcceptWaveform(data)
                        dec_ms = (time.perf_counter() - t0) * 1e3
                        if fin:
                            self._handle_final(json.loads(self.rec.Result()).get("text", ""), dec_ms)
                        else:
                            part = normalize(json.loads(self.rec.PartialResult()).get("partial", ""))
                            if part and part != self._last_part:
                                self._last_part, self._last_part_t = part, time.perf_counter()
                            if self.wake in part.split():
                                self._arm()
            except Exception as e:
                log("VOICE", f"errore audio ({e}), riprovo tra 1s")
                time.sleep(1)
