"""Self-check for local key storage helpers."""

from io import BytesIO


def test_write_env_keys_local_only(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")

    user_data.write_env_keys(firecrawl_key="fc-test-secret", openrouter_key="")
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "FIRECRAWL_API_KEY=fc-test-secret" in text
    assert "OPENROUTER_API_KEY" not in text
    assert "never uploaded" in text.lower() or "ONLY on this PC" in text

    status = user_data.setup_status()
    assert status["has_firecrawl"] is True
    assert status["keys_local_only"] is True
    assert "fc-t" in status["firecrawl_masked"] or status["firecrawl_masked"].startswith("fc-")
    assert "test-secret" not in status["firecrawl_masked"]


def test_save_resume(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")
    path = user_data.save_resume_text("# Me\n\nDeveloper")
    assert path.exists()
    assert "Developer" in path.read_text(encoding="utf-8")


def _minimal_text_pdf(text: str) -> bytes:
    """Tiny PDF with a text stream (no OCR)."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    stream = content.encode("latin-1")
    objects = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("latin-1")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj)
    xref = out.tell()
    out.write(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.write(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return out.getvalue()


def test_save_resume_pdf_keeps_original_and_extracts_text(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")
    monkeypatch.setattr(user_data, "resume_pdf_path", lambda: tmp_path / "resume.pdf")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")

    data = _minimal_text_pdf("HelloResumePDF")
    result = user_data.save_resume_pdf(data, original_name="Mark_CV.pdf")
    assert (tmp_path / "resume.pdf").exists()
    assert (tmp_path / "resume.pdf").read_bytes().startswith(b"%PDF")
    assert "HelloResumePDF" in result["content"]
    assert "HelloResumePDF" in (tmp_path / "resume.md").read_text(encoding="utf-8")
    assert result["original_name"] == "Mark_CV.pdf"
