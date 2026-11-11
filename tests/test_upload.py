import numpy as np
import pytest
from PIL import Image

from nps.cli import main
from nps.core.models import AssetState
from nps.dossier.build import build_dossier
from nps.engine.mock import MockEngine
from nps.intake.upload import (
    AllowListUploadGate,
    DetectorUploadGate,
    RejectAllUploadGate,
    UploadDecision,
    upload_gate_by_name,
)
from nps.pipeline import Pipeline, PipelineError
from nps.safety.gate import MockOnlyGate
from tests.fakes import FakeFaces, FakePersons, open_upload_gate

C = "test-campaign"
IMAGE = Image.new("RGB", (200, 100), (120, 130, 140))
SMALL = (0, 0, 50, 50)  # 12.5 % of the image
LARGE = (0, 0, 100, 60)  # 30 %


def gate(faces=(), persons=(), **kwargs):
    return DetectorUploadGate(FakeFaces(faces, kwargs.get("faces_fail", False)),
                              FakePersons(persons, kwargs.get("persons_fail", False)))


# -- decision rules ----------------------------------------------------------


def test_nothing_found_is_accepted():
    verdict = gate().check_image(IMAGE)
    assert verdict.decision is UploadDecision.ACCEPTED
    assert verdict.details == {"faces": 0, "persons": 0, "person_area_shares": []}


def test_any_face_is_rejected_even_next_to_a_small_person():
    verdict = gate(faces=[(1, 1, 9, 9)], persons=[SMALL]).check_image(IMAGE)
    assert verdict.decision is UploadDecision.REJECTED
    assert "face" in verdict.reasons[0]


def test_small_person_area_without_face_is_accepted():
    verdict = gate(persons=[SMALL, (150, 50, 190, 90)]).check_image(IMAGE)
    assert verdict.decision is UploadDecision.ACCEPTED
    assert verdict.details["persons"] == 2


def test_larger_person_without_face_goes_to_a_human():
    verdict = gate(persons=[SMALL, LARGE]).check_image(IMAGE)
    assert verdict.decision is UploadDecision.NEEDS_REVIEW
    assert "30%" in verdict.reasons[0]


def test_threshold_is_inclusive():
    exactly = (0, 0, 60, 50)  # 15 %
    assert gate(persons=[exactly]).check_image(IMAGE).decision is UploadDecision.NEEDS_REVIEW


def test_boxes_are_clipped_to_the_image():
    overhang = (-1000, -1000, 20, 20)  # only 2 % lies inside
    assert gate(persons=[overhang]).check_image(IMAGE).decision is UploadDecision.ACCEPTED


@pytest.mark.parametrize("broken", ["faces_fail", "persons_fail"])
def test_failing_detector_rejects(broken):
    verdict = gate(**{broken: True}).check_image(IMAGE)
    assert verdict.decision is UploadDecision.REJECTED
    assert "detector failed" in verdict.reasons[0]


def test_transparent_cutouts_are_flattened_before_detection():
    seen = {}

    class Recorder(FakeFaces):
        def faces(self, image):
            seen["mode"], seen["corner"] = image.mode, image.getpixel((0, 0))
            return []

    DetectorUploadGate(Recorder(), FakePersons()).check_image(Image.new("RGBA", (40, 40), (0, 0, 0, 0)))
    assert seen == {"mode": "RGB", "corner": (255, 255, 255)}


# -- files and videos --------------------------------------------------------


def test_unreadable_file_is_rejected(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    assert gate().check_file(path).decision is UploadDecision.REJECTED


def write_video(path, frames, fps=10):
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    for value in frames:
        writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    writer.release()


class FaceInBrightFrames:
    def faces(self, image):
        return [(1, 1, 9, 9)] if image.getpixel((0, 0))[0] > 200 else []


def test_video_is_checked_frame_by_frame(tmp_path):
    clean = tmp_path / "clean.mp4"
    write_video(clean, [10] * 30)
    verdict = DetectorUploadGate(FaceInBrightFrames(), FakePersons()).check_file(clean)
    assert verdict.decision is UploadDecision.ACCEPTED
    assert verdict.details["frames_checked"] == 6  # 3 seconds, one frame per half second

    late = tmp_path / "late.mp4"
    write_video(late, [10] * 20 + [250] * 10)
    verdict = DetectorUploadGate(FaceInBrightFrames(), FakePersons()).check_file(late)
    assert verdict.decision is UploadDecision.REJECTED
    assert verdict.details["decisive_frame"] == 4


def test_too_long_or_broken_video_is_rejected(tmp_path, monkeypatch):
    import nps.intake.upload as upload

    path = tmp_path / "long.mp4"
    write_video(path, [10] * 30)
    monkeypatch.setattr(upload, "VIDEO_MAX_SECONDS", 2)
    verdict = gate().check_file(path)
    assert verdict.decision is UploadDecision.REJECTED and "longer than" in verdict.reasons[0]

    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"\x00" * 100)
    assert gate().check_file(broken).decision is UploadDecision.REJECTED


