"""Identidad anatómica de los diez dedos a partir de los landmarks ya detectados.

No ejecuta un modelo, no asigna notas y no decide si un dedo está pulsando.
La identidad sale del índice oficial del punto y de la mano Left o Right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fingermelody.vision.hand_tracker import HandFrame, TrackedHand

PRESS_NOT_EVALUATED = "not_evaluated"
STATUS_DETECTED = "Detectado"
STATUS_UNTRACKED = "Sin seguimiento"
STATUS_ABSENT = "Ausente"

_HANDS = ("Left", "Right")


@dataclass(frozen=True)
class FingerSpec:
    """Definición anatómica de un dedo. El orden de la tupla es el orden estable."""

    name: str
    display_name: str
    code: str
    joints: tuple[tuple[int, str], ...]

    @property
    def indices(self) -> tuple[int, ...]:
        return tuple(index for index, _role in self.joints)

    @property
    def tip_index(self) -> int:
        return self.joints[-1][0]


FINGER_SPECS: tuple[FingerSpec, ...] = (
    FingerSpec("thumb", "Pulgar", "THUMB", ((1, "CMC"), (2, "MCP"), (3, "IP"), (4, "TIP"))),
    FingerSpec("index", "Índice", "INDEX", ((5, "MCP"), (6, "PIP"), (7, "DIP"), (8, "TIP"))),
    FingerSpec("middle", "Medio", "MIDDLE", ((9, "MCP"), (10, "PIP"), (11, "DIP"), (12, "TIP"))),
    FingerSpec("ring", "Anular", "RING", ((13, "MCP"), (14, "PIP"), (15, "DIP"), (16, "TIP"))),
    FingerSpec("pinky", "Meñique", "PINKY", ((17, "MCP"), (18, "PIP"), (19, "DIP"), (20, "TIP"))),
)


@dataclass(frozen=True)
class FingerJoint:
    """Una articulación de un dedo, con su índice oficial de MediaPipe."""

    index: int
    role: str
    normalized: tuple[float, float, float] | None
    pixel: tuple[int, int] | None


@dataclass(frozen=True)
class TrackedFinger:
    """Un dedo identificado. Los campos de nota, pulsación e historial quedan reservados."""

    finger_id: str
    hand: str
    name: str
    display_name: str
    indices: tuple[int, ...]
    joints: tuple[FingerJoint, ...]
    tip_normalized: tuple[float, float, float] | None
    tip_pixel: tuple[int, int] | None
    tracked: bool
    note: str | None = None
    press_state: str = PRESS_NOT_EVALUATED
    movement_history: tuple[tuple[float, float], ...] = ()
    activation: str | None = None


@dataclass(frozen=True)
class FingerPanelLine:
    """Una fila del panel. Detectado no significa pulsado."""

    finger_id: str
    display_name: str
    status: str


@dataclass(frozen=True)
class FingerPanel:
    """Texto de seguimiento de las dos manos. Inactivo mientras la cámara no reconoce."""

    active: bool = False
    left_lines: tuple[FingerPanelLine, ...] = ()
    right_lines: tuple[FingerPanelLine, ...] = ()

    @staticmethod
    def inactive() -> FingerPanel:
        return FingerPanel()


@dataclass(frozen=True)
class FingerObservation:
    """Dedos presentes en este fotograma y el panel completo de las dos manos."""

    fingers: tuple[TrackedFinger, ...]
    panel: FingerPanel


def finger_id(hand: str, spec: FingerSpec) -> str:
    """Identificador estable, independiente de la posición en pantalla."""
    return f"{hand.upper()}_{spec.code}"


def format_panel_column(
    title: str,
    lines: tuple[FingerPanelLine, ...],
    *,
    active: bool,
) -> str:
    """Texto de una columna del panel."""
    if not active:
        rows = [f"{spec.display_name} — —" for spec in FINGER_SPECS]
    elif not lines:
        rows = [f"{spec.display_name} — {STATUS_ABSENT}" for spec in FINGER_SPECS]
    else:
        rows = [f"{line.display_name} — {line.status}" for line in lines]
    return title + "\n" + "\n".join(rows)


class FingerDetector:
    """Asigna los cinco dedos de cada mano clasificada.

    Una instancia no guarda el fotograma anterior: si una mano desaparece,
    sus dedos dejan de salir en el resultado y la otra conserva sus ids.
    """

    def identify(self, frame: HandFrame) -> FingerObservation:
        grouped = _hands_by_label(frame.hands)
        present: list[TrackedFinger] = []
        columns: dict[str, tuple[FingerPanelLine, ...]] = {}
        for hand_label in _HANDS:
            hand = grouped.get(hand_label)
            if hand is None:
                columns[hand_label] = _absent_lines(hand_label)
                continue
            fingers = tuple(_finger_from_hand(hand_label, spec, hand) for spec in FINGER_SPECS)
            present.extend(fingers)
            columns[hand_label] = tuple(_line_for(finger) for finger in fingers)
        return FingerObservation(
            fingers=tuple(present),
            panel=FingerPanel(
                active=True,
                left_lines=columns["Left"],
                right_lines=columns["Right"],
            ),
        )


def _hands_by_label(hands: tuple[TrackedHand, ...]) -> dict[str, TrackedHand]:
    grouped: dict[str, TrackedHand] = {}
    for hand in hands:
        if hand.label in _HANDS and hand.label not in grouped:
            grouped[hand.label] = hand
    return grouped


def _finger_from_hand(hand_label: str, spec: FingerSpec, hand: TrackedHand) -> TrackedFinger:
    joints = tuple(_joint_from_hand(hand, index, role) for index, role in spec.joints)
    tip = joints[-1]
    tracked = all(
        joint.normalized is not None and joint.pixel is not None for joint in joints
    )
    return TrackedFinger(
        finger_id=finger_id(hand_label, spec),
        hand=hand_label,
        name=spec.name,
        display_name=spec.display_name,
        indices=spec.indices,
        joints=joints,
        tip_normalized=tip.normalized,
        tip_pixel=tip.pixel,
        tracked=tracked,
    )


def _joint_from_hand(hand: TrackedHand, index: int, role: str) -> FingerJoint:
    normalized = hand.normalized[index] if index < len(hand.normalized) else None
    pixel = hand.pixels[index] if index < len(hand.pixels) else None
    return FingerJoint(
        index=index,
        role=role,
        normalized=_as_normalized(normalized),
        pixel=_as_pixel(pixel),
    )


def _as_normalized(value) -> tuple[float, float, float] | None:
    if not isinstance(value, tuple) or len(value) < 2:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
        z = float(value[2]) if len(value) > 2 else 0.0
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(number) for number in (x, y, z)):
        return None
    return (x, y, z)


def _as_pixel(value) -> tuple[int, int] | None:
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    try:
        return (int(value[0]), int(value[1]))
    except (TypeError, ValueError):
        return None


def _absent_lines(hand_label: str) -> tuple[FingerPanelLine, ...]:
    return tuple(
        FingerPanelLine(
            finger_id=finger_id(hand_label, spec),
            display_name=spec.display_name,
            status=STATUS_ABSENT,
        )
        for spec in FINGER_SPECS
    )


def _line_for(finger: TrackedFinger) -> FingerPanelLine:
    status = STATUS_DETECTED if finger.tracked else STATUS_UNTRACKED
    return FingerPanelLine(
        finger_id=finger.finger_id,
        display_name=finger.display_name,
        status=status,
    )
