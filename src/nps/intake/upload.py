"""Upload gate: no photo of a real person may enter the system.

Rules (decided 2026-11-11):
  face found                                   -> rejected
  larger person area without a face            -> a human decides
  only small person areas without a face       -> accepted (typically a hand)
  nothing found                                -> accepted
  detector fails, file unreadable, video too long -> rejected
Videos are checked frame by frame; the strictest result of any frame counts.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from nps.core.hashing import sha256_image
from nps.detectors import RTDETR, YUNET, models_dir

# A person box below this share of the image counts as "small".
SMALL_PERSON_AREA = 0.15
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
VIDEO_FRAME_INTERVAL_S = 0.5
VIDEO_MAX_SECONDS = 300


class UploadDecision(str, Enum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


_SEVERITY = {UploadDecision.ACCEPTED: 0, UploadDecision.NEEDS_REVIEW: 1, UploadDecision.REJECTED: 2}

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in pixels


@dataclass(frozen=True)
class UploadVerdict:
    decision: UploadDecision
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


class FaceDetector(Protocol):
    def faces(self, image: Image.Image) -> list[Box]: ...


class PersonDetector(Protocol):
    def persons(self, image: Image.Image) -> list[Box]: ...


class UploadGate(Protocol):
    name: str

    def check_image(self, image: Image.Image) -> UploadVerdict: ...

    def check_file(self, path: Path) -> UploadVerdict: ...


def _flatten(image: Image.Image) -> Image.Image:
    """Put cut-outs on white so transparent areas do not confuse the detectors."""
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


class YuNetFaceDetector:
    """YuNet finds faces of roughly 10 to 300 pixels, so several scales are tried."""

    SCALES = (1920, 960, 480, 240)

    def __init__(self, directory: Path | None = None, score_threshold: float = 0.6) -> None:
        self._directory = directory
        self._threshold = score_threshold
        self._model_path: str | None = None

    def faces(self, image: Image.Image) -> list[Box]:
        import cv2

        if self._model_path is None:
            folder = YUNET.verify(self._directory or models_dir())
            self._model_path = str(folder / next(iter(YUNET.files)))
        bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        longest = max(image.size)
        found: list[Box] = []
        factors = sorted({min(1.0, target / longest) for target in self.SCALES}, reverse=True)
        for factor in factors:
            width = max(16, round(image.width * factor))
            height = max(16, round(image.height * factor))
            resized = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)
            detector = cv2.FaceDetectorYN.create(
                self._model_path, "", (width, height), self._threshold, 0.3, 5000
            )
            _, faces = detector.detect(resized)
            for face in faces if faces is not None else []:
                x, y, w, h = (float(v) / factor for v in face[:4])
                found.append((x, y, x + w, y + h))
        return found


class RtDetrPersonDetector:
    def __init__(self, directory: Path | None = None, score_threshold: float = 0.5) -> None:
        self._directory = directory
        self._threshold = score_threshold
        self._loaded: Any = None

    def persons(self, image: Image.Image) -> list[Box]:
        import torch

        if self._loaded is None:
            from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection

            folder = RTDETR.verify(self._directory or models_dir())
            self._loaded = (
                RTDetrImageProcessor.from_pretrained(folder),
                RTDetrV2ForObjectDetection.from_pretrained(folder).eval(),
            )
        processor, model = self._loaded
        rgb = image.convert("RGB")
        with torch.no_grad():
            output = model(**processor(images=rgb, return_tensors="pt"))
        result = processor.post_process_object_detection(
            output, target_sizes=torch.tensor([rgb.size[::-1]]), threshold=self._threshold
        )[0]
        return [
            tuple(float(v) for v in box)
            for label, box in zip(result["labels"], result["boxes"])
            if model.config.id2label[int(label)] == "person"
        ]


def _area_share(box: Box, size: tuple[int, int]) -> float:
    width = max(0.0, min(box[2], size[0]) - max(box[0], 0.0))
    height = max(0.0, min(box[3], size[1]) - max(box[1], 0.0))
    return (width * height) / float(size[0] * size[1])


def _read_frames(path: Path) -> list[Image.Image]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("video cannot be opened")
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not fps or fps <= 0 or not count or count <= 0:
            raise ValueError("video has no readable length")
        if count / fps > VIDEO_MAX_SECONDS:
            raise ValueError(f"video is longer than {VIDEO_MAX_SECONDS} seconds")
        step = max(1, round(fps * VIDEO_FRAME_INTERVAL_S))
        frames, index = [], 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index % step == 0:
                frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
            index += 1
        # A file that ends early would leave part of the video unchecked.
        if index < count - step or not frames:
            raise ValueError("video could not be read to the end")
        return frames
    finally:
        capture.release()


class DetectorUploadGate:
    name = "detectors"

    def __init__(
        self,
        face_detector: FaceDetector | None = None,
        person_detector: PersonDetector | None = None,
        small_person_area: float = SMALL_PERSON_AREA,
    ) -> None:
        self._faces = face_detector or YuNetFaceDetector()
        self._persons = person_detector or RtDetrPersonDetector()
        self._small = small_person_area

    def check_image(self, image: Image.Image) -> UploadVerdict:
        try:
            flat = _flatten(image)
            faces = self._faces.faces(flat)
            persons = self._persons.persons(flat)
        except Exception as error:  # noqa: BLE001 - any failure must reject
            return UploadVerdict(
                UploadDecision.REJECTED, (f"detector failed: {type(error).__name__}: {error}",)
            )
        shares = [round(_area_share(box, flat.size), 4) for box in persons]
        details = {"faces": len(faces), "persons": len(persons), "person_area_shares": shares}
        if faces:
            return UploadVerdict(UploadDecision.REJECTED, (f"{len(faces)} face(s) found",), details)
        large = [share for share in shares if share >= self._small]
        if large:
            return UploadVerdict(
                UploadDecision.NEEDS_REVIEW,
                (f"person without a face covering {max(large):.0%} of the image",),
                details,
            )
        return UploadVerdict(UploadDecision.ACCEPTED, (), details)

    def check_file(self, path: Path) -> UploadVerdict:
        path = Path(path)
        try:
            if path.suffix.lower() in VIDEO_SUFFIXES:
                frames = _read_frames(path)
            else:
                with Image.open(path) as image:
                    image.load()
                    frames = [image.copy()]
        except Exception as error:  # noqa: BLE001 - unreadable files are rejected
            return UploadVerdict(
                UploadDecision.REJECTED, (f"file cannot be read: {type(error).__name__}: {error}",)
            )
        worst = UploadVerdict(UploadDecision.ACCEPTED)
        worst_frame = 0
        for index, frame in enumerate(frames):
            verdict = self.check_image(frame)
            if _SEVERITY[verdict.decision] > _SEVERITY[worst.decision]:
                worst, worst_frame = verdict, index
            if worst.decision is UploadDecision.REJECTED:
                break
        details = {**worst.details, "frames_checked": len(frames), "decisive_frame": worst_frame}
        return UploadVerdict(worst.decision, worst.reasons, details)


class RejectAllUploadGate:
    """Default when no gate is configured: nothing gets in."""

    name = "reject_all"

    def check_image(self, image: Image.Image) -> UploadVerdict:
        return UploadVerdict(UploadDecision.REJECTED, ("no upload gate configured",))

    def check_file(self, path: Path) -> UploadVerdict:
        return UploadVerdict(UploadDecision.REJECTED, ("no upload gate configured",))


class AllowListUploadGate:
    """Accepts only images whose pixels are known in advance (the built-in demo product).

    Lets the demo run where the detection models are not installed.
    """

    name = "demo_only"

    def __init__(self, allowed_pixel_hashes: set[str]) -> None:
        self._allowed = set(allowed_pixel_hashes)

    def check_image(self, image: Image.Image) -> UploadVerdict:
        if sha256_image(image) in self._allowed:
            return UploadVerdict(UploadDecision.ACCEPTED, (), {"allow_list": True})
        return UploadVerdict(UploadDecision.REJECTED, ("not the built-in demo product",))

    def check_file(self, path: Path) -> UploadVerdict:
        try:
            with Image.open(path) as image:
                image.load()
                return self.check_image(image)
        except Exception as error:  # noqa: BLE001
            return UploadVerdict(UploadDecision.REJECTED, (f"file cannot be read: {error}",))


UPLOAD_GATE_NAMES = (DetectorUploadGate.name, AllowListUploadGate.name, RejectAllUploadGate.name)


def upload_gate_by_name(name: str) -> UploadGate:
    if name == DetectorUploadGate.name:
        return DetectorUploadGate()
    if name == AllowListUploadGate.name:
        from nps.cli import demo_product

        return AllowListUploadGate({sha256_image(demo_product())})
    if name == RejectAllUploadGate.name:
        return RejectAllUploadGate()
    raise ValueError(f"unknown upload gate '{name}', expected one of {list(UPLOAD_GATE_NAMES)}")


def check_image_via_file(gate: UploadGate, image: Image.Image) -> UploadVerdict:
    """Helper for callers that hold an image and want the file-level result shape."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "upload.png"
        image.save(path)
        return gate.check_file(path)
