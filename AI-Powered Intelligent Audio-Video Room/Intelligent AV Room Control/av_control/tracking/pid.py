class PID:
    def __init__(self, kp, ki, kd, limit, d_alpha=0.35):
        self.kp, self.ki, self.kd, self.limit, self.a = kp, ki, kd, limit, d_alpha
        self.reset()

    def reset(self):
        self.i = self.prev = self.d = 0.0

    def update(self, err, dt):
        dt = max(1 / 60, min(0.12, dt))
        self.i = max(-self.limit, min(self.limit, self.i + err * dt))
        self.d = self.a * ((err - self.prev) / dt) + (1 - self.a) * self.d
        self.prev = err
        return max(-self.limit, min(self.limit, self.kp * err + self.ki * self.i + self.kd * self.d))


class HysteresisAxis:
    def __init__(self, enter, exit_):
        self.enter, self.exit, self.active = enter, exit_, False

    def should_move(self, e):
        if self.active:
            if e < self.exit:
                self.active = False
        elif e > self.enter:
            self.active = True
        return self.active
