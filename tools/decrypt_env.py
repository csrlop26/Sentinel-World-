"""
Descifra .env.enc con tu contraseña y restaura .env.
Llamado automáticamente por update.bat si .env.enc existe y .env no.

Uso:
    python tools/decrypt_env.py
"""
import base64
import getpass
import sys
from pathlib import Path


def main():
    enc_path = Path(".env.enc")
    out_path = Path(".env")

    if not enc_path.exists():
        print("ERROR: no se encuentra .env.enc en el directorio actual.")
        sys.exit(1)

    try:
        from cryptography.fernet import Fernet, InvalidToken
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        print("ERROR: ejecuta primero:  pip install cryptography")
        sys.exit(1)

    if out_path.exists():
        answer = input(".env ya existe. ¿Sobreescribir? (s/n): ").strip().lower()
        if answer != "s":
            print("Cancelado — .env no ha sido modificado.")
            sys.exit(0)

    content = enc_path.read_bytes()
    parts = content.split(b"\n", 1)
    if len(parts) != 2:
        print("ERROR: formato de .env.enc inválido — ¿fue creado con encrypt_env.py?")
        sys.exit(1)

    try:
        salt = base64.urlsafe_b64decode(parts[0])
    except Exception:
        print("ERROR: formato de .env.enc corrupto.")
        sys.exit(1)

    encrypted = parts[1]
    password = getpass.getpass("Contraseña: ").encode()

    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    fernet = Fernet(key)

    try:
        plaintext = fernet.decrypt(encrypted)
    except InvalidToken:
        print("ERROR: contraseña incorrecta o archivo .env.enc corrupto.")
        sys.exit(1)

    out_path.write_bytes(plaintext)
    print(f"✓ .env restaurado correctamente desde {enc_path}")


if __name__ == "__main__":
    main()
