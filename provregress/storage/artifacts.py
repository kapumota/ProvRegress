"""Almacén inmutable de bytes con direccionamiento por contenido SHA-256."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from pydantic import ValidationError

from provregress.schema.common import ArtifactRef, HashRef
from provregress.storage.hashing import sha256_hex


class ArtifactStoreError(ValueError):
    """Error al publicar o consultar un artefacto del almacén."""


class ArtifactIntegrityError(ArtifactStoreError):
    """El contenido almacenado no coincide con su identidad declarada."""


class ArtifactStore:
    """Conserva una sola copia verificable de cada secuencia de bytes."""

    def __init__(self, root: Path) -> None:
        """Establece un directorio raíz sin escribir artefactos todavía."""
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ArtifactStoreError("La raíz del almacén debe ser un directorio.")

    @staticmethod
    def _relative_path(digest: str) -> str:
        """Deriva una ruta estable exclusivamente del digest."""
        return f"sha256/{digest[:2]}/{digest}"

    def _target(self, digest: str, *, create: bool) -> Path:
        """Verifica que los directorios del almacén no sean enlaces simbólicos."""
        base = self.root / "sha256"
        directory = base / digest[:2]
        for part in (base, directory):
            if part.is_symlink():
                raise ArtifactStoreError("No se admiten directorios simbólicos en el almacén.")
            if part.exists() and not part.is_dir():
                raise ArtifactStoreError("La estructura del almacén no es un directorio.")
            if create:
                # Se comprueba cada nivel antes de crear el siguiente.
                part.mkdir(exist_ok=True)
                if part.is_symlink() or not part.is_dir():
                    raise ArtifactStoreError("La estructura del almacén no es segura.")
        return directory / digest

    def _checked_ref(self, ref: ArtifactRef) -> ArtifactRef:
        """Revalida referencias, incluidas las alteradas después de construirlas."""
        if not isinstance(ref, ArtifactRef):
            raise ArtifactStoreError("Se requiere una referencia ArtifactRef válida.")
        try:
            checked = ArtifactRef.model_validate(ref.model_dump(mode="python", warnings=False))
        except (ValidationError, ValueError, TypeError) as exc:
            raise ArtifactStoreError("La referencia del artefacto no es válida.") from exc
        if checked.relative_path != self._relative_path(checked.hash.value):
            raise ArtifactStoreError("La ruta declarada no corresponde al hash del contenido.")
        return checked

    def _read_verified(self, ref: ArtifactRef) -> bytes:
        """Lee un archivo regular y comprueba tamaño y digest de sus bytes."""
        target = self._target(ref.hash.value, create=False)
        if target.is_symlink():
            raise ArtifactIntegrityError("El artefacto no puede ser un enlace simbólico.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags)
        except OSError as exc:
            if target.is_symlink():
                raise ArtifactIntegrityError("El artefacto no puede ser un enlace simbólico.") from exc
            raise
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ArtifactIntegrityError("El artefacto debe ser un archivo regular.")
            data = source.read()
        if len(data) != ref.size_bytes or sha256_hex(data) != ref.hash.value:
            raise ArtifactIntegrityError("El contenido o tamaño del artefacto no coincide con su referencia.")
        return data

    def put_bytes(self, data: bytes, media_type: str | None = None) -> ArtifactRef:
        """Publica bytes sin reemplazar contenidos existentes ni perder idempotencia."""
        if not isinstance(data, bytes):
            raise TypeError("El artefacto debe proporcionarse como bytes.")
        if media_type is not None and (not isinstance(media_type, str) or not media_type.strip()):
            raise ValueError("El tipo MIME debe ser texto no vacío o None.")
        digest = sha256_hex(data)
        ref = ArtifactRef(
            hash=HashRef(algorithm="sha256", value=digest),
            relative_path=self._relative_path(digest),
            media_type=media_type,
            size_bytes=len(data),
        )
        target = self._target(digest, create=True)
        # Si existe, nunca se repara ni se reemplaza un objeto corrupto.
        if target.exists() or target.is_symlink():
            self._read_verified(ref)
            return ref

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".artifact-", dir=target.parent,
                                             delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # link() falla si otro escritor publicó antes: no existe ventana de truncado.
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError:
                pass
            self._read_verified(ref)
            return ref
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get_bytes(self, ref: ArtifactRef) -> bytes:
        """Devuelve bytes únicamente cuando la referencia coincide con su contenido."""
        return self._read_verified(self._checked_ref(ref))

    def exists(self, ref: ArtifactRef) -> bool:
        """Comprueba presencia e integridad, sin aceptar corrupción como ausencia."""
        checked = self._checked_ref(ref)
        try:
            self._read_verified(checked)
        except FileNotFoundError:
            return False
        return True
