"""
keygen.py
=========
Generates a secp256k1 ECDSA key pair using the starkbank-ecdsa library
(exposed as starkbank.key.create()).

The SDK saves the files as:
    keys/private-key.pem   <- keep secret, set as STARKBANK_PRIVATE_KEY
    keys/public-key.pem    <- paste the contents into Stark Bank dashboard

Usage
-----
    python keygen.py              # prints to stdout
    python keygen.py keys/        # saves keys/private-key.pem + keys/public-key.pem
"""

import sys
import starkbank


def generate_keys(path: str | None = None) -> tuple[str, str]:
    """Return (private_key_pem, public_key_pem). Saves files if path given."""
    return starkbank.key.create(path)


if __name__ == "__main__":  # pragma: no cover
    save_path = sys.argv[1] if len(sys.argv) > 1 else None
    priv, pub = generate_keys(save_path)

    print("=" * 60)
    print("PRIVATE KEY  (set as STARKBANK_PRIVATE_KEY env var)")
    print("=" * 60)
    print(priv)
    print("=" * 60)
    print("PUBLIC KEY  (paste this into the Stark Bank dashboard)")
    print("Menu → Integrations → New Project → Public Key field")
    print("=" * 60)
    print(pub)

    if save_path:
        print(f"\nFiles saved:")
        print(f"  {save_path}private-key.pem  <- keep secret")
        print(f"  {save_path}public-key.pem   <- paste into dashboard")