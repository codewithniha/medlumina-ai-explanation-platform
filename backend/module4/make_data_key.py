"""Prints a fresh random key for MEDLUMINA_DATA_KEY. Run once, store the output in your secret manager
(or, for a local setup, in backend/module4/.env). Do NOT commit it. Lose it and kept DICOM originals
cannot be recovered."""
import base64
import secrets

print(base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
