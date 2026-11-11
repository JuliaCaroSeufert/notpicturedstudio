"""Command line entry point for the step-0 pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from nps.audit.chain import AuditLog, ChainError
from nps.core.models import AssetState, Brief
from nps.dossier.build import build_dossier
from nps.engine.mock import MockEngine
from nps.pipeline import Pipeline, PipelineError
from nps.safety.gate import BlockAllGate, gate_by_name

DEMO_BRIEF = {
    "campaign_id": "demo-herbst",
    "brand": {"name": "Beispielmarke", "colors": ["#1F6F8B", "#F2C14E"]},
    "product_name": "Holzbauklötze",
    "product_category": "toys",
    "scene": "Helles Kinderzimmer, weiches Tageslicht, Holzboden",
    "child": {"age_group": "toddler", "description": "sitzt auf dem Boden und stapelt Klötze"},
    "width": 768,
    "height": 768,
    "seed": 1234,
    "placement": {"x": 420, "y": 470},
}


def demo_product() -> Image.Image:
    """A small synthetic product cut-out, so the demo needs no input files."""
    product = Image.new("RGBA", (220, 180), (0, 0, 0, 0))
    draw = ImageDraw.Draw(product)
    draw.rounded_rectangle((10, 60, 110, 170), radius=12, fill=(214, 64, 69, 255))
    draw.rounded_rectangle((100, 20, 210, 170), radius=12, fill=(31, 111, 139, 255))
    draw.ellipse((40, 10, 120, 90), fill=(242, 193, 78, 255))
    return product


def _write_dossier(out: Path, log: AuditLog, campaign_id: str) -> Path:
    path = out / f"dossier-{campaign_id}.json"
    path.write_text(json.dumps(build_dossier(log, campaign_id), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def cmd_run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if args.demo:
        brief, product = Brief.model_validate(DEMO_BRIEF), demo_product()
    else:
        if not args.brief or not args.product:
            print("Fehler: --brief und --product angeben oder --demo verwenden.", file=sys.stderr)
            return 64
        brief = Brief.model_validate_json(Path(args.brief).read_text(encoding="utf-8"))
        product = Image.open(args.product).convert("RGBA")

    pipeline = Pipeline(out, MockEngine(), gate_by_name(args.safety_gate))
    try:
        record = pipeline.generate(brief, product)
        if record.state is AssetState.IN_REVIEW and args.approve_as:
            record = pipeline.review(brief, record.asset_id, args.approve_as, approve=True)
    except PipelineError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1

    dossier = _write_dossier(out, pipeline.log, brief.campaign_id)
    print(f"Asset:   {record.asset_id or '-'}")
    print(f"Zustand: {record.state.value}")
    for check in record.checks:
        if not check.passed:
            print(f"Nicht bestanden: {check.check} {json.dumps(check.details, ensure_ascii=False)}")
    if record.path:
        print(f"Bild:    {record.path}")
    print(f"Dossier: {dossier}")
    if record.state is AssetState.IN_REVIEW:
        print("Wartet auf Freigabe (--approve-as NAME).")
    return 0 if record.state in (AssetState.SEALED, AssetState.IN_REVIEW) else 2


def cmd_verify(args: argparse.Namespace) -> int:
    log = AuditLog(Path(args.out) / "audit.jsonl")
    try:
        entries = log.verify()
    except ChainError as error:
        print(f"Audit-Kette beschädigt: {error}", file=sys.stderr)
        return 1
    print(f"Audit-Kette intakt, {len(entries)} Einträge.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nps")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Brief bis zum gekennzeichneten Bild ausführen")
    run.add_argument("--out", required=True, help="Ausgabeverzeichnis")
    run.add_argument("--demo", action="store_true", help="eingebauten Beispiel-Brief verwenden")
    run.add_argument("--brief", help="Brief als JSON-Datei")
    run.add_argument("--product", help="Produktfreisteller als PNG mit Transparenz")
    run.add_argument(
        "--safety-gate",
        default=BlockAllGate.name,
        help="block_all (Standard, blockiert alles) oder mock_only (nur Test-Engine)",
    )
    run.add_argument("--approve-as", help="Name der Person, die das Bild freigibt")
    run.set_defaults(handler=cmd_run)

    verify = commands.add_parser("verify", help="Audit-Kette prüfen")
    verify.add_argument("--out", required=True)
    verify.set_defaults(handler=cmd_verify)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
