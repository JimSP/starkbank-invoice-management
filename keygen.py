"""
keygen.py
=========
Generates a secp256k1 ECDSA key pair using the starkbank-ecdsa library
(exposed as starkbank.key.create()).

Usage
-----
    python keygen.py              # prints to stdout
    python keygen.py keys/        # saves keys/privateKey.pem + publicKey.pem
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
    print("PUBLIC KEY  (upload to Stark Bank dashboard)")
    print("=" * 60)
    print(pub)

    if save_path:
        print(f"\nKeys saved to: {save_path}")
