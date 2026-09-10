from conftest import AMBIENTE_PRODUCAO, carrega_settings

S3 = "storages.backends.s3.S3Storage"
LOCAL = "django.core.files.storage.FileSystemStorage"


def test_storage_padrao_e_s3_fora_dos_testes():
    settings = carrega_settings(S3_ENDPOINT="http://minio:9000", S3_BUCKET="orientasi")
    assert settings.STORAGES["default"]["BACKEND"] == S3
    assert settings.STORAGES["default"]["OPTIONS"]["bucket_name"] == "orientasi"


def test_producao_usa_s3_mesmo_sem_endpoint_configurado():
    """O ramo que ninguém exercitava (achado da revisão final): `S3_ENDPOINT`
    existe porque o MinIO precisa de um endpoint próprio, mas a AWS S3 real
    não precisa de nenhum. A seleção antiga (`if os.environ.get("S3_ENDPOINT")`)
    fazia um deploy correto contra a AWS cair em SILÊNCIO no
    `FileSystemStorage` — fotos, PDFs e `.docx` gravados no disco efêmero do
    container e perdidos no primeiro restart, sem erro. Quem decide o backend
    agora é o `AMBIENTE`; o `endpoint_url` é opcional (`None` = endpoint
    padrão da AWS)."""
    ambiente = dict(AMBIENTE_PRODUCAO)
    ambiente["S3_ENDPOINT"] = ""
    settings = carrega_settings(**ambiente)

    assert settings.STORAGES["default"]["BACKEND"] == S3
    assert settings.STORAGES["default"]["OPTIONS"]["endpoint_url"] is None
    assert settings.STORAGES["default"]["OPTIONS"]["access_key"] == "chave-de-acesso"


def test_dev_sem_minio_cai_para_o_disco_local():
    """O fallback local sobrevive, mas só para `dev` sem MinIO: quem roda a
    stack completa tem `S3_ENDPOINT` no `.env.example`."""
    settings = carrega_settings(AMBIENTE="dev", S3_ENDPOINT="")
    assert settings.STORAGES["default"]["BACKEND"] == LOCAL


def test_fixture_isola_os_testes_do_bucket(settings):
    # A fixture autouse do conftest força FileSystemStorage: nenhum teste toca o MinIO.
    assert settings.STORAGES["default"]["BACKEND"] == LOCAL
