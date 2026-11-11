"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from nps.audit.chain import AuditLog, ChainError
from nps.core.models import AssetState, ShootingBrief
from nps.dossier.build import build_dossier
from nps.engine.registry import ENGINE_NAMES, engine_by_name
from nps.pipeline import AssetRecord, Pipeline, PipelineError
from nps.safety.gate import BlockAllGate, gate_by_name
from nps.state import read_campaign

DEMO_BRIEF = {
    "campaign_id": "demo-herbst",
    "shooting_id": "kinderzimmer",
    "brand": {"name": "Beispielmarke", "colors": ["#1F6F8B", "#F2C14E"]},
    "product_name": "Holzbauklötze",
    "product_category": "toys",
    "scene": "Helles Kinderzimmer, weiches Tageslicht, Holzboden",
    "persons": [{"age_years": 3, "description": "sitzt auf dem Boden und spielt"}],
    "width": 768,
    "height": 768,
    "base_seed": 1234,
    "variants_per_motif": 6,
    "motifs": [
        {"motif_id": "stapeln", "description": "Kind stapelt Klötze", "placement": {"x": 420, "y": 470}},
        {"motif_id": "ueberblick", "placement": {"x": 80, "y": 500}},
    ],
}


def demo_product() -> Image.Image:
    """A small synthetic product cut-out, so the demo needs no input files."""
    product = Image.new("RGBA", (220, 180), (0, 0, 0, 0))
    draw = ImageDraw.Draw(product)
    draw.rounded_rectangle((10, 60, 110, 170), radius=12, fill=(214, 64, 69, 255))
    draw.rounded_rectangle((100, 20, 210, 170), radius=12, fill=(31, 111, 139, 255))
    draw.ellipse((40, 10, 120, 90), fill=(242, 193, 78, 255))
    return product


def _pipeline(args: argparse.Namespace) -> Pipeline:
    # Review and client steps never generate, so they get the engine-free defaults.
    engine = engine_by_name(getattr(args, "engine", "mock"))
    gate = gate_by_name(getattr(args, "safety_gate", BlockAllGate.name))
    return Pipeline(Path(args.out), engine, gate)


