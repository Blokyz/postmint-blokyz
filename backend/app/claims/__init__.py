"""Phase-3 claims engine: eligibility evaluation + holding-window tracking.

Off-chain half of the race (PROJECT_MASTER §11). Eligibility is computed from the
DB ownership snapshot + the approved atlas manifest; holding windows are tracked in
the `claims` table and kept honest by transfer polling. The on-chain trust bridge
(the ECDSA claim attestation) lives in `app.claim_signing`.
"""