def test_other_gates(product):
    assert RejectAllUploadGate().check_image(IMAGE).decision is UploadDecision.REJECTED
    from nps.core.hashing import sha256_image

    allow = AllowListUploadGate({sha256_image(product)})
    assert allow.check_image(product).decision is UploadDecision.ACCEPTED
    assert allow.check_image(IMAGE).decision is UploadDecision.REJECTED
    with pytest.raises(ValueError):
        upload_gate_by_name("open")


# -- pipeline ----------------------------------------------------------------


def pipeline(tmp_path, upload_gate=None):
    kwargs = {"upload_gate": upload_gate} if upload_gate else {}
    return Pipeline(tmp_path, MockEngine(), MockOnlyGate(), **kwargs)


def saved(tmp_path, name="ref.png"):
    path = tmp_path / name
    IMAGE.save(path)
    return path


def test_pipeline_without_upload_gate_admits_nothing(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    records = pipe.generate_shooting(brief, product)
    assert [r.state for r in records] == [AssetState.REJECTED]
    assert records[0].checks[0].check == "product_upload"
    assert pipe.state(C).shootings == {}
    assert not list(tmp_path.rglob("*.png"))


def test_product_with_a_face_stops_the_shooting(tmp_path, brief, product):
    pipe = pipeline(tmp_path, gate(faces=[(1, 1, 9, 9)]))
    records = pipe.generate_shooting(brief, product)
    assert records[0].state is AssetState.REJECTED
    state = pipe.state(C)
    assert state.shootings == {} and state.assets == {}
    (upload,) = state.uploads.values()
    assert upload.decision == "rejected" and upload.purpose == "product"


def test_product_needing_review_runs_after_a_human_accepts(tmp_path, brief, product):
    pipe = pipeline(tmp_path, gate(persons=[(0, 0, 60, 40)]))
    first = pipe.generate_shooting(brief, product)
    assert first[0].state is AssetState.REJECTED
    sha = first[0].checks[0].details["sha256"]
    assert first[0].checks[0].details["decision"] == "needs_review"

    pipe.review_upload(C, sha, "Erika", accept=True, note="nur eine Hand")
    records = pipe.generate_shooting(brief, product)
    assert all(r.state is AssetState.IN_REVIEW for r in records) and len(records) == 12
    assert pipe.state(C).uploads[sha].review["reviewer"] == "Erika"


def test_accepted_reference_is_stored_and_logged(tmp_path):
    pipe = pipeline(tmp_path / "work", open_upload_gate())
    sha, verdict = pipe.register_upload(C, saved(tmp_path), purpose="reference", uploaded_by="Erika")
    assert verdict.decision is UploadDecision.ACCEPTED
    assert (tmp_path / "work" / "uploads" / "accepted" / sha).read_bytes() == saved(tmp_path).read_bytes()
    upload = pipe.state(C).uploads[sha]
    assert (upload.filename, upload.uploaded_by, upload.gate) == ("ref.png", "Erika", "detectors")
    assert build_dossier(pipe.log, C)["uploads"][0]["sha256"] == sha


def test_rejected_reference_is_logged_but_not_kept(tmp_path):
    pipe = pipeline(tmp_path / "work", gate(faces=[(1, 1, 9, 9)]))
    sha, verdict = pipe.register_upload(C, saved(tmp_path), purpose="reference", uploaded_by="Erika")
    assert verdict.decision is UploadDecision.REJECTED
    assert not (tmp_path / "work" / "uploads").exists()
    assert pipe.state(C).uploads[sha].decision == "rejected"
    with pytest.raises(PipelineError):
        pipe.review_upload(C, sha, "Erika", accept=True)


def test_reference_waiting_for_review_is_kept_apart(tmp_path):
    work = tmp_path / "work"
    pipe = pipeline(work, gate(persons=[LARGE]))
    sha, verdict = pipe.register_upload(C, saved(tmp_path), purpose="reference", uploaded_by="Erika")
    assert verdict.decision is UploadDecision.NEEDS_REVIEW
    assert (work / "uploads" / "pending" / sha).exists()
    assert not pipe.state(C).uploads[sha].usable

    pipe.review_upload(C, sha, "Erika", accept=False, note="Rückenansicht eines Kindes")
    assert not (work / "uploads" / "pending" / sha).exists()
    assert not (work / "uploads" / "accepted").exists()
    assert pipe.state(C).uploads[sha].decision == "rejected"
    with pytest.raises(PipelineError):
        pipe.review_upload(C, sha, "Erika", accept=True)


def test_same_file_is_checked_once(tmp_path):
    pipe = pipeline(tmp_path / "work", open_upload_gate())
    path = saved(tmp_path)
    pipe.register_upload(C, path, purpose="reference", uploaded_by="A")
    pipe.register_upload(C, path, purpose="reference", uploaded_by="B")
    assert [e.event for e in pipe.log.verify()] == ["upload_checked"]


def test_cli_upload_with_demo_gate(tmp_path, capsys):
    out = str(tmp_path / "work")
    path = saved(tmp_path)
    code = main(["upload", str(path), "--out", out, "--campaign", C, "--by", "E", "--upload-gate", "demo_only"])
    assert code == 2
    assert "rejected" in capsys.readouterr().out
    assert main(["status", "--out", out, "--campaign", C]) == 0
    assert "ref.png" in capsys.readouterr().out
