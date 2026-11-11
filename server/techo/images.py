from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from .errors import APIError

MAX_PIXELS = 50_000_000
FULL_EDGE = 1600
THUMB_EDGE = 400
FULL_QUALITY = 80
FULL_MIN_QUALITY = 60
FULL_TARGET_BYTES = 400 * 1024
THUMB_QUALITY = 70
ACCEPTED_FORMATS = ("JPEG", "PNG", "WEBP")
SRGB = ImageCms.createProfile("sRGB")


@dataclass(frozen=True)
class Rendition:
    data: bytes
    width: int
    height: int

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class ProcessedPhoto:
    full: Rendition
    thumb: Rendition

    @property
    def hash(self) -> str:
        return self.full.digest[:12]


def rejected(message: str) -> APIError:
    return APIError(400, "validation_error", message, field="file")


def _to_srgb(image: Image.Image) -> Image.Image:
    # Phones often embed Display P3; convert pixels before the profile is dropped.
    profile = image.info.get("icc_profile")
    if not profile or image.mode not in {"RGB", "RGBA"}:
        return image
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        return ImageCms.profileToProfile(image, source, SRGB, outputMode=image.mode)
    except (ImageCms.PyCMSError, OSError, ValueError):
        return image


def _flatten(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _clean_copy(image: Image.Image) -> Image.Image:
    # A fresh image carries no info dict: no EXIF, XMP, ICC or GPS can reach the encoder.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    return clean


def _encode(image: Image.Image, edge: int, quality: int, target: int | None = None) -> Rendition:
    resized = image.copy()
    resized.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    while True:
        buffer = io.BytesIO()
        resized.save(buffer, "WEBP", quality=quality, method=4)
        data = buffer.getvalue()
        if target is None or len(data) <= target or quality <= FULL_MIN_QUALITY:
            return Rendition(data, resized.width, resized.height)
        quality = max(FULL_MIN_QUALITY, quality - 5)


def process(raw: bytes) -> ProcessedPhoto:
    """Decode by content, orient, strip metadata and render full and thumb WebP files."""
    if not raw:
        raise rejected("file 不能为空")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(raw), formats=ACCEPTED_FORMATS)
            if image.format not in ACCEPTED_FORMATS:
                raise rejected("只支持 JPEG、PNG 或 WebP 图片")
            if image.width * image.height > MAX_PIXELS:
                raise rejected("图片像素总数不能超过 5000 万")
            image.load()
            oriented = ImageOps.exif_transpose(image)
            rgb = _clean_copy(_flatten(_to_srgb(oriented)))
    except APIError:
        raise
    except UnidentifiedImageError as exc:
        raise rejected("只支持 JPEG、PNG 或 WebP 图片") from exc
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
    ) as exc:
        # Truncated or corrupt files fail here; no partial image is accepted.
        raise rejected("图片无法解码，文件可能已损坏") from exc
    full = _encode(rgb, FULL_EDGE, FULL_QUALITY, FULL_TARGET_BYTES)
    thumb = _encode(rgb, THUMB_EDGE, THUMB_QUALITY)
    return ProcessedPhoto(full=full, thumb=thumb)
