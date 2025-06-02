import pytest
from cryptography.x509.oid import (
    NameOID,
)

from .gen_certhash import (
    CertificateManager,
)


# Certificate generation with default common name
@pytest.mark.trio
async def test_generate_self_signed_cert_with_default_common_name():
    cert_manager = CertificateManager()

    cert_manager.generate_self_signed_cert()

    assert cert_manager.certificate is not None
    assert cert_manager.private_key is not None
    assert cert_manager.certhash is not None

    # Verify the common name is the default "py-libp2p"
    cert_subject = cert_manager.certificate.subject
    common_name = cert_subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert common_name == "py-libp2p"

    # Verify certhash format (base64 URL-safe encoded string)
    certhash = cert_manager.get_certhash()
    assert isinstance(certhash, str)
    assert "+" not in certhash
    assert "/" not in certhash


# Accessing certhash before certificate generation
@pytest.mark.trio
async def test_get_certhash_before_certificate_generation():
    cert_manager = CertificateManager()

    assert cert_manager.certificate is None
    assert cert_manager.private_key is None
    assert cert_manager.certhash is None

    certhash = cert_manager.get_certhash()
    assert certhash == "uEiNone"  # Default value when no certificate is generated

    # generate the certificate and verify certhash is available
    cert_manager.generate_self_signed_cert()
    assert cert_manager.get_certhash() is not None
