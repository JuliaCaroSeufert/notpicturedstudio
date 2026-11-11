"""Download the pinned detection models and verify their checksums.

    python scripts/fetch_models.py

Needs access to huggingface.co and its download server us.aws.cdn.hf.co.
"""

from __future__ import annotations

import sys
import urllib.request

from nps.detectors import ALL_MODELS, ModelError, models_dir


def main() -> int:
    target = models_dir()
    for model in ALL_MODELS:
        folder = target / model.key
        folder.mkdir(parents=True, exist_ok=True)
        for filename in model.files:
            path = folder / filename
            if not path.is_file():
                print(f"Lade {model.repo}/{filename}")
                urllib.request.urlretrieve(model.url(filename), path)
        try:
            model.verify(target)
        except ModelError as error:
            print(f"Fehler: {error}", file=sys.stderr)
            return 1
        print(f"OK: {model.repo} ({model.licence})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
