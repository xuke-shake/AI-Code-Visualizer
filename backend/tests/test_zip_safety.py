from __future__ import annotations

import io
import asyncio
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from app.core.exceptions import AppException
from app.tools.zip_safety import save_upload_zip, validate_zip_file


def _zip_bytes(entries: list[tuple[str, bytes]], compression: int = ZIP_STORED) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=compression) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return stream.getvalue()


def _symlink_zip_bytes() -> bytes:
    stream = io.BytesIO()
    info = ZipInfo("link.py")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        archive.writestr(info, b"target.py")
    return stream.getvalue()


def _encrypted_flag_zip_bytes() -> bytes:
    stream = io.BytesIO()
    info = ZipInfo("secret.py")
    info.flag_bits |= 0x1
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        archive.writestr(info, b"not actually encrypted")
    # zipfile may clear the flag when writing an entry; set it in both the
    # local header and central directory to model an encrypted member.
    data = bytearray(stream.getvalue())
    local_offset = data.find(b"PK\x03\x04")
    central_offset = data.find(b"PK\x01\x02")
    data[local_offset + 6] |= 0x01
    data[central_offset + 8] |= 0x01
    return bytes(data)


@pytest.mark.parametrize(
    "payload",
    [
        _zip_bytes([("../escape.py", b"x")]),
        _zip_bytes([("/absolute.py", b"x")]),
        _zip_bytes([("//server/share.py", b"x")]),
        _zip_bytes([("C:/drive.py", b"x")]),
        _zip_bytes([("a/./file.py", b"x")]),
        _zip_bytes([("a//file.py", b"x")]),
        _symlink_zip_bytes(),
        _encrypted_flag_zip_bytes(),
    ],
)
def test_validate_zip_rejects_unsafe_members(tmp_path: Path, payload: bytes):
    archive_path = tmp_path / "unsafe.zip"
    archive_path.write_bytes(payload)
    with pytest.raises(AppException):
        validate_zip_file(archive_path)


def test_validate_zip_rejects_duplicate_members(tmp_path: Path):
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        archive.writestr("same.py", b"one")
        archive.writestr("same.py", b"two")
    archive_path = tmp_path / "duplicate.zip"
    archive_path.write_bytes(stream.getvalue())

    with pytest.raises(AppException, match="重复成员"):
        validate_zip_file(archive_path)


def test_validate_zip_rejects_member_size_limit(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_zip_member_uncompressed_size_mb", 1)
    archive_path = tmp_path / "large.zip"
    archive_path.write_bytes(_zip_bytes([("large.py", b"x" * (1024 * 1024 + 1))]))

    with pytest.raises(AppException, match="单个文件解压大小"):
        validate_zip_file(archive_path)


def test_validate_zip_rejects_total_size_and_file_count_limits(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_zip_member_uncompressed_size_mb", 2)
    monkeypatch.setattr(settings, "max_zip_total_uncompressed_size_mb", 1)
    total_archive = tmp_path / "total-large.zip"
    total_archive.write_bytes(
        _zip_bytes([
            ("one.py", b"x" * (700 * 1024)),
            ("two.py", b"y" * (700 * 1024)),
        ])
    )
    with pytest.raises(AppException, match="总解压大小"):
        validate_zip_file(total_archive)

    monkeypatch.setattr(settings, "max_zip_files", 1)
    count_archive = tmp_path / "too-many-files.zip"
    count_archive.write_bytes(_zip_bytes([("one.py", b"x"), ("two.py", b"y")]))
    with pytest.raises(AppException, match="文件数"):
        validate_zip_file(count_archive)


def test_validate_zip_rejects_excessive_compression_ratio(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_zip_compression_ratio", 5.0)
    archive_path = tmp_path / "bomb.zip"
    archive_path.write_bytes(_zip_bytes([("repeat.py", b"A" * 100_000)], compression=ZIP_DEFLATED))

    with pytest.raises(AppException, match="压缩比"):
        validate_zip_file(archive_path)


class _ChunkedUpload:
    filename = "same-name.zip"

    def __init__(self, content: bytes, chunk_size: int = 7):
        self._stream = io.BytesIO(content)
        self._chunk_size = chunk_size
        self.read_calls = 0
        self.file = self  # UploadFile exposes the synchronous stream used by the worker.

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        return self._stream.read(min(size, self._chunk_size))


def test_save_upload_streams_to_random_final_key_and_cleans_failed_temp_files(test_database, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    content = _zip_bytes([("demo.py", b"print('ok')")])
    first_upload = _ChunkedUpload(content)
    first = asyncio.run(save_upload_zip(first_upload, user_id=7))
    second_upload = _ChunkedUpload(content)
    second = asyncio.run(save_upload_zip(second_upload, user_id=7))

    assert first_upload.read_calls > 2
    assert second_upload.read_calls > 2
    assert first["object_key"] != second["object_key"]
    assert first["filename"] == "same-name.zip"
    assert (settings.storage_path / first["object_key"]).exists()
    assert (settings.storage_path / second["object_key"]).exists()

    monkeypatch.setattr(settings, "max_upload_size_mb", 0)
    failed_upload = _ChunkedUpload(content)
    with pytest.raises(AppException, match="超过"):
        asyncio.run(save_upload_zip(failed_upload, user_id=7))
    upload_dir = settings.storage_path / "uploads" / "7"
    assert not any(item.name.startswith(".upload-") for item in upload_dir.iterdir())
