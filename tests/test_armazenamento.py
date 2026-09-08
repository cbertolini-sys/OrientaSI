import importlib
import os


def test_storage_padrao_e_s3_fora_dos_testes():
    anterior = dict(os.environ)
    os.environ.update({"S3_ENDPOINT": "http://minio:9000", "S3_BUCKET": "orientasi"})
    try:
        import config.settings

        settings = importlib.reload(config.settings)
        backend = settings.STORAGES["default"]["BACKEND"]
        assert backend == "storages.backends.s3.S3Storage"
        assert settings.STORAGES["default"]["OPTIONS"]["bucket_name"] == "orientasi"
    finally:
        os.environ.clear()
        os.environ.update(anterior)
        import config.settings

        importlib.reload(config.settings)


def test_fixture_isola_os_testes_do_bucket(settings):
    # A fixture autouse do conftest força FileSystemStorage: nenhum teste toca o MinIO.
    assert settings.STORAGES["default"]["BACKEND"] == (
        "django.core.files.storage.FileSystemStorage"
    )
