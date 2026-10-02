"""Safe image preprocessing for newly uploaded task files."""

from io import BytesIO
import logging
from os.path import splitext
import warnings

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError


logger = logging.getLogger(__name__)

_MAX_IMAGE_PIXELS = 60_000_000
_MAX_SIDE = 1600
_IMAGE_FORMATS = {"JPG": "JPEG", "JPEG": "JPEG", "PNG": "PNG"}
_IMAGE_EXTENSIONS = {
    "JPEG": {"jpg", "jpeg"},
    "PNG": {"png"},
}


def _read_upload(uploaded_file):
    if not hasattr(uploaded_file, "read"):
        return None
    try:
        uploaded_file.seek(0)
        data = uploaded_file.read()
        uploaded_file.seek(0)
    except (AttributeError, OSError, ValueError) as exc:
        raise ValidationError("No fue posible leer la imagen subida.") from exc
    if not isinstance(data, bytes):
        raise ValidationError("El archivo subido no contiene bytes válidos.")
    return data


def _load_validated_image(data, expected_format):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as inspected:
                actual_format = (inspected.format or "").upper()
                if actual_format != expected_format:
                    raise ValidationError("El contenido de la imagen no coincide con su formato declarado.")
                inspected.verify()

            image = Image.open(BytesIO(data))
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
                image.close()
                raise ValidationError("La imagen supera el límite de dimensiones permitido.")
            image.load()
            return image
    except ValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ValidationError("La imagen no es válida o no se puede decodificar.") from exc


def _processed_name(name, expected_format):
    if not name:
        return name
    extension = ".png" if expected_format == "PNG" else ".jpg"
    stem = name.rsplit(".", 1)[0] if "." in name.rsplit("/", 1)[-1] else name
    current_extension = name.rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""
    if expected_format == "PNG" and current_extension == "png":
        return name
    if expected_format == "JPEG" and current_extension in {"jpg", "jpeg"}:
        return name
    return f"{stem}{extension}"


def _as_uploaded_file(uploaded_file, data, expected_format):
    buffer = BytesIO(data)
    content_type = "image/png" if expected_format == "PNG" else "image/jpeg"
    return InMemoryUploadedFile(
        file=buffer,
        field_name=getattr(uploaded_file, "field_name", None),
        name=_processed_name(getattr(uploaded_file, "name", ""), expected_format),
        content_type=content_type,
        size=len(data),
        charset=getattr(uploaded_file, "charset", None),
    )


def optimize_uploaded_image(uploaded_file, declared_format):
    """Validate and optimize a new JPG/JPEG/PNG upload in memory.

    Non-image formats and non-uploaded file values are returned untouched so
    existing test fixtures and document paths retain their current contract.
    """
    expected_format = _IMAGE_FORMATS.get(str(declared_format or "").upper())
    if expected_format is None:
        return uploaded_file

    extension = splitext(getattr(uploaded_file, "name", ""))[1].lower().lstrip(".")
    if extension not in _IMAGE_EXTENSIONS[expected_format]:
        return uploaded_file

    data = _read_upload(uploaded_file)
    if data is None:
        return uploaded_file

    image = _load_validated_image(data, expected_format)
    original_dimensions = image.size
    try:
        try:
            processed = ImageOps.exif_transpose(image)
            if max(processed.size) > _MAX_SIDE:
                processed.thumbnail((_MAX_SIDE, _MAX_SIDE), Image.Resampling.LANCZOS)

            if expected_format == "JPEG":
                processed = processed.convert("RGB")
                output_format = "JPEG"
                save_options = {"quality": 82, "optimize": True, "progressive": True}
            else:
                output_format = "PNG"
                save_options = {"optimize": True}

            output = BytesIO()
            processed.save(output, format=output_format, **save_options)
            return _as_uploaded_file(uploaded_file, output.getvalue(), expected_format)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "Image optimization failed; preserving validated original: format=%s bytes=%s dimensions=%sx%s",
                expected_format,
                len(data),
                original_dimensions[0],
                original_dimensions[1],
            )
            return uploaded_file
    finally:
        image.close()
