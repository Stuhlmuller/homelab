# Google Workspace Entra federation

This operator module changes the verified `stuhlmuller.net` Entra domain from
managed authentication to Google Workspace SAML federation. It only reads
validated metadata from the protected SSM parameter
`/homelab/entra/google-workspace-federation-metadata`; no certificate or
endpoint is committed to Git.

Apply the shared SSM declaration first. From clean, signed current `main`, run
`scripts/entra-google-workspace-federation-metadata.py` with the
`GoogleIDPMetadata.xml` downloaded from the Google Workspace Microsoft Office
365 app. Then create and review a private saved plan for this operator unit.
Google Workspace auto-provisioning must be enabled for the same user scope
before federation: each Google user needs a matching Entra account.
