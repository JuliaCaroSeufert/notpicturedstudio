"""Throwaway certificate chain for development and tests.

Files signed with it validate as intact but untrusted. It must never be used
for client deliveries; those need a certificate from a recognised authority.
"""

from __future__ import annotations

import datetime

ORGANISATION = "notpicturedstudio DEV (not for delivery)"


def generate_dev_chain() -> tuple[bytes, bytes]:
    """Return (certificate chain PEM, private key PEM). Needs the `dev` extra."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    def name(common_name: str) -> x509.Name:
        return x509.Name(
            [
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, ORGANISATION),
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            ]
        )

    def usage(*, signature: bool, cert_sign: bool) -> x509.KeyUsage:
        return x509.KeyUsage(
            digital_signature=signature,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=cert_sign,
            crl_sign=cert_sign,
            encipher_only=False,
            decipher_only=False,
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=1)
    root_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())

    root = (
        x509.CertificateBuilder()
        .subject_name(name("DEV Root"))
        .issuer_name(name("DEV Root"))
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(usage(signature=False, cert_sign=True), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    leaf = (
        x509.CertificateBuilder()
        .subject_name(name("DEV Signer"))
        .issuer_name(root.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(now + datetime.timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(usage(signature=True, cert_sign=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False
        )
        .sign(root_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    chain = leaf.public_bytes(pem) + root.public_bytes(pem)
    key = leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return chain, key
