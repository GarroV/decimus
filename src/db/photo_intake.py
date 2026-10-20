"""Приём кадра по ссылке загрузки: тип — по сигнатуре байт, а не по имени и заголовку клиента.

Имя файла и `Content-Type` приходят от того, кто шлёт, и ничего не доказывают.
Принимаются JPEG, PNG, WebP и HEIC/HEIF; сжатие до копии хранения (и перевод
HEIC в JPEG) делает `add_photo` тем же путём, что у кадров `import_add_photo`.
"""

from __future__ import annotations

#: Бренды ISO-BMFF (`ftyp`), под которыми живут HEIC/HEIF с телефонов.
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"})


def sniff_image(data: bytes) -> str | None:
    """`jpeg` / `png` / `webp` / `heic` по первым байтам — или `None`, если это не кадр."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "heic"
    return None