def _write_dossier(out: Path, log: AuditLog, campaign_id: str) -> Path:
    path = out / f"dossier-{campaign_id}.json"
    path.write_text(
        json.dumps(build_dossier(log, campaign_id), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _print_status(out: Path, campaign_id: str) -> None:
    state = read_campaign(AuditLog(out / "audit.jsonl"), campaign_id)
    for shooting in state.shootings.values():
        print(f"Shooting {shooting.shooting_id}")
        for motif in shooting.motifs.values():
            print(f"  Motiv {motif.motif_id}")
            for variant in motif.variants:
                print(f"    Variante {variant.index + 1}: {variant.asset_id}  {variant.state.value}")
            for version in motif.versions:
                print(f"    Fassung V{version.number}: {version.asset_id}  {version.status.value}")
    for rejected in state.rejected_briefs:
        reasons = "; ".join(rejected["check"]["details"]["reasons"])
        print(f"Abgelehntes Briefing {rejected['shooting_id']}: {reasons}")


def cmd_run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if args.demo:
        brief, product = ShootingBrief.model_validate(DEMO_BRIEF), demo_product()
    else:
        if not args.brief or not args.product:
            print("Fehler: --brief und --product angeben oder --demo verwenden.", file=sys.stderr)
            return 64
        brief = ShootingBrief.model_validate_json(Path(args.brief).read_text(encoding="utf-8"))
        product = Image.open(args.product).convert("RGBA")

    pipeline = _pipeline(args)
    records: list[AssetRecord] = pipeline.generate_shooting(brief, product)
    dossier = _write_dossier(out, pipeline.log, brief.campaign_id)
    _print_status(out, brief.campaign_id)
    for failed in {
        (check.check, json.dumps(check.details, ensure_ascii=False))
        for record in records
        for check in record.checks
        if not check.passed
    }:
        print(f"Nicht bestanden: {failed[0]} {failed[1]}")
    print(f"Dossier: {dossier}")
    return 0 if any(record.state is AssetState.IN_REVIEW for record in records) else 2


def cmd_status(args: argparse.Namespace) -> int:
    _print_status(Path(args.out), args.campaign)
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.approve_variant(args.campaign, args.asset, args.by, args.note)
    _write_dossier(Path(args.out), pipeline.log, args.campaign)
    if isinstance(result, AssetRecord):
        print(f"Blockiert: {result.checks[0].check}")
        return 2
    print(f"Motiv {result.motif_id}: Fassung V{result.number} versiegelt: {result.path}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    pipeline.reject_variant(args.campaign, args.asset, args.by, args.note)
    _write_dossier(Path(args.out), pipeline.log, args.campaign)
    print("Variante abgelehnt.")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    pipeline.release_version(args.campaign, args.shooting, args.motif, args.version, args.by)
    _write_dossier(Path(args.out), pipeline.log, args.campaign)
    print(f"Fassung V{args.version} an den Kunden freigegeben.")
    return 0


def cmd_customer(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.customer_decision(
        args.campaign,
        args.shooting,
        args.motif,
        args.version,
        approved=args.changes is None,
        recorded_by=args.by,
        comment=args.changes or args.comment,
    )
    _write_dossier(Path(args.out), pipeline.log, args.campaign)
    print(f"Fassung V{args.version}: {result.status.value}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    entries = AuditLog(Path(args.out) / "audit.jsonl").verify()
    print(f"Audit-Kette intakt, {len(entries)} Einträge.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nps")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str, handler, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--out", required=True, help="Arbeitsverzeichnis")
        sub.set_defaults(handler=handler)
        return sub

    def on_version(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--campaign", required=True)
        sub.add_argument("--shooting", required=True)
        sub.add_argument("--motif", required=True)
        sub.add_argument("--version", required=True, type=int)
        sub.add_argument("--by", required=True, help="Name der handelnden Person")

    run = command("run", cmd_run, "Shooting registrieren und Varianten erzeugen")
    run.add_argument("--demo", action="store_true", help="eingebautes Beispiel-Shooting verwenden")
    run.add_argument("--brief", help="Shooting-Briefing als JSON-Datei")
    run.add_argument("--product", help="Produktfreisteller als PNG mit Transparenz")
    run.add_argument("--engine", default="mock", choices=ENGINE_NAMES)
    run.add_argument(
        "--safety-gate",
        default=BlockAllGate.name,
        help="block_all (Standard, blockiert alles) oder mock_only (nur Test-Engine)",
    )

    status = command("status", cmd_status, "Stand einer Kampagne anzeigen")
    status.add_argument("--campaign", required=True)

    for name, handler, help_text in (
        ("approve", cmd_approve, "Variante intern freigeben; sie wird zur nächsten Fassung"),
        ("reject", cmd_reject, "Variante intern ablehnen"),
    ):
        sub = command(name, handler, help_text)
        sub.add_argument("--campaign", required=True)
        sub.add_argument("--asset", required=True)
        sub.add_argument("--by", required=True, help="Name der prüfenden Person")
        sub.add_argument("--note", default="")

    on_version(command("release", cmd_release, "Fassung dem Kunden zeigen"))
    customer = command("customer", cmd_customer, "Entscheidung des Kunden festhalten")
    on_version(customer)
    customer.add_argument("--changes", help="Änderungswunsch des Kunden; ohne diese Angabe gilt die Fassung als abgenommen")
    customer.add_argument("--comment", default="", help="Anmerkung zur Abnahme")

    command("verify", cmd_verify, "Audit-Kette prüfen")

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except PipelineError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    except ChainError as error:
        print(f"Audit-Kette beschädigt: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
