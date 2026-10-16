from __future__ import annotations

import datetime
import ipaddress
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DAYS = 30


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def write_self_signed(directory: Path, host: str = DEFAULT_HOST,
                      common_name: str | None = None) -> dict:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    common_name = common_name or host
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    alternative = x509.SubjectAlternativeName([x509.DNSName(host),
                                              x509.DNSName("localhost")])
    if _is_address(host):
        alternative = x509.SubjectAlternativeName(
            [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(host))])
    certificate = (x509.CertificateBuilder()
                   .subject_name(subject)
                   .issuer_name(subject)
                   .public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(_now() - datetime.timedelta(minutes=5))
                   .not_valid_after(_now() + datetime.timedelta(days=DAYS))
                   .add_extension(alternative, critical=False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                                  critical=True)
                   .sign(key, hashes.SHA256()))
    certificate_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    return {"certificate": str(certificate_path), "key": str(key_path),
            "host": host, "days": DAYS,
            "detail": "autofirmado: el cliente tiene que confiar en este archivo "
                      "explicitamente; no es una cadena publica"}


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def main(argv: list) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path.cwd() / ".cshcli" / "tls"
    report = write_self_signed(target)
    print(f"certificado: {report['certificate']}")
    print(f"clave:       {report['key']}")
    print(f"anfitrion:   {report['host']}")
    print(f"vigencia:    {report['days']} dias, {report['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))