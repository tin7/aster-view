"""MCP server end to end over stdio, on the example."""
import asyncio
import os
import sys

import pytest

pytest.importorskip("mcp")
pytest.importorskip("vtk")
pytestmark = pytest.mark.render

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def _run(example, out):
    env = dict(os.environ, ASTER_VIEW_OUT=str(out))
    params = StdioServerParameters(command=sys.executable, args=["-m", "aster_view.server"], env=env)
    results = {}
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            calls = {
                "med_info": {"path": example},
                "med_steps": {"path": example, "field": "DEPL"},
                "med_stats": {"path": example, "field": "SIEF_ELGA", "component": "SIRR"},
                "med_history": {"path": example, "field": "DEPL", "component": "DR", "group": "Inner"},
                "med_line": {"path": example, "field": "SIEF_ELGA", "component": "SITT",
                             "p0": [50, 0.5, 50], "p1": [60, 0.5, 50], "n": 20},
                "med_extract": {"path": example, "field": "DEPL", "components": ["DR"], "group": "Inner"},
                "med_render": {"path": example, "field": "SIEF_ELGA", "component": "SIRR",
                               "clip_mode": "slice", "clip_axis": "z", "clip_value": 50,
                               "representation": "Superficie con aristas", "cell_reduce": "min"},
                "med_figure": {"path": example, "field": "SIEF_ELGA", "component": "SITT", "view": "+z",
                               "label": r"$\sigma_\theta$ (MPa)", "bar": "vertical"},
                "med_to_vtu": {"path": example, "steps": "all"},
            }
            for name, args in calls.items():
                results[name] = await s.call_tool(name, args)
            results["bad"] = await s.call_tool("med_stats", {"path": example, "field": "TEMP", "component": "X"})
    return names, results


def test_tools(example, tmp_path):
    names, res = asyncio.run(_run(example, tmp_path / "out"))
    assert {"med_info", "med_render", "med_figure", "med_view", "med_to_vtu"} <= names
    for name, r in res.items():
        if name != "bad":
            assert not r.is_error, (name, r.content[0].text)
    text = {k: v.content[0].text for k, v in res.items()}
    assert "SIEF_ELGA" in text["med_info"] and "| 5 |" in text["med_info"]
    assert "At the Gauss points" in text["med_render"]
    assert ".pdf" in text["med_figure"] and "includegraphics" in text["med_figure"]
    assert any(c.type == "image" for c in res["med_render"].content)
    assert res["bad"].is_error and "No field" in res["bad"].content[0].text
    assert (tmp_path / "out" / "tube_resu" / "vtu" / "tube_resu.pvd").exists()
