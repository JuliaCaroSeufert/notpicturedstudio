"""Stand-ins for models, so tests run without weights."""

from nps.intake.upload import DetectorUploadGate


class FakeFaces:
    def __init__(self, boxes=(), fail=False):
        self.boxes, self.fail = list(boxes), fail

    def faces(self, image):
        if self.fail:
            raise RuntimeError("face model broken")
        return self.boxes


class FakePersons:
    def __init__(self, boxes=(), fail=False):
        self.boxes, self.fail = list(boxes), fail

    def persons(self, image):
        if self.fail:
            raise RuntimeError("person model broken")
        return self.boxes


def open_upload_gate():
    """A gate whose detectors find nothing."""
    return DetectorUploadGate(FakeFaces(), FakePersons())
