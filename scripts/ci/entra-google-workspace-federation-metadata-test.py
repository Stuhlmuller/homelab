#!/usr/bin/env python3
"""Containment checks for the Google Workspace federation metadata transfer."""
import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / "entra-google-workspace-federation-metadata.py"
spec = importlib.util.spec_from_file_location("metadata", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
xml = b'''<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://accounts.google.com/o/saml2?idpid=test">
<IDPSSODescriptor><KeyDescriptor><KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#"><X509Data><X509Certificate>YQ==</X509Certificate></X509Data></KeyInfo></KeyDescriptor>
<SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://accounts.google.com/o/saml2/idp?idpid=test"/></IDPSSODescriptor></EntityDescriptor>'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "GoogleIDPMetadata.xml"
    path.write_bytes(xml)
    assert module.metadata(path) == {
        "issuer_uri": "https://accounts.google.com/o/saml2?idpid=test",
        "sign_in_uri": "https://accounts.google.com/o/saml2/idp?idpid=test",
        "signing_certificate": "YQ==",
    }
    path.write_bytes(b"<!DOCTYPE test><bad/>")
    try:
        module.metadata(path)
        raise AssertionError("DOCTYPE accepted")
    except module.Failure:
        pass
with patch.object(module, "command", return_value='{"Version": 4}') as command:
    module.store({"issuer_uri": "https://accounts.google.com/x", "sign_in_uri": "https://accounts.google.com/y", "signing_certificate": "YQ=="})
    assert "YQ==" not in str(command.call_args_list[0])
print("Google Workspace federation metadata checks passed")
