"""Spring-damped slider model, shared by the music page and the settings page.

The music page's seek and volume bars and the settings page's frosted-glass
level control all ride the same physics: the value the user picked is `target`,
the value that is drawn is `visual`, and `visual` chases it with a sticky,
slightly overshooting spring that also bounces off the two ends. Keeping the
model here (rather than inside `toy_page.py`) is what makes "same feel as the
music page's progress bar" a fact rather than a copy that can drift.
"""


class ElasticSlider:
    """A value slider with spring-damped visual follow-through and wall bounce.

    `drag_damping` is the one knob callers tune. Left at None, dragging uses the
    music page's law -- the faster the drag, the looser the spring, so a flick
    sends the fill past its stop and it springs back. A control whose handle must
    not fly past its ends can pass a fixed damping instead: lower is more
    responsive (the handle keeps up with the pointer) and higher is more viscous,
    with ~0.775 being critical for this stiffness, i.e. the point where the
    overshoot stops.
    """

    def __init__(self, value: float = 0.0, drag_damping: float = None) -> None:
        self.target = value
        self.visual = value
        self.vel = 0.0
        self.dragging = False
        self.hovered = False
        self.drag_damping = drag_damping
        self._prev_target = value
        self.speed = 0.0
        self.wall_impact = 0.0
        self.wall_side = 0  # -1 = left wall, 1 = right wall
        # Hover/drag growth, 0 = resting thickness, 1 = fully expanded.
        self.expand = 0.0
        self.expand_vel = 0.0

    def set_target(self, value: float) -> None:
        self._prev_target = self.target
        self.target = max(0.0, min(1.0, value))
        self.speed = abs(self.target - self._prev_target)

    def update(self) -> None:
        # Heavier damping for a sticky, QQ-candy-like feel (damping ~0.775 is
        # critical for this stiffness: above it the value stops overshooting).
        stiffness = 0.15
        damping = 0.55
        if self.dragging:
            if self.drag_damping is None:
                damping = max(0.30, 0.80 - self.speed * 3.0)
            else:
                damping = self.drag_damping

        force = (self.target - self.visual) * stiffness
        self.vel += force - self.vel * damping
        self.visual += self.vel

        # Grow/shrink toward the hovered thickness with a light spring, so the
        # bar eases wider instead of snapping and settles with a tiny bounce.
        # (~110 ms to 90%, ~2.8% overshoot.)
        expand_target = 1.0 if (self.hovered or self.dragging) else 0.0
        self.expand_vel += (
            (expand_target - self.expand) * 0.10 - self.expand_vel * 0.42
        )
        self.expand += self.expand_vel
        self.expand = max(0.0, min(1.2, self.expand))

        # Stronger soft walls: the border stretches with the fill but pulls it
        # back before it overshoots too far.
        self.wall_impact = 0.0
        self.wall_side = 0
        if self.visual < 0.0:
            penetration = -self.visual
            self.vel += penetration * 0.45
            self.vel *= 0.55
            self.wall_impact = penetration
            self.wall_side = -1
        elif self.visual > 1.0:
            penetration = self.visual - 1.0
            self.vel -= penetration * 0.45
            self.vel *= 0.55
            self.wall_impact = penetration
            self.wall_side = 1

    def settled(self) -> bool:
        """True when nothing would change any more, so frames can stop.

        Used by callers that drive `update()` from their own timer: a page that
        only animates on demand must not keep a 16 ms timer alive at rest.
        """
        expand_target = 1.0 if (self.hovered or self.dragging) else 0.0
        return (
            abs(self.target - self.visual) < 0.002
            and abs(self.vel) < 0.002
            and abs(expand_target - self.expand) < 0.002
            and abs(self.expand_vel) < 0.002
        )
