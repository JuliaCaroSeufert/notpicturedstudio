"""Stand-in for the FLUX backend, shared by several test modules."""

from PIL import Image

from nps.engine.flux2_klein import LoadedModel


class FakeBackend:
    """Stands in for the model: returns a colour derived from the seed."""

    def __init__(self, size=None):
        self.loads = 0
        self.calls = []
        self._size = size

    def load(self, config):
        self.loads += 1
        return LoadedModel(
            weights_sha256="w" * 64,
            libraries={"torch": "2.6.0", "diffusers": "0.42.1"},
            runtime={"device": config.device, "gpu": "Fake L40S"},
        )

    def run(self, **kwargs):
        self.calls.append(kwargs)
        size = self._size or (kwargs["width"], kwargs["height"])
        seed = kwargs["seed"]
        return Image.new("RGBA", size, (seed % 256, (seed >> 8) % 256, 7, 255))
