import sys
import starkbank


def generate_keys(path: str | None = None) -> tuple[str, str]:
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