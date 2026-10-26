"""Escena VTK de un resultado MED: la usan el visor interactivo, las imágenes del MCP
y las figuras para paper.

Tubería: malla (celdas elegidas) -> deformada (DEPL x escala) -> umbral ("ok":
celdas sin valor, sin desplazamiento o fuera del umbral de valores) -> corte por
plano (recortar | sección | celdas enteras) -> superficie -> colores.
Los campos en puntos de Gauss se dibujan como promedio de los PG de cada celda.
"""
from __future__ import annotations

import json
import os
import warnings

import numpy as np
import vtk
from vtkmodules.util import numpy_support as ns

from .derived import Axis, derived_names, evaluate
from .i18n import canonical
from .medfile import MED_TYPES, MedError

# MED orienta los volúmenes al revés que VTK (verificado: volumen con signo
# negativo en HE8/H20 de code_aster). Permutaciones que invierten la celda
# conservando la topología de esquinas y aristas.
FLIP = {
    "HE8": [0, 3, 2, 1, 4, 7, 6, 5],
    "H20": [0, 3, 2, 1, 4, 7, 6, 5, 11, 10, 9, 8, 15, 14, 13, 12, 16, 19, 18, 17],
    "TE4": [0, 2, 1, 3],
    "T10": [0, 2, 1, 3, 6, 5, 4, 7, 9, 8],
    "PE6": [0, 2, 1, 3, 5, 4],
    "P15": [0, 2, 1, 3, 5, 4, 8, 7, 6, 11, 10, 9, 12, 14, 13],
    "PY5": [0, 3, 2, 1, 4],
    "P13": [0, 3, 2, 1, 4, 8, 7, 6, 5, 9, 12, 11, 10],
}
FLIP["H27"], FLIP["P18"] = FLIP["H20"], FLIP["P15"]
# tetraedro de control y signo que espera VTK (las cuñas de VTK miran "hacia afuera")
ORIENT = {"HE8": ((0, 1, 3, 4), 1), "H20": ((0, 1, 3, 4), 1), "H27": ((0, 1, 3, 4), 1),
          "TE4": ((0, 1, 2, 3), 1), "T10": ((0, 1, 2, 3), 1),
          "PY5": ((0, 1, 3, 4), 1), "P13": ((0, 1, 3, 4), 1),
          "PE6": ((0, 1, 2, 3), -1), "P15": ((0, 1, 2, 3), -1), "P18": ((0, 1, 2, 3), -1)}

# Mapas de colores: los de ParaView 5.11 muestreados (paraview_colormaps.json, 256
# colores exportados con pvpython), así coinciden con las figuras hechas en ParaView.
_PV = json.load(open(os.path.join(os.path.dirname(__file__), "paraview_colormaps.json")))
COLORMAPS = {
    "Cool to Warm": ("pv", "Cool to Warm"),
    "Cool to Warm (Extended)": ("pv", "Cool to Warm (Extended)"),
    "Blue Orange (divergent)": ("pv", "Blue Orange (divergent)"),
    "RdBu": ("mpl", "RdBu_r"),
    "Jet": ("pv", "Jet"),
    "Turbo": ("pv", "Turbo"),
    "Rainbow Uniform": ("pv", "Rainbow Uniform"),
    "Rainbow Desaturated": ("pv", "Rainbow Desaturated"),
    "Viridis": ("pv", "Viridis (matplotlib)"),
    "Inferno": ("pv", "Inferno (matplotlib)"),
    "Black-Body": ("pv", "Black-Body Radiation"),
    "Grayscale": ("pv", "Grayscale"),
}

# las opciones con nombre usan claves fijas; los rótulos de cada idioma están en i18n.py
BACKGROUNDS = {
    "light_gradient": ("#fafafc", "#ccd4e0"),
    "white": ("#ffffff", None),
    "light_gray": ("#e8e8ea", None),
    "paraview_gray": ("#525770", None),
    "dark_gradient": ("#3b4152", "#121419"),
    "black": ("#000000", None),
}
REPRESENTATIONS = ("surface", "surface_edges", "wireframe", "points")
CLIP_MODES = ("clip", "slice", "crinkle")

VIEWS = {"iso": (1, 1, 1), "+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0),
         "+z": (0, 0, 1), "-z": (0, 0, -1)}

SETTING_KEYS = ("field", "comp", "groups", "window", "warp_scale", "hide_nan", "clip_mode", "clip_origin",
                "clip_normal", "clip_invert", "context", "threshold", "cmap", "invert", "bands", "log",
                "range", "symmetric", "representation", "opacity", "shading", "background",
                "show_text", "show_bar", "show_triad", "bar_title", "edge_color", "edge_width",
                "show_nodes", "node_color", "node_size", "cell_reduce", "bar_pos", "bar_custom")

# cómo se pinta un campo en puntos de Gauss: un valor por elemento a partir de sus PG
CELL_REDUCE = ("mean", "min", "max", "absmax")


class _Choice:
    """Atributo de opción con nombre: guarda la clave aunque se le asigne el rótulo
    en otro idioma o el nombre de la v0.2 (vistas y recetas viejas)."""

    def __init__(self, kind, default):
        self.kind, self.default = kind, default

    def __set_name__(self, owner, name):
        self.attr = "_" + name

    def __get__(self, obj, owner=None):
        return self if obj is None else getattr(obj, self.attr, self.default)

    def __set__(self, obj, value):
        v = canonical(self.kind, value)
        if self.kind == "clip_mode" and v == "none":
            v = None
        setattr(obj, self.attr, v)


def oriented_conn(mtype, conn, coords):
    vt, dim, nn = MED_TYPES[mtype]
    c = conn[:, :nn]
    if mtype in ORIENT and len(c):
        (a, b, d, e), want = ORIENT[mtype]
        X = coords
        v = np.einsum("ij,ij->i", np.cross(X[c[:, b]] - X[c[:, a]], X[c[:, d]] - X[c[:, a]]),
                      X[c[:, e]] - X[c[:, a]])
        if np.sign(np.median(v)) == -want:
            c = c[:, FLIP[mtype][:nn]]
    return c


def colormap_rgb(name, n=256, invert=False):
    name = canonical("cmap", name)
    kind, src = COLORMAPS.get(name, ("mpl", name))
    t = (np.arange(n) + 0.5) / n if n < 256 else np.linspace(0, 1, n)
    if kind == "pv":
        base = np.asarray(_PV[src], float)
        g = np.linspace(0, 1, len(base))
        rgb = np.stack([np.interp(t, g, base[:, k]) for k in range(3)], axis=1)
    else:
        import matplotlib
        rgb = matplotlib.colormaps[src](t)[:, :3]
    return rgb[::-1] if invert else rgb


def lookup_table(cmap="Cool to Warm", bands=0, invert=False, log=False, rng=(0.0, 1.0)):
    n = int(bands) if bands and int(bands) > 1 else 256
    rgb = colormap_rgb(cmap, n, invert)
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(n)
    for i, c in enumerate(rgb):
        lut.SetTableValue(i, float(c[0]), float(c[1]), float(c[2]), 1.0)
    lut.SetNanColor(0.62, 0.62, 0.62, 1.0)
    if log:
        lut.SetScaleToLog10()
    lut.SetTableRange(*rng)
    lut.Build()
    return lut, rgb


def probe_grid(grid, points, tol):
    """Valor del arreglo "valor" de grid en los puntos -> (valores, encontrado).

    vtkProbeFilter con localizador de celdas (la búsqueda por defecto parte del nodo más
    cercano y pierde puntos cuando ese nodo es de otra pieza). Los puntos que no encuentra
    porque caen sobre una cara del borde (una línea sobre un plano de simetría con los nodos
    a 1e-15 del lado de afuera, o un punto tocado en pantalla sobre una cara curva dibujada
    con cuerdas) se buscan corriéndolos hasta 2*tol hacia adentro; los que siguen afuera
    quedan sin valor."""
    X = np.ascontiguousarray(points, dtype=float).reshape(-1, 3)
    P = vtk.vtkPoints()
    P.SetData(ns.numpy_to_vtk(X, deep=True))
    pd = vtk.vtkPolyData()
    pd.SetPoints(P)
    pr = vtk.vtkProbeFilter()
    pr.SetInputData(pd)
    pr.SetSourceData(grid)
    pr.SetCellLocator(vtk.vtkStaticCellLocator())
    pr.SetTolerance(float(tol))
    pr.ComputeToleranceOff()
    pr.Update()
    out = pr.GetOutput()
    v = ns.vtk_to_numpy(out.GetPointData().GetArray("valor")).astype(float)
    m = ns.vtk_to_numpy(out.GetPointData().GetArray(pr.GetValidPointMaskArrayName())).astype(bool)
    bad = np.flatnonzero(~m)
    pa, ca = grid.GetPointData().GetArray("valor"), grid.GetCellData().GetArray("valor")
    if len(bad) and grid.GetNumberOfCells() and (pa is not None or ca is not None):
        # se corre el punto 2*tol hacia el centro de las celdas de su nodo más cercano y se
        # acepta la primera que lo contiene. (FindClosestPoint no sirve: en celdas cuadráticas
        # EvaluatePosition no converge para puntos de afuera y elige otra celda lejana.)
        from vtkmodules.vtkCommonCore import reference
        pl = vtk.vtkStaticPointLocator()
        pl.SetDataSet(grid)
        pl.BuildLocator()
        ids = vtk.vtkIdList()
        for i in bad:
            grid.GetPointCells(pl.FindClosestPoint(X[i].tolist()), ids)
            for j in range(ids.GetNumberOfIds()):
                cid = ids.GetId(j)
                cell = grid.GetCell(cid)
                pts = cell.GetPoints()
                g = np.mean([pts.GetPoint(k) for k in range(pts.GetNumberOfPoints())], axis=0)
                d = g - X[i]
                y = X[i] + d * min(1.0, 2.0 * tol / (np.linalg.norm(d) or 1.0))
                w = [0.0] * cell.GetNumberOfPoints()
                if cell.EvaluatePosition(y.tolist(), [0.0] * 3, reference(0), [0.0] * 3, reference(0.0), w) != 1:
                    continue
                v[i] = (ca.GetValue(cid) if ca is not None
                        else sum(wk * pa.GetValue(cell.GetPointId(k)) for k, wk in enumerate(w)))
                m[i] = True
                break
    return v, m


def hex_rgb(h):
    h = str(h).lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _jsonable(v):
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, tuple):
        return list(v)
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    return v


class Scene:
    """Estado de visualización + tubería VTK + interacción (zoom, clic, plano)."""

    representation = _Choice("representation", "surface")
    clip_mode = _Choice("clip_mode", None)
    cell_reduce = _Choice("cell_reduce", "mean")
    background = _Choice("background", "light_gradient")
    cmap = _Choice("cmap", "Cool to Warm")
    bar_pos = _Choice("bar_pos", "right")

    def __init__(self, res, offscreen=True, size=(1400, 900)):
        # la escena trabaja con una sola malla: la vista del archivo desde esa malla
        self.res = res.view(res.mesh_name)
        self.mesh = self.res.mesh
        self.axis = Axis.auto(self.mesh)
        lo, hi = self.mesh.bbox()
        # estado (ver SETTING_KEYS)
        self.field = None
        self.comp = None
        self.step = -1
        self.groups = []
        self.window = None
        self.warp_scale = 0.0
        self.hide_nan = False
        self.edge_color = "#38383f"
        self.edge_width = 1.0
        self.show_nodes = False
        self.node_color = "#202024"
        self.node_size = 5.0
        self.cell_reduce = "mean"
        self.clip_mode = None
        self.clip_origin = (lo + hi) / 2
        self.clip_normal = np.array([1.0, 0.0, 0.0])
        self.clip_invert = False
        self.context = True
        self.threshold = None
        self.cmap = "Cool to Warm"
        self.invert = False
        self.bands = 0
        self.log = False
        self.range = None
        self.symmetric = False
        self.representation = "surface"
        self.opacity = 1.0
        self.shading = True
        self.background = "light_gradient"
        self.show_text = True
        self.show_bar = True
        self.show_triad = True
        self.bar_title = None
        self.bar_custom = None          # [x, y, ancho, alto, orientación] si se la arrastró
        self.title_extra = ""
        # interacción
        self.click_mode = "rotar"       # rotar | valor | centrar | acercar | plano
        self.on_click = None            # callback(modo, dict) que pone el visor
        self.on_plane = None            # callback(origen, normal) al soltar el plano
        self.on_bar = None              # callback() al soltar la barra de colores arrastrada
        self.picks = []                 # puntos de lectura: {"x0": [x, y, z]}
        self.last_range = (0.0, 1.0)
        self.last_rgb = None
        self.last_info = {}
        self._grid_cache = {}
        self._U = None

        self.ren = vtk.vtkRenderer()
        # luces como ParaView (principal, relleno, trasera y frontal) y antialiasing
        self.ren.AutomaticLightCreationOff()
        self.lightkit = vtk.vtkLightKit()
        self.lightkit.AddLightsToRenderer(self.ren)
        # más relleno que el de fábrica: el lado en sombra no se oscurece tanto y los
        # colores se siguen leyendo contra la barra
        self.lightkit.SetKeyLightIntensity(0.85)
        self.lightkit.SetKeyToFillRatio(1.6)
        self.lightkit.SetKeyToHeadRatio(1.8)
        self.lightkit.SetKeyToBackRatio(3.0)
        self.ren.UseFXAAOn()
        self.rw = vtk.vtkRenderWindow()
        self.rw.AddRenderer(self.ren)
        self.rw.SetSize(*size)
        if offscreen:
            self.rw.SetOffScreenRendering(1)
        self.iren = vtk.vtkRenderWindowInteractor()
        self.iren.SetRenderWindow(self.rw)
        self.style = vtk.vtkInteractorStyleTrackballCamera()
        self.iren.SetInteractorStyle(self.style)
        # con observadores propios, VTK NO llama al manejador por defecto del estilo
        self.style.AddObserver("MouseWheelForwardEvent", lambda o, e: self._wheel(1.12))
        self.style.AddObserver("MouseWheelBackwardEvent", lambda o, e: self._wheel(1 / 1.12))
        self.style.AddObserver("LeftButtonPressEvent", self._left_down)
        self.style.AddObserver("LeftButtonReleaseEvent", self._left_up)

        # --- tubería
        self.src = vtk.vtkTrivialProducer()
        self.src.SetOutput(vtk.vtkUnstructuredGrid())
        self.warp = vtk.vtkWarpVector()
        self.warp.SetInputConnection(self.src.GetOutputPort())
        self.warp.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "U")
        self.thresh = vtk.vtkThreshold()
        self.thresh.SetInputConnection(self.warp.GetOutputPort())
        self.thresh.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS, "ok")
        self.thresh.SetLowerThreshold(0.5)
        self.thresh.SetUpperThreshold(1.5)
        self.thresh.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_BETWEEN)
        self.plane = vtk.vtkPlane()
        self.clipper = vtk.vtkTableBasedClipDataSet()
        self.clipper.SetClipFunction(self.plane)
        self.clipper.SetInputConnection(self.thresh.GetOutputPort())
        # el de tablas no maneja celdas cuadráticas (H20): para esas, el general
        self.clipper_q = vtk.vtkClipDataSet()
        self.clipper_q.SetClipFunction(self.plane)
        self.clipper_q.SetInputConnection(self.thresh.GetOutputPort())
        self._nonlinear = False
        self.crinkle = vtk.vtkExtractGeometry()
        self.crinkle.SetImplicitFunction(self.plane)
        self.crinkle.ExtractBoundaryCellsOn()
        self.crinkle.SetInputConnection(self.thresh.GetOutputPort())
        self.cutter = vtk.vtkCutter()
        self.cutter.SetCutFunction(self.plane)
        self.cutter.SetInputConnection(self.thresh.GetOutputPort())
        self.surf = vtk.vtkDataSetSurfaceFilter()
        self.surf.SetNonlinearSubdivisionLevel(1)
        self.surf.SetInputConnection(self.thresh.GetOutputPort())
        # normales por punto: sombreado suave en superficies curvas (sin bandas por faceta);
        # las aristas de más de 45° se parten y siguen nítidas
        self.normals = vtk.vtkPolyDataNormals()
        self.normals.SetInputConnection(self.surf.GetOutputPort())
        self.normals.SetFeatureAngle(45.0)
        self.normals.SplittingOn()
        self.normals.ConsistencyOff()
        self.normals.ComputeCellNormalsOff()
        self.mapper = vtk.vtkPolyDataMapper()
        self.mapper.SetInputConnection(self.normals.GetOutputPort())
        self.mapper.InterpolateScalarsBeforeMappingOn()
        self.mapper.SetResolveCoincidentTopologyToPolygonOffset()
        self.actor = vtk.vtkActor()
        self.actor.SetMapper(self.mapper)
        self.ren.AddActor(self.actor)
        # aristas de los elementos: superficie sin subdividir (caras cuadráticas ->
        # polígonos por sus esquinas) en alambre; en "Alambre" se colorea con el campo
        self.surf0 = vtk.vtkDataSetSurfaceFilter()
        self.surf0.SetNonlinearSubdivisionLevel(0)
        self.surf0.SetInputConnection(self.thresh.GetOutputPort())
        self.edge_mapper = vtk.vtkPolyDataMapper()
        self.edge_mapper.SetInputConnection(self.surf0.GetOutputPort())
        self.edge_actor = vtk.vtkActor()
        self.edge_actor.SetMapper(self.edge_mapper)
        self.edge_actor.GetProperty().SetRepresentationToWireframe()
        self.edge_actor.GetProperty().LightingOff()
        self.edge_actor.VisibilityOff()
        self.ren.AddActor(self.edge_actor)
        # nodos de la superficie visible: caras de borde conservando las cuadráticas (así
        # entran los nodos intermedios de H20, no los puntos de la subdivisión) -> vértices.
        # Con campo en celdas se pasa a nodos (promedio) para poder colorear "Puntos".
        self.c2p = vtk.vtkCellDataToPointData()
        self.c2p.PassCellDataOn()
        self.ugeo = vtk.vtkUnstructuredGridGeometryFilter()
        self.ugeo.SetInputConnection(self.thresh.GetOutputPort())
        self.verts = vtk.vtkVertexGlyphFilter()
        self.verts.SetInputConnection(self.ugeo.GetOutputPort())
        self.node_mapper = vtk.vtkPolyDataMapper()
        self.node_mapper.SetInputConnection(self.verts.GetOutputPort())
        self.node_mapper.SetScalarModeToUsePointFieldData()
        self.node_mapper.SetResolveCoincidentTopologyToOff()  # con desplazamiento se colaban nodos de caras ocultas
        self.node_actor = vtk.vtkActor()
        self.node_actor.SetMapper(self.node_mapper)
        self.node_actor.GetProperty().SetRenderPointsAsSpheres(True)
        self.node_actor.VisibilityOff()
        self.ren.AddActor(self.node_actor)
        self._cell_field = False
        # contexto al cortar: el resto del modelo, gris translúcido
        self.ctx_surf = vtk.vtkDataSetSurfaceFilter()
        self.ctx_surf.SetInputConnection(self.thresh.GetOutputPort())
        self.ctx_mapper = vtk.vtkPolyDataMapper()
        self.ctx_mapper.SetInputConnection(self.ctx_surf.GetOutputPort())
        self.ctx_mapper.ScalarVisibilityOff()
        self.ctx_actor = vtk.vtkActor()
        self.ctx_actor.SetMapper(self.ctx_mapper)
        self.ctx_actor.GetProperty().SetColor(0.6, 0.6, 0.63)
        self.ctx_actor.GetProperty().SetOpacity(0.12)
        self.ctx_actor.VisibilityOff()
        self.ctx_actor.PickableOff()
        self.ren.AddActor(self.ctx_actor)
        # puntos leídos
        self.pick_pts = vtk.vtkPolyData()
        pm = vtk.vtkPolyDataMapper()
        pm.SetInputData(self.pick_pts)
        self.pick_actor = vtk.vtkActor()
        self.pick_actor.SetMapper(pm)
        self.pick_actor.GetProperty().SetRenderPointsAsSpheres(True)
        self.pick_actor.GetProperty().SetPointSize(12)
        self.pick_actor.GetProperty().SetColor(1.0, 0.85, 0.1)
        self.pick_actor.PickableOff()
        self.ren.AddActor(self.pick_actor)
        self.captions = []

        self.bar = vtk.vtkScalarBarActor()
        self.bar.SetNumberOfLabels(6)
        self.bar.SetLabelFormat("%-#.4g")
        self.bar.UnconstrainedFontSizeOn()
        for tp, fs in ((self.bar.GetTitleTextProperty(), 19), (self.bar.GetLabelTextProperty(), 15)):
            tp.ShadowOff()
            tp.ItalicOff()
            tp.BoldOff()
            tp.SetFontSize(fs)
        # la barra la maneja un widget: se arrastra y se estira con el mouse, como en ParaView
        # (al llevarla arriba o abajo se pone horizontal sola). Se dibuja con el widget prendido.
        self.bar_widget = vtk.vtkScalarBarWidget()
        self.bar_widget.SetInteractor(self.iren)
        self.bar_widget.SetScalarBarActor(self.bar)
        self.bar_widget.SetCurrentRenderer(self.ren)
        self.bar_widget.SetDefaultRenderer(self.ren)
        self.bar_rep = self.bar_widget.GetScalarBarRepresentation()
        self.bar_rep.SetShowBorderToActive()
        self._bar_dragging = False
        self.bar_widget.AddObserver("StartInteractionEvent", self._bar_grabbed)
        self.bar_widget.AddObserver("InteractionEvent", lambda o, e: self._bar_layout())
        # en horizontal el título va en un texto aparte: el de vtkScalarBarActor se monta
        # sobre los números
        self._bar_text = ""
        self.bar_title_actor = vtk.vtkTextActor()
        ttp = self.bar_title_actor.GetTextProperty()
        ttp.ShallowCopy(self.bar.GetTitleTextProperty())
        ttp.SetJustificationToCentered()
        ttp.SetVerticalJustificationToBottom()
        self.bar_title_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        self.bar_title_actor.VisibilityOff()
        self.bar_title_actor.PickableOff()
        self.ren.AddViewProp(self.bar_title_actor)
        self.bar_widget.AddObserver("EndInteractionEvent", self._bar_released)
        # ubicación recalculada en cada dibujo: en píxeles desde el borde, así en una vista
        # angosta (pestaña de VSCode) los números no se salen
        self.ren.AddObserver("StartEvent", self._place_bar)
        self.text = vtk.vtkTextActor()
        self.text.GetTextProperty().SetFontSize(16)
        self.text.SetPosition(12, 12)
        self.ren.AddViewProp(self.text)

        self.axes = vtk.vtkAxesActor()
        self.marker = vtk.vtkOrientationMarkerWidget()
        self.marker.SetOrientationMarker(self.axes)
        self.marker.SetInteractor(self.iren)
        self.marker.SetViewport(0.0, 0.08, 0.14, 0.30)
        self.marker.SetEnabled(1)
        self.marker.InteractiveOff()

        # plano arrastrable de tamaño fijo en pantalla (sirve en un tubo de 6 m)
        self.pw_rep = vtk.vtkDisplaySizedImplicitPlaneRepresentation()
        self.pw_rep.SetDrawOutline(False)
        self.pw_rep.SetConstrainToWidgetBounds(False)
        self.pw = vtk.vtkDisplaySizedImplicitPlaneWidget()
        self.pw.SetInteractor(self.iren)
        self.pw.SetRepresentation(self.pw_rep)
        self.pw.AddObserver("EndInteractionEvent", self._plane_moved)
        self.show_plane = False
        self._apply_background()

    # ============================================================ malla
    def cell_group_choices(self):
        """Grupos de celdas (los de mayor dimensión primero)."""
        m = self.mesh
        gs = [(m.group_dim(g), g) for g in m.cell_groups]
        return [g for d, g in sorted(gs, key=lambda x: (-x[0], x[1])) if d > 0]

    def _selection(self):
        m = self.mesh
        if self.groups:
            sel = {}
            for g in self.groups:
                for t, idx in m.group_cells(g).items():
                    sel[t] = np.union1d(sel.get(t, np.zeros(0, int)), idx)
        else:
            d = m.max_dim
            sel = {t: np.arange(b.ne) for t, b in m.blocks.items() if b.dim == d}
        if self.window is not None:
            # coordenada absoluta a lo largo del eje (con eje z: la z del centroide)
            a, b = self.window
            for t in list(sel):
                s = m.centroids(t)[sel[t]] @ self.axis.direction
                sel[t] = sel[t][(s >= a) & (s <= b)]
        return {t: i for t, i in sel.items() if len(i) and t in MED_TYPES}

    def _grid(self):
        win = tuple(self.window) if self.window is not None else None
        key = (tuple(self.groups), win, tuple(self.axis.point), tuple(self.axis.direction))
        if key in self._grid_cache:
            return self._grid_cache[key]
        m = self.mesh
        sel = self._selection()
        if not sel:
            raise MedError("No cells to show with these groups / this window")
        conns, types, sizes, cell_map = [], [], [], []
        for t, idx in sel.items():
            vt, dim, nn = MED_TYPES[t]
            c = oriented_conn(t, m.blocks[t].conn[idx], m.coords)
            conns.append(c)
            types.append(np.full(len(idx), vt, np.uint8))
            sizes.append(np.full(len(idx), c.shape[1], np.int64))
            cell_map.append((t, idx))
        conn = np.concatenate([c.ravel() for c in conns]).astype(np.int64)
        offsets = np.concatenate([[0], np.cumsum(np.concatenate(sizes))]).astype(np.int64)
        ca = vtk.vtkCellArray()
        ca.SetData(ns.numpy_to_vtkIdTypeArray(offsets, deep=True), ns.numpy_to_vtkIdTypeArray(conn, deep=True))
        pts = vtk.vtkPoints()
        pts.SetData(ns.numpy_to_vtk(np.ascontiguousarray(m.coords, dtype=float), deep=True))
        ug = vtk.vtkUnstructuredGrid()
        ug.SetPoints(pts)
        ug.SetCells(ns.numpy_to_vtk(np.concatenate(types), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR), ca)
        used = np.unique(conn)
        if len(self._grid_cache) > 6:
            self._grid_cache.clear()
        self._grid_cache[key] = (ug, cell_map, used, conns)
        return self._grid_cache[key]

    @staticmethod
    def _cells_all_finite(conns, node_ok):
        return np.concatenate([np.all(node_ok[c], axis=1) for c in conns])

    # ============================================================ campos
    def field_choices(self):
        return [f.short for f in self.res.fields.values()]

    def comp_choices(self, field):
        info = self.res.field(field)
        return info.components + derived_names(info.components, self.mesh.space_dim)

    def set_result(self, res):
        """Cambia de malla (archivo con varias): lo que depende de la malla vuelve a cero."""
        self.res = res.view(res.mesh_name)
        self.mesh = self.res.mesh
        self.axis = Axis.auto(self.mesh)
        lo, hi = self.mesh.bbox()
        self.clip_origin = (lo + hi) / 2
        self.field = self.comp = None
        self.groups, self.window, self.threshold, self.clip_mode = [], None, None, None
        self.picks, self._U, self.last_info = [], None, {}
        self._grid_cache.clear()

    def _displacement(self, time):
        try:
            info = self.res.field("DEPL")
        except MedError:
            return None
        fs = self.res.read(info.name, time=time)
        U = np.zeros((self.mesh.n_nodes, 3))
        for k, c in enumerate(("DX", "DY", "DZ")):
            if c in info.components:
                U[:, k] = fs.node[:, info.components.index(c)]
        return U, fs.step.time

    def _cell_values(self, vals, cell_map):
        """Un valor por elemento a partir de sus puntos de Gauss, según cell_reduce."""
        parts = []
        for t, idx in cell_map:
            if t not in vals:
                parts.append(np.full(len(idx), np.nan))
                continue
            a = vals[t][idx]
            with np.errstate(invalid="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)    # elementos sin valor (todo NaN)
                if self.cell_reduce == "min":
                    v = np.nanmin(a, axis=1)
                elif self.cell_reduce == "max":
                    v = np.nanmax(a, axis=1)
                elif self.cell_reduce == "absmax":
                    k = np.argmax(np.nan_to_num(np.abs(a), nan=-1.0), axis=1)
                    v = a[np.arange(len(a)), k]           # conserva el signo
                else:
                    v = np.mean(a, axis=1)
            parts.append(v)
        return np.concatenate(parts)

    def _gauss_extremes(self, vals, cell_map):
        """(min, max) en los puntos de Gauss de las celdas visibles."""
        lo, hi = np.inf, -np.inf
        for t, idx in cell_map:
            if t in vals and len(idx):
                a = vals[t][idx]
                a = a[np.isfinite(a)]
                if a.size:
                    lo, hi = min(lo, a.min()), max(hi, a.max())
        return (float(lo), float(hi)) if np.isfinite(lo) else (np.nan, np.nan)

    def range_all_steps(self):
        """(min, max) de la componente sobre las celdas visibles en TODOS los instantes."""
        ug, cell_map, used, conns = self._grid()
        info = self.res.field(self.field)
        lo, hi = np.inf, -np.inf
        for i in range(len(info.steps)):
            fs = self.res.read(info.name, step=i)
            vals = evaluate(self.res, fs, self.comp, self.axis)
            v = np.asarray(vals, float)[used] if fs.node is not None else self._cell_values(vals, cell_map)
            v = v[np.isfinite(v)]
            if v.size:
                lo, hi = min(lo, v.min()), max(hi, v.max())
        return (float(lo), float(hi)) if np.isfinite(lo) else (0.0, 1.0)

    def update(self):
        ug, cell_map, used, conns = self._grid()
        self._nonlinear = any(MED_TYPES[t][0] in (21, 22, 23, 24, 25, 26, 27) for t, _ in cell_map)
        pd, cd = ug.GetPointData(), ug.GetCellData()
        for d in (pd, cd):
            while d.GetNumberOfArrays():
                d.RemoveArray(0)
        info = {}
        t_now = None
        ncell = ug.GetNumberOfCells()
        ok = np.ones(ncell, bool)
        cellv = None
        if self.field:
            fs = self.res.read(self.field, step=self.step)
            t_now = fs.step.time
            vals = evaluate(self.res, fs, self.comp, self.axis)
            if fs.node is not None:
                arr = np.asarray(vals, float)
                shown = arr[used]
                pd.AddArray(self._vtk(arr, "valor"))
                self.mapper.SetScalarModeToUsePointFieldData()
                self.edge_mapper.SetScalarModeToUsePointFieldData()
                self._cell_field = False
                if self.hide_nan:
                    ok &= self._cells_all_finite(conns, np.isfinite(arr))
                if self.threshold is not None:
                    with np.errstate(invalid="ignore"):
                        cellv = np.concatenate([np.nanmean(arr[c], axis=1) for c in conns])
            else:
                arr = self._cell_values(vals, cell_map)
                shown = cellv = arr
                cd.AddArray(self._vtk(arr, "valor"))
                self.mapper.SetScalarModeToUseCellFieldData()
                self.edge_mapper.SetScalarModeToUseCellFieldData()
                self._cell_field = True
                if self.hide_nan:
                    ok &= np.isfinite(arr)
            if self.threshold is not None:
                a, b = self.threshold
                with np.errstate(invalid="ignore"):
                    ok &= (cellv >= a) & (cellv <= b)
            for mp in (self.mapper, self.edge_mapper, self.node_mapper):
                mp.SelectColorArray("valor")
            fin = shown[np.isfinite(shown)]
            lo, hi = (float(fin.min()), float(fin.max())) if fin.size else (0.0, 1.0)
            # ruido numérico (DX = -1e-23 en un plano de simetría): a la barra va como 0
            big = max(abs(lo), abs(hi))
            lo, hi = (0.0 if abs(lo) < 1e-12 * big else lo), (0.0 if abs(hi) < 1e-12 * big else hi)
            info = {"min": lo, "max": hi, "definidos": int(fin.size), "n": int(shown.size),
                    "tiempo": t_now, "paso": fs.index, "soporte": fs.info.support}
            if fs.node is None:
                # lo pintado es un valor por elemento; los extremos reales están en los PG
                info["reduccion"] = self.cell_reduce
                info["pg_min"], info["pg_max"] = self._gauss_extremes(vals, cell_map)
            if self.range is not None:
                lo, hi = float(self.range[0]), float(self.range[1])
            elif self.symmetric:
                m = max(abs(lo), abs(hi))
                lo, hi = -m, m
            if self.log and lo <= 0:
                lo = float(fin[fin > 0].min()) if (fin > 0).any() else 1e-12
            if hi <= lo:
                hi = lo + (abs(lo) * 1e-6 or 1e-12)
            self.last_range = (lo, hi)
            lut, self.last_rgb = lookup_table(self.cmap, self.bands, self.invert, self.log, (lo, hi))
            for mp in (self.mapper, self.edge_mapper, self.node_mapper):
                mp.SetLookupTable(lut)
                mp.UseLookupTableScalarRangeOn()
            self.bar.SetLookupTable(lut)
            self._bar_text = self.bar_title or self.comp
        info["celdas_umbral"] = int((~ok).sum()) if self.threshold is not None else 0

        # deformada: las celdas con nodos sin desplazamiento (fuera del modelo, cuando
        # AFFE_MODELE se restringe a algunos grupos) se ocultan; si no, quedarían quietas en su lugar
        U = None
        if self.warp_scale:
            d = self._displacement(t_now)
            if d is not None:
                U, tu = d
                ok &= self._cells_all_finite(conns, np.all(np.isfinite(U), axis=1))
                U = np.nan_to_num(U)
                info["deformada"] = f"DEPL x {self.warp_scale:g} (t = {tu:g})"
        self._U = U
        pd.AddArray(self._vtk(U if U is not None else np.zeros((self.mesh.n_nodes, 3)), "U"))
        self.warp.SetScaleFactor(self.warp_scale if U is not None else 0.0)
        cd.AddArray(self._vtk(ok.astype(float), "ok"))
        # número de celda: llega a cada polígono de la superficie dibujada (lectura con clic)
        cd.AddArray(self._vtk(np.arange(ncell, dtype=float), "cid"))
        info["celdas_ocultas"] = int((~ok).sum())

        self.src.SetOutput(ug)
        ug.Modified()
        self._apply_clip()
        self._apply_display()
        self._update_picks()
        name = os.path.basename(self.res.path)
        line = name
        if self.field:
            line += f"   |   {self.res.field(self.field).short}  {self.comp}   t = {t_now:g}"
        if self.title_extra:
            line += f"   |   {self.title_extra}"
        self.text.SetInput(line)
        self.last_info = info
        return info

    def _apply_clip(self):
        last = self.thresh
        mode = self.clip_mode
        if mode:
            n = np.asarray(self.clip_normal, float)
            n = n / (np.linalg.norm(n) or 1.0)
            self.plane.SetOrigin(*map(float, self.clip_origin))
            self.plane.SetNormal(*map(float, n))
            self.plane.Modified()
            if mode == "clip":
                last = self.clipper_q if self._nonlinear else self.clipper
                last.SetInsideOut(1 if self.clip_invert else 0)
            elif mode == "crinkle":
                self.crinkle.SetExtractInside(1 if self.clip_invert else 0)
                last = self.crinkle
            else:
                last = self.cutter
        self.surf.SetInputConnection(last.GetOutputPort())
        self.surf0.SetInputConnection(last.GetOutputPort())
        # nodos: campo en celdas -> a nodos; la sección ya es superficie (polydata)
        node_src = last
        if self._cell_field:
            self.c2p.SetInputConnection(last.GetOutputPort())
            node_src = self.c2p
        if mode == "slice":
            self.verts.SetInputConnection(node_src.GetOutputPort())
        else:
            self.ugeo.SetInputConnection(node_src.GetOutputPort())
            self.verts.SetInputConnection(self.ugeo.GetOutputPort())
        self.ctx_actor.SetVisibility(1 if (mode and self.context) else 0)
        if mode and self.show_plane:
            self._sync_plane_widget()
            self.pw.SetEnabled(1)
        else:
            self.pw.SetEnabled(0)

    def _apply_display(self):
        rep = self.representation
        p = self.actor.GetProperty()
        p.SetOpacity(float(self.opacity))
        if self.shading:
            p.SetInterpolationToGouraud()
            p.SetAmbient(0.08)
            p.SetDiffuse(0.92)
            p.SetSpecular(0.15)
            p.SetSpecularPower(30)
        else:  # sin sombreado: los colores son exactamente los de la barra
            p.SetAmbient(1.0)
            p.SetDiffuse(0.0)
            p.SetSpecular(0.0)
        colored = bool(self.field)
        self.mapper.SetScalarVisibility(colored)
        if not colored:
            p.SetColor(0.85, 0.85, 0.87)
        # como en ParaView: en "wireframe" y "points" las líneas/puntos llevan los colores
        # del campo; las aristas sobre la superficie y los nodos superpuestos, un color fijo
        ep = self.edge_actor.GetProperty()
        ep.SetOpacity(1.0)  # opacas: con transparencia los cruces quedan como puntos oscuros
        ep.SetLineWidth(float(self.edge_width))
        ep.SetColor(*hex_rgb(self.edge_color))
        npr = self.node_actor.GetProperty()
        npr.SetPointSize(float(self.node_size))
        npr.SetColor(*hex_rgb(self.node_color))
        self.actor.SetVisibility(1 if rep in ("surface", "surface_edges") else 0)
        self.edge_actor.SetVisibility(1 if rep in ("surface_edges", "wireframe") else 0)
        self.edge_mapper.SetScalarVisibility(colored and rep == "wireframe")
        self.node_actor.SetVisibility(1 if (rep == "points" or self.show_nodes) else 0)
        self.node_mapper.SetScalarVisibility(colored and rep == "points")
        on = 1 if (colored and self.show_bar) else 0
        if self.bar_widget.GetEnabled() != on:
            self.bar_widget.SetEnabled(on)
        self._bar_layout()
        self.text.SetVisibility(1 if self.show_text else 0)
        self.marker.SetEnabled(1 if self.show_triad else 0)
        if self.show_triad:
            self.marker.InteractiveOff()
        self._apply_background()

    # ------------------------------------------------------------ barra de colores
    def _place_bar(self, *_):
        """Posición según bar_pos: right / left / top / bottom (arriba y abajo, horizontal) o
        custom, la que dejó el usuario al arrastrarla. Se mide en píxeles donde importa."""
        W, H = self.rw.GetSize()
        if W <= 0 or H <= 0 or self._bar_dragging:
            return
        pos = self.bar_pos
        if pos == "custom" and self.bar_custom:
            x, y, w, h, o = self.bar_custom
        elif pos == "left":
            x, y, w, h, o = 0.02, 0.24, 0.08, 0.66, 1
        elif pos in ("top", "bottom"):
            h = min(0.15, 62.0 / H)
            x, w, o = 0.2, 0.6, 0
            y = 1.0 - h - 36.0 / H if pos == "top" else 0.03      # arriba: lugar para el título
        else:
            x, y, w, h, o = max(0.5, 1.0 - 135.0 / W), 0.12, 0.08, 0.72, 1
        self.bar.SetOrientation(int(o))
        self.bar_rep.SetPosition(x, y)
        self.bar_rep.SetPosition2(w, h)
        self._bar_layout()

    def _bar_layout(self):
        """Tope de tamaño en el sentido corto de la barra y título según la orientación."""
        horizontal = not self.bar.GetOrientation()
        if horizontal:
            self.bar.SetMaximumWidthInPixels(100000)
            self.bar.SetMaximumHeightInPixels(62)
        else:
            self.bar.SetMaximumWidthInPixels(90)
            self.bar.SetMaximumHeightInPixels(100000)
        self.bar.SetTitle(" " if horizontal else self._bar_text)
        show = horizontal and bool(self.bar_widget.GetEnabled())
        self.bar_title_actor.SetVisibility(1 if show else 0)
        if show:
            (x, y), (w, h) = self.bar_rep.GetPosition(), self.bar_rep.GetPosition2()
            H = max(self.rw.GetSize()[1], 1)
            self.bar_title_actor.SetInput(self._bar_text)
            self.bar_title_actor.SetPosition(x + w / 2, y + h + 4.0 / H)

    def _bar_grabbed(self, *_):
        self._bar_dragging = True

    def _bar_released(self, *_):
        self._bar_dragging = False
        x, y = self.bar_rep.GetPosition()
        w, h = (min(max(v, 0.02), 1.0) for v in self.bar_rep.GetPosition2())
        # que no quede afuera de la vista
        top = 1.0 - h - (36.0 / max(self.rw.GetSize()[1], 1) if not self.bar.GetOrientation() else 0.0)
        x, y = min(max(x, 0.0), 1.0 - w), min(max(y, 0.0), top)
        self.bar_custom = [float(x), float(y), float(w), float(h), int(self.bar.GetOrientation())]
        self.bar_pos = "custom"
        self._place_bar()
        self.rw.Render()
        if self.on_bar:
            self.on_bar()

    def _apply_background(self):
        bg = self.background
        c1, c2 = BACKGROUNDS.get(bg, (bg, None))
        r1 = hex_rgb(c1)
        self.ren.SetBackground(*r1)
        if c2:
            self.ren.GradientBackgroundOn()
            self.ren.SetBackground2(*hex_rgb(c2))
        else:
            self.ren.GradientBackgroundOff()
        lum = 0.2126 * r1[0] + 0.7152 * r1[1] + 0.0722 * r1[2]
        fg = (0.1, 0.1, 0.12) if lum > 0.5 else (0.95, 0.95, 0.95)
        for tp in (self.bar.GetTitleTextProperty(), self.bar.GetLabelTextProperty(), self.text.GetTextProperty(),
                   self.bar_title_actor.GetTextProperty()):
            tp.SetColor(*fg)
        for c in self.captions:
            c.GetCaptionTextProperty().SetColor(*fg)
            c.GetProperty().SetColor(*fg)
        self._fg = fg

    @staticmethod
    def _vtk(a, name):
        v = ns.numpy_to_vtk(np.ascontiguousarray(a, dtype=float), deep=True)
        v.SetName(name)
        return v

    # ============================================================ plano de corte
    def _sync_plane_widget(self):
        b = self.src.GetOutputDataObject(0).GetBounds()
        self.pw_rep.PlaceWidget(b)
        self.pw_rep.SetOrigin(*map(float, self.clip_origin))
        self.pw_rep.SetNormal(*map(float, self.clip_normal))

    def _plane_moved(self, obj, ev):
        self.clip_origin = np.array(self.pw_rep.GetOrigin())
        self.clip_normal = np.array(self.pw_rep.GetNormal())
        self.update()
        if self.on_plane:
            self.on_plane(self.clip_origin, self.clip_normal)

    def plane_preset(self, kind, value=None):
        """Normal y origen de presets: 'x','y','z', 'transversal' (normal = eje, en la
        coordenada axial value), 'longitudinal' (contiene al eje, ángulo value en grados),
        'camara' (normal a la mirada, por el punto focal)."""
        lo, hi = self.mesh.bbox()
        c = (lo + hi) / 2
        a = self.axis.direction
        if kind in ("x", "y", "z"):
            n = np.zeros(3)
            n["xyz".index(kind)] = 1.0
            o = c
        elif kind == "transversal":
            n = a.copy()
            o = self.axis.point + ((float(value) - self.axis.point @ a) * a if value is not None else 0)
        elif kind == "longitudinal":
            e1 = np.cross(a, [0, 1, 0]) if abs(a[1]) < 0.9 else np.cross(a, [1, 0, 0])
            e1 /= np.linalg.norm(e1)
            e2 = np.cross(a, e1)
            th = np.radians(float(value or 0))
            n = np.cos(th) * e1 + np.sin(th) * e2
            o = self.axis.point.copy()
        elif kind == "camara":
            cam = self.ren.GetActiveCamera()
            n = -np.array(cam.GetDirectionOfProjection())
            o = np.array(cam.GetFocalPoint())
        else:
            raise MedError(f"Unknown plane preset: {kind}")
        self.clip_normal, self.clip_origin = np.asarray(n, float), np.asarray(o, float)

    def plane_offset_range(self):
        """Rango de la posición del plano a lo largo de su normal (proyección de la caja)."""
        lo, hi = self.mesh.bbox()
        n = np.asarray(self.clip_normal, float)
        n = n / (np.linalg.norm(n) or 1.0)
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        s = corners @ n
        return float(s.min()), float(s.max()), float(np.asarray(self.clip_origin) @ n)

    def set_plane_offset(self, s):
        n = np.asarray(self.clip_normal, float)
        n = n / (np.linalg.norm(n) or 1.0)
        o = np.asarray(self.clip_origin, float)
        self.clip_origin = o + (float(s) - o @ n) * n

    # ============================================================ clic y lectura
    def _event_xy(self):
        return self.iren.GetEventPosition()

    def _left_down(self, obj, ev):
        if self.click_mode == "rotar":
            self.style.OnLeftButtonDown()
            return
        if self.click_mode == "mover":
            # la "mano" de ParaView: el botón izquierdo hace lo del botón del medio (desplazar)
            self.style.OnMiddleButtonDown()
            return
        x, y = self._event_xy()
        hit = self.pick_at(x, y)
        if hit is None:
            return
        mode = self.click_mode
        if mode == "valor":
            self.picks.append({"x0": hit["x0"]})
            self._update_picks()
        elif mode == "centrar":
            self.center_on(hit["pos"])
        elif mode == "acercar":
            self.center_on(hit["pos"])
            self.zoom(2.0)
        elif mode == "plano":
            self.clip_origin = np.asarray(hit["x0"] if self.warp_scale == 0 else hit["pos"], float)
            self.update()
        if self.on_click:
            self.on_click(mode, hit)
        self.rw.Render()

    def _left_up(self, obj, ev):
        if self.click_mode == "rotar":
            self.style.OnLeftButtonUp()
        elif self.click_mode == "mover":
            self.style.OnMiddleButtonUp()

    def pick_at(self, x, y):
        """Celda bajo el píxel (x, y): posición, posición sin deformar, celda y nodo."""
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.0005)
        picker.PickFromListOn()
        if self.actor.GetVisibility():
            picker.AddPickList(self.actor)
        elif self.representation == "points":
            picker.AddPickList(self.node_actor)
        else:
            picker.AddPickList(self.edge_actor)
        if not picker.Pick(x, y, 0, self.ren):
            return None
        pos = np.array(picker.GetPickPosition())
        x0 = pos.copy()
        if self._U is not None and self.warp_scale:
            # punto sin deformar: se descuenta el desplazamiento interpolado EN el punto tocado
            # (pesos del polígono de la superficie). Restar el U del nodo más cercano deja el
            # punto afuera de la pieza donde U varía mucho dentro del elemento (cerca de un agujero).
            u = self._u_at(picker.GetDataSet(), picker.GetCellId(), pos)
            if u is None:
                X = self.mesh.coords + self.warp_scale * self._U
                ug, cell_map, used, conns = self._grid()
                u = self._U[used[np.argmin(np.linalg.norm(X[used] - pos, axis=1))]]
            x0 = pos - self.warp_scale * u
        x0 = self._into_cell(picker.GetDataSet(), picker.GetCellId(), x0)
        return {"pos": pos.tolist(), "x0": x0.tolist()}

    def _into_cell(self, ds, pid, x0):
        """El punto tocado está sobre la superficie dibujada, que aproxima las caras curvas
        con cuerdas (puede quedar ~1e-2 afuera del material). Se lo mete apenas dentro de la
        celda de volumen de la que sale ese polígono, así la lectura (y la de otros instantes)
        lo encuentra siempre."""
        arr = ds.GetCellData().GetArray("cid") if ds is not None else None
        ug = self.src.GetOutputDataObject(0)
        if arr is None or pid < 0:
            return x0
        from vtkmodules.vtkCommonCore import reference
        cell = ug.GetCell(int(arr.GetTuple1(pid)))
        pts = cell.GetPoints()
        g = np.mean([pts.GetPoint(k) for k in range(pts.GetNumberOfPoints())], axis=0)
        w = [0.0] * cell.GetNumberOfPoints()
        for a in (0.0, 1e-3, 3e-3, 1e-2, 3e-2, 0.1, 0.3):
            y = x0 + a * (g - x0)
            if cell.EvaluatePosition(y.tolist(), [0.0] * 3, reference(0), [0.0] * 3, reference(0.0), w) == 1:
                return y
        return x0

    @staticmethod
    def _u_at(ds, cid, pos):
        """Desplazamiento "U" interpolado en pos dentro de la celda cid de ds (o None)."""
        arr = ds.GetPointData().GetArray("U") if ds is not None else None
        if arr is None or cid < 0:
            return None
        from vtkmodules.vtkCommonCore import reference
        cell = ds.GetCell(cid)
        w = [0.0] * cell.GetNumberOfPoints()
        cell.EvaluatePosition(list(pos), [0.0, 0.0, 0.0], reference(0), [0.0, 0.0, 0.0], reference(0.0), w)
        return sum(wk * np.array(arr.GetTuple3(cell.GetPointId(k))) for k, wk in enumerate(w))

    def probe(self, points):
        """Valor de la componente actual en puntos (geometría sin deformar)."""
        ug = self.src.GetOutputDataObject(0)
        if not self.field or ug.GetNumberOfCells() == 0:
            return np.full(len(points), np.nan)
        # los puntos tomados en pantalla caen sobre la superficie dibujada, que en celdas
        # cuadráticas aproxima los arcos con cuerdas (en un agujero queda ~1e-4 del radio
        # adentro del hueco): se aceptan hasta 0,1 % del tamaño de la pieza
        v, m = probe_grid(ug, points, 1e-3 * np.linalg.norm(np.subtract(*self.mesh.bbox())))
        v[~m] = np.nan
        return v

    def nearest_node(self, x0):
        ug, cell_map, used, conns = self._grid()
        k = used[np.argmin(np.linalg.norm(self.mesh.coords[used] - np.asarray(x0), axis=1))]
        return int(k) + 1

    def _update_picks(self):
        for c in self.captions:
            self.ren.RemoveViewProp(c)
        self.captions = []
        pts = vtk.vtkPoints()
        verts = vtk.vtkCellArray()
        if self.picks:
            X0 = np.array([p["x0"] for p in self.picks], float)
            vals = self.probe(X0)
            for i, (p, v) in enumerate(zip(self.picks, vals)):
                p["valor"] = float(v)
                p["nodo"] = self.nearest_node(p["x0"])
                pos = np.array(p["x0"])
                if self._U is not None and self.warp_scale:
                    pos = pos + self.warp_scale * self._U[p["nodo"] - 1]
                pts.InsertNextPoint(*pos)
                verts.InsertNextCell(1)
                verts.InsertCellPoint(i)
                cap = vtk.vtkCaptionActor2D()
                cap.SetAttachmentPoint(*pos)
                cap.SetCaption(f"{i + 1}: {v:.5g}")
                cap.BorderOff()
                cap.LeaderOn()
                cap.ThreeDimensionalLeaderOff()
                cap.SetPosition(18, 18)
                cap.SetWidth(0.12)
                cap.SetHeight(0.035)
                tp = cap.GetCaptionTextProperty()
                tp.SetFontSize(14)
                tp.ShadowOff()
                tp.BoldOff()
                tp.ItalicOff()
                cap.GetTextActor().SetTextScaleModeToNone()
                self.ren.AddViewProp(cap)
                self.captions.append(cap)
        self.pick_pts.SetPoints(pts)
        self.pick_pts.SetVerts(verts)
        self.pick_pts.Modified()
        self._apply_background()

    def clear_picks(self):
        self.picks = []
        self._update_picks()

    # ============================================================ cámara
    def _wheel(self, factor):
        x, y = self._event_xy()
        vtk.vtkInteractorStyle.DollyToPosition(factor, [x, y], self.ren)
        self.ren.ResetCameraClippingRange()
        self.rw.Render()

    def zoom(self, factor):
        cam = self.ren.GetActiveCamera()
        if cam.GetParallelProjection():
            cam.SetParallelScale(cam.GetParallelScale() / factor)
        else:
            cam.Dolly(factor)
        self.ren.ResetCameraClippingRange()

    def _depth_in_box(self, xa, ya, xb, yb, cx, cy):
        """Profundidad (z-buffer, 0..1) de la pieza en el centro del recuadro; si ahí no
        hay pieza, la mediana de la pieza visible dentro del recuadro; None si está vacío."""
        W, H = self.rw.GetSize()
        xa, xb = max(0, xa), min(W - 1, xb)
        ya, yb = max(0, ya), min(H - 1, yb)
        if xb <= xa or yb <= ya:
            return None
        self.rw.Render()
        zb = vtk.vtkFloatArray()
        self.rw.GetZbufferData(xa, ya, xb, yb, zb)
        z = ns.vtk_to_numpy(zb).reshape(yb - ya + 1, xb - xa + 1)
        zc = z[min(max(int(cy) - ya, 0), yb - ya), min(max(int(cx) - xa, 0), xb - xa)]
        if zc < 0.9999:
            return float(zc)
        geo = z[z < 0.9999]
        return float(np.median(geo)) if geo.size else None

    def zoom_box(self, x0, y0, x1, y1):
        """Zoom a un recuadro de la pantalla (píxeles de VTK, origen abajo a la izquierda),
        como "Zoom to Box" de ParaView. Lleva al centro el punto de la PIEZA que está en el
        centro del recuadro (profundidad leída del z-buffer) y acerca la cámara hasta que el
        recuadro llene la vista. Con perspectiva no alcanza con usar el plano del punto
        focal: en un tubo ese plano pasa por el eje, detrás de la pared que se mira, y el
        zoom se iba a otra zona. Un recuadro de menos de 5 px es un clic: ×2 en ese punto."""
        W, H = self.rw.GetSize()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w < 5 or h < 5:
            w, h = W / 2, H / 2
            xa, xb, ya, yb = int(cx) - 8, int(cx) + 8, int(cy) - 8, int(cy) + 8
        else:
            xa, xb = sorted((int(round(x0)), int(round(x1))))
            ya, yb = sorted((int(round(y0)), int(round(y1))))
        cam = self.ren.GetActiveCamera()
        z = self._depth_in_box(xa, ya, xb, yb, cx, cy)
        if z is None:  # recuadro sobre el fondo: el plano del punto focal
            self.ren.SetWorldPoint(*cam.GetFocalPoint(), 1.0)
            self.ren.WorldToDisplay()
            z = self.ren.GetDisplayPoint()[2]
        self.ren.SetDisplayPoint(cx, cy, z)
        self.ren.DisplayToWorld()
        p = np.array(self.ren.GetWorldPoint(), float)
        S = p[:3] / p[3]
        dop = np.array(cam.GetDirectionOfProjection(), float)
        f = max(w / W, h / H)            # fracción de la vista que ocupa el recuadro
        if cam.GetParallelProjection():
            dist = cam.GetDistance()
            cam.SetFocalPoint(*S)
            cam.SetPosition(*(S - dop * dist))
            cam.SetParallelScale(cam.GetParallelScale() * f)
        else:
            depth = float(np.dot(S - np.array(cam.GetPosition()), dop))   # distancia a S sobre la mirada
            cam.SetFocalPoint(*S)
            cam.SetPosition(*(S - dop * max(depth * f, 1e-9)))
        self.ren.ResetCameraClippingRange()

    def center_on(self, p):
        cam = self.ren.GetActiveCamera()
        d = np.asarray(p, float) - np.array(cam.GetFocalPoint())
        cam.SetFocalPoint(*(np.array(cam.GetFocalPoint()) + d))
        cam.SetPosition(*(np.array(cam.GetPosition()) + d))
        self.ren.ResetCameraClippingRange()

    def fit(self):
        self.ren.ResetCamera()
        self.ren.ResetCameraScreenSpace(0.92)

    def set_parallel(self, on):
        self.ren.GetActiveCamera().SetParallelProjection(1 if on else 0)
        self.fit()

    def set_view(self, view="iso", zoom=1.0):
        """Vistas fijas. "Arriba" se elige perpendicular a la mirada y al eje
        largo, así un tubo largo queda acostado en la pantalla. En una malla 2D (plano xy)
        "iso" es la vista de frente y arriba es +y, como se dibuja un modelo plano."""
        planar = self.mesh.space_dim == 2
        if planar and view == "iso":
            view = "+z"
        d = np.array(VIEWS.get(view, VIEWS["iso"]), float)
        d /= np.linalg.norm(d)
        main = self.axis.direction
        up = np.array([0.0, 1.0, 0.0]) if planar and view in ("+z", "-z") else None
        for cand in (() if up is not None else ((0, 1, 0), (0, 0, 1), (1, 0, 0))):
            c = np.array(cand, float)
            if abs(c @ d) < 0.9 and abs(c @ main) < 0.9:
                up = c
                break
        if up is None:
            up = next(np.array(c, float) for c in ((0, 1, 0), (0, 0, 1), (1, 0, 0)) if abs(np.dot(c, d)) < 0.9)
        lo, hi = self.mesh.bbox()
        ext = np.sort(hi - lo)
        if view == "iso" and ext[1] > 0 and ext[2] / ext[1] > 5:
            # pieza esbelta (un tubo largo): casi de costado y apenas oblicua
            side = np.cross(main, up)
            d = 0.25 * main + 0.45 * up + side
            d /= np.linalg.norm(d)
        cam = self.ren.GetActiveCamera()
        cam.SetFocalPoint(0, 0, 0)
        cam.SetPosition(*d)
        cam.SetViewUp(*up)
        self.fit()
        cam.Zoom(zoom)

    def camera_get(self):
        c = self.ren.GetActiveCamera()
        return {"position": list(c.GetPosition()), "focal_point": list(c.GetFocalPoint()),
                "view_up": list(c.GetViewUp()), "view_angle": c.GetViewAngle(),
                "parallel": bool(c.GetParallelProjection()), "parallel_scale": c.GetParallelScale()}

    def camera_set(self, d):
        c = self.ren.GetActiveCamera()
        c.SetPosition(*d["position"])
        c.SetFocalPoint(*d["focal_point"])
        c.SetViewUp(*d["view_up"])
        c.SetViewAngle(d.get("view_angle", 30.0))
        c.SetParallelProjection(1 if d.get("parallel") else 0)
        c.SetParallelScale(d.get("parallel_scale", 1.0))
        self.ren.ResetCameraClippingRange()

    # ============================================================ estado
    def get_settings(self):
        d = {k: _jsonable(getattr(self, k)) for k in SETTING_KEYS}
        if self.field:
            info = self.res.field(self.field)
            d["field"] = info.short
            d["time"] = info.steps[info.step_index(self.step)].time
        d["axis"] = {"point": self.axis.point.tolist(), "direction": self.axis.direction.tolist()}
        d["camera"] = self.camera_get()
        d["size"] = list(self.rw.GetSize())
        d["picks"] = [p["x0"] for p in self.picks]
        d["med"] = self.res.path
        d["mesh"] = self.res.mesh_name
        return d

    def apply_settings(self, d):
        for k in SETTING_KEYS:
            if k in d:
                v = d[k]
                if k in ("clip_origin", "clip_normal") and v is not None:
                    v = np.asarray(v, float)
                if k in ("window", "threshold", "range") and v is not None:
                    v = tuple(v)
                setattr(self, k, v)
        if self.field:
            info = self.res.field(self.field)
            self.field = info.name
            self.step = info.step_index(time=d["time"]) if "time" in d else -1
        if "axis" in d:
            self.axis = Axis.make(self.mesh, d["axis"]["point"], d["axis"]["direction"])
        self.picks = [{"x0": list(p)} for p in d.get("picks", [])]
        info = self.update()
        if "camera" in d:
            self.camera_set(d["camera"])
        return info

    # ============================================================ imágenes
    def screenshot(self, path, size=None):
        if size:
            self.rw.SetSize(*size)
        self.rw.Render()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(self.rw)
        w2i.ReadFrontBufferOff()
        w2i.Update()
        wr = vtk.vtkPNGWriter()
        wr.SetFileName(path)
        wr.SetInputConnection(w2i.GetOutputPort())
        wr.Write()
        return path

    def render_paper(self, w_px, h_px, shading=False, background="#ffffff"):
        """Imagen RGB (h, w, 3) sólo con la geometría, para componer una figura: sin textos,
        barra, triedro, plano ni etiquetas; fondo liso y, por defecto, sin sombreado
        (los colores quedan exactamente como en la barra)."""
        keep = dict(size=self.rw.GetSize(), bg=self.background, text=self.show_text, bar=self.show_bar,
                    triad=self.show_triad, shading=self.shading, plane=self.show_plane,
                    ew=self.edge_width, ns=self.node_size)
        cam = self.camera_get()
        caps = [c.GetVisibility() for c in self.captions]
        try:
            self.background, self.show_text, self.show_bar, self.show_triad = background, False, False, False
            self.shading, self.show_plane = shading, False
            # líneas y puntos en píxeles: escalarlos con la resolución para que la figura
            # se vea igual que la pantalla
            k = float(w_px) / max(keep["size"][0], 1)
            self.edge_width, self.node_size = keep["ew"] * k, keep["ns"] * k
            self._apply_display()
            self.pw.SetEnabled(0)
            for c in self.captions:
                c.VisibilityOff()
            self.pick_actor.VisibilityOff()
            self.rw.SetSize(int(w_px), int(h_px))
            self.camera_set(cam)
            self.rw.Render()
            w2i = vtk.vtkWindowToImageFilter()
            w2i.SetInput(self.rw)
            w2i.ReadFrontBufferOff()
            w2i.Update()
            im = w2i.GetOutput()
            w, h, _ = im.GetDimensions()
            img = ns.vtk_to_numpy(im.GetPointData().GetScalars()).reshape(h, w, -1)[::-1, :, :3].copy()
            ps = self.ren.GetActiveCamera().GetParallelScale()
            return img, (2 * ps / h if self.ren.GetActiveCamera().GetParallelProjection() else None)
        finally:
            self.background, self.show_text, self.show_bar = keep["bg"], keep["text"], keep["bar"]
            self.show_triad, self.shading, self.show_plane = keep["triad"], keep["shading"], keep["plane"]
            self.edge_width, self.node_size = keep["ew"], keep["ns"]
            for c, v in zip(self.captions, caps):
                c.SetVisibility(v)
            self.pick_actor.VisibilityOn()
            self.rw.SetSize(*keep["size"])
            self._apply_display()
            self._apply_clip()
            self.camera_set(cam)
