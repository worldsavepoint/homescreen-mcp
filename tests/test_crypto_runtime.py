"""Exercise the pinned USB dependency's certificate path with generated keys."""
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pymobiledevice3.ca import generate_pairing_cert_chain


def test_usb_pairing_certificate_generation_and_signatures():
    device_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = device_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.PKCS1)
    host_pem, host_key_pem, device_pem, root_pem, root_key_pem = generate_pairing_cert_chain(public_key)
    host = x509.load_pem_x509_certificate(host_pem)
    device = x509.load_pem_x509_certificate(device_pem)
    root = x509.load_pem_x509_certificate(root_pem)
    host_key = serialization.load_pem_private_key(host_key_pem, password=None)
    root_key = serialization.load_pem_private_key(root_key_pem, password=None)
    assert device.public_key().public_numbers() == device_key.public_key().public_numbers()
    assert host.public_key().public_numbers() == host_key.public_key().public_numbers()
    assert root.public_key().public_numbers() == root_key.public_key().public_numbers()
    for certificate in (root, host, device):
        root.public_key().verify(certificate.signature, certificate.tbs_certificate_bytes,
                                 padding.PKCS1v15(), certificate.signature_hash_algorithm)
    assert root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert not host.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert not device.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
