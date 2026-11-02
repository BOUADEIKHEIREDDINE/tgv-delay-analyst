"""Tests for scripts/download_data.py (R2).

No network: urlretrieve (the function that downloads the file) is replaced
by a fake that records the URL and writes a small file, and the output goes
to a temporary folder instead of data/raw/.
The real download is checked by following the README on a fresh clone (R1).
"""

import download_data


def test_url_is_the_sncf_dataset_with_semicolons():
    assert download_data.URL.startswith("https://ressources.data.sncf.com/")
    assert "regularite-mensuelle-tgv-aqst" in download_data.URL
    assert download_data.URL.endswith("delimiter=%3B")  # ";" separator, what load_raw expects


def test_output_is_where_clean_data_reads_it():
    import clean_data

    assert download_data.OUTPUT_FILE == clean_data.RAW_FILE


def test_main_downloads_into_raw_folder(monkeypatch, tmp_path, capsys):
    raw_dir = tmp_path / "data" / "raw"  # does not exist yet: main() must create it
    output = raw_dir / "regularite-mensuelle-tgv-aqst.csv"
    monkeypatch.setattr(download_data, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(download_data, "RAW_DIR", raw_dir)
    monkeypatch.setattr(download_data, "OUTPUT_FILE", output)

    downloads = []

    def fake_urlretrieve(url, filename):
        downloads.append((url, filename))
        filename.write_text("date;service\n2024-01;National\n", encoding="utf-8")

    monkeypatch.setattr(download_data, "urlretrieve", fake_urlretrieve)
    download_data.main()

    assert downloads == [(download_data.URL, output)]  # one download, to the right file
    assert output.exists()
    printed = capsys.readouterr().out
    assert f"Downloading {download_data.URL}" in printed
    assert "Saved to data/raw/regularite-mensuelle-tgv-aqst.csv" in printed  # relative path, no home folder


def test_main_works_when_the_folder_already_exists(monkeypatch, tmp_path):
    """Running the script twice must not fail (exist_ok=True)."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)
    monkeypatch.setattr(download_data, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(download_data, "RAW_DIR", raw_dir)
    monkeypatch.setattr(download_data, "OUTPUT_FILE", raw_dir / "file.csv")
    monkeypatch.setattr(download_data, "urlretrieve", lambda url, filename: filename.write_text("x"))
    download_data.main()
    download_data.main()
    assert (raw_dir / "file.csv").read_text() == "x"
