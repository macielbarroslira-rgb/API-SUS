import pytest

from app.catalogo import ErroCatalogo, montar_datasets
from tests.conftest import SPEC


def test_monta_bases_somente_get():
    ds = montar_datasets(SPEC)
    assert set(ds) == {"arboviroses-dengue", "cnes-estabelecimentos", "cnes-estabelecimentos-codigo_cnes"}


def test_resolve_refs_de_parametros_e_resposta():
    dengue = montar_datasets(SPEC)["arboviroses-dengue"]
    assert dengue.grupo == "Agravo Arboviroses"
    assert [p.nome for p in dengue.parametros] == ["nu_ano", "id_municip", "limit", "offset"]
    assert dengue.paginavel
    assert dengue.chave_lista == "dengue"
    assert [c.nome for c in dengue.campos] == ["dt_notific", "id_municip", "classi_fin"]
    assert dengue.campos[0].tipo == "string (date)"


def test_parametro_de_caminho_e_obrigatorio():
    ds = montar_datasets(SPEC)["cnes-estabelecimentos-codigo_cnes"]
    p = ds.parametro("codigo_cnes")
    assert p.local == "path" and p.obrigatorio
    assert not ds.paginavel


def test_openapi3():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/vacinas": {
                "get": {
                    "parameters": [{"name": "ano", "in": "query", "schema": {"type": "integer", "enum": [2023, 2024]}}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "array", "items": {"$ref": "#/components/schemas/Dose"}}
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {"schemas": {"Dose": {"properties": {"vacina": {"type": "string"}}}}},
    }
    ds = montar_datasets(spec)["vacinas"]
    assert ds.parametros[0].tipo == "integer" and ds.parametros[0].enum == [2023, 2024]
    assert [c.nome for c in ds.campos] == ["vacina"]
    assert ds.chave_lista is None


def test_spec_invalida():
    with pytest.raises(ErroCatalogo):
        montar_datasets({"swagger": "2.0"})
