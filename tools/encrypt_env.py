"""
Cifra tu .env con una contraseña y guarda el resultado en .env.enc.
El archivo .env.enc puede subirse al repo (es texto cifrado, ilegible sin la contraseña).
Tu contraseña NO se guarda en ningún sitio — es solo tuya.

Uso:
    python tools/encrypt_env.py
"""
import base64
import getpass
import os
import sys
from pathlib import Path


def main():
    env_path = Path(".env")
    out_path = Path(".env.enc")

    if not env_path.exists():
        print("ERROR: no se encuentra .env en el directorio actual.")
        sys.exit(1)

    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        print("ERROR: ejecuta primero:  pip install cryptography")
        sys.exit(1)

    print("Cifrado de .env → .env.enc")
    print("La contraseña NO se guarda en ningún sitio.\n")

    password = getpass.getpass("Contraseña: ").encode()
    password2 = getpass.getpass("Confirma contraseña: ").encode()
    if password != password2:
        print("ERROR: las contraseñas no coinciden.")
        sys.exit(1)

    # Derivar clave AES-256 desde la contraseña con PBKDF2
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    fernet = Fernet(key)

    plaintext = env_path.read_bytes()
    encrypted = fernet.encrypt(plaintext)

    # Formato: <salt_b64>\n<datos_cifrados>
    output = base64.urlsafe_b64encode(salt) + b"\n" + encrypted
    out_path.write_bytes(output)

    print(f"\n✓ Cifrado guardado en: {out_path}")
    print("  Puedes subir .env.enc al repo — sin la contraseña no sirve de nada.")
    print("  NUNCA compartas la contraseña.")


if __name__ == "__main__":
    main()
