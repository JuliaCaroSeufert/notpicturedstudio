"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from nps.audit.chain import AuditLog, ChainError
from nps.core.hashing import sha256_bytes
from nps.core.models import AssetState, ShootingBrief
from nps.dossier.build import build_dossier
from nps.engine.registry import ENGINE_NAMES, engine_by_name
from nps.intake.upload import UPLOAD_GATE_NAMES, DetectorUploadGate, upload_gate_by_name
from nps.pipeline import AssetRecord, Pipeline, PipelineError
from nps.provenance.c2pa_sign import C2paConfig, C2paSigner, ProvenanceError, read_credentials
from nps.provenance.devcert import generate_dev_chain
from nps.provenance.seal import Sealer
from nps.provenance.watermark import watermarker_by_name
from nps.safety.gate import GATE_NAMES, BlockAllGate, gate_by_name
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
    upload_gate = upload_gate_by_name(getattr(args, "upload_gate", DetectorUploadGate.name))
    return Pipeline(Path(args.out), engine, gate, sealer=sealer_from_env(), upload_gate=upload_gate)


def sealer_from_env() -> Sealer:
    """Certificate, key and watermark choice come from the environment only."""
    config = C2paConfig.from_env()
    return Sealer(
        signer=C2paSigner(config) if config else None,
        watermarker=watermarker_by_name(os.environ.get("NPS_WATERMARK")),
    )


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
    for upload in state.uploads.values():
        reasons = f"  ({'; '.join(upload.reasons)})" if upload.reasons else ""
        print(f"Upload {upload.filename} [{upload.purpose}] {upload.sha256[:12]}: {upload.decision}{reasons}")
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


def cmd_upload(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    sha256, verdict = pipeline.register_upload(
        args.campaign, Path(args.file), purpose=args.purpose, uploaded_by=args.by
    )
    _write_dossier(Path(args.out), pipeline.log, args.campaign)
    print(f"Upload {sha256[:12]}: {verdict.decision.value}")
    for reason in verdict.reasons:
        print(f"  {reason}")
    if verdict.decision.value == "needs_review":
        print(f"  Entscheidung nötig: nps upload-review --sha {sha256} --accept oder --reject")
    return 0 if verdict.decision.value == "accepted" else 2


def cmd_upload_review(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    sha256 = _full_upload_hash(Path(args.out), args.campaign, args.sha)
    pipeline.review_upload(args.campaign, sha256, args.by, accept=args.accept, note=args.note)
    _write_dossier(Path(args.out), pipeline.log, args.campaign)
    print("Upload angenommen." if args.accept else "Upload abgelehnt und gelöscht.")
    return 0


def _full_upload_hash(out: Path, campaign_id: str, prefix: str) -> str:
    uploads = read_campaign(AuditLog(out / "audit.jsonl"), campaign_id).uploads
    matches = [sha for sha in uploads if sha.startswith(prefix)]
    if len(matches) != 1:
        raise PipelineError(f"'{prefix}' passt auf {len(matches)} Uploads; bitte eindeutig angeben")
    return matches[0]


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


def cmd_dev_cert(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chain, key = generate_dev_chain()
    (out / "dev-chain.pem").write_bytes(chain)
    key_path = out / "dev-key.pem"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    print("Testzertifikat erzeugt. Nicht für Auslieferungen verwenden.")
    print(f"export NPS_C2PA_CERT={out / 'dev-chain.pem'}")
    print(f"export NPS_C2PA_KEY={key_path}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Show what a file says about itself and whether the audit chain knows it."""
    data = Path(args.file).read_bytes()
    report = read_credentials(data)
    if report is None:
        print("C2PA: keine Signatur vorhanden")
    else:
        print(f"C2PA: {report.state}" + ("" if report.intact else "  (Datei verändert oder Signatur ungültig)"))
        print(f"  Signiert von: {report.common_name} / {report.issuer}")
        print(f"  Quelle: {report.digital_source_type}")
        print(f"  Asset: {(report.asset or {}).get('asset_id')}")
        if report.state == "Valid":
            print("  Hinweis: Zertifikat ist nicht anerkannt (Testzertifikat).")

    known = False
    if args.campaign:
        digest = sha256_bytes(data)
        state = read_campaign(AuditLog(Path(args.out) / "audit.jsonl"), args.campaign)
        for shooting in state.shootings.values():
            for motif in shooting.motifs.values():
                for version in motif.versions:
                    if version.final_sha256 == digest:
                        known = True
                        print(
                            f"Audit-Kette: unverändert, Shooting {shooting.shooting_id}, "
                            f"Motiv {motif.motif_id}, Fassung V{version.number} ({version.status.value})"
                        )
        if not known:
            print("Audit-Kette: Datei ist dort nicht als versiegelte Fassung verzeichnet")
    intact = report is not None and report.intact
    return 0 if intact and (known or not args.campaign) else 2


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
        choices=GATE_NAMES,
        help="block_all (Standard, blockiert alles), mock_only (nur Test-Engine) "
        "oder provisional (Nacktheits-Klassifikatoren)",
    )
    run.add_argument("--upload-gate", default=DetectorUploadGate.name, choices=UPLOAD_GATE_NAMES)

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

    upload = command("upload", cmd_upload, "Referenz- oder Produktdatei prüfen und aufnehmen")
    upload.add_argument("file")
    upload.add_argument("--campaign", required=True)
    upload.add_argument("--by", required=True, help="Name der hochladenden Person")
    upload.add_argument("--purpose", default="reference", choices=("reference", "product"))
    upload.add_argument("--upload-gate", default=DetectorUploadGate.name, choices=UPLOAD_GATE_NAMES)

    review = command("upload-review", cmd_upload_review, "Über einen Upload entscheiden, den das Gate nicht entscheiden konnte")
    review.add_argument("--campaign", required=True)
    review.add_argument("--sha", required=True, help="Kennung des Uploads (Anfang genügt)")
    review.add_argument("--by", required=True, help="Name der entscheidenden Person")
    review.add_argument("--note", default="")
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--accept", action="store_true")
    decision.add_argument("--reject", action="store_true")

    on_version(command("release", cmd_release, "Fassung dem Kunden zeigen"))
    customer = command("customer", cmd_customer, "Entscheidung des Kunden festhalten")
    on_version(customer)
    customer.add_argument("--changes", help="Änderungswunsch des Kunden; ohne diese Angabe gilt die Fassung als abgenommen")
    customer.add_argument("--comment", default="", help="Anmerkung zur Abnahme")

    command("verify", cmd_verify, "Audit-Kette prüfen")
    command("dev-cert", cmd_dev_cert, "Testzertifikat für die C2PA-Signatur erzeugen")
    inspect = command("inspect", cmd_inspect, "Signatur einer Bilddatei prüfen und mit der Audit-Kette abgleichen")
    inspect.add_argument("file")
    inspect.add_argument("--campaign", help="zusätzlich mit dieser Kampagne abgleichen")

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except PipelineError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    except ProvenanceError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    except ChainError as error:
        print(f"Audit-Kette beschädigt: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
