"""The viewer page builds in each language and shows the result lines translated."""
import pytest

pytest.importorskip("trame")
pytest.importorskip("vtk")
pytestmark = pytest.mark.render

from trame.app import get_server  # noqa: E402

from aster_view import viewer  # noqa: E402


@pytest.mark.parametrize("lang, word", [("es", "Pintado"), ("en", "Shown"), ("fr", "Affiché")])
def test_build(example, lang, word):
    server, scene = viewer.build_app(example, "SIEF_ELGA", "SIRR", lang=lang,
                                     server=get_server(f"test_{lang}", client_type="vue3"))
    st = server.state
    assert st.info_txt.startswith(word) and st.pg_txt
    assert st.t["p_res"] == {"es": "Resultado", "en": "Result", "fr": "Résultat"}[lang]
    assert [i["value"] for i in st.reps] == ["surface", "surface_edges", "wireframe", "points"]
    scene.rw.Finalize()
