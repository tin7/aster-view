"""Idiomas del visor (español, English, français) y opciones con nombre.

- UI: textos de la página, por clave; ui_table(lang) es lo que recibe la página.
- CHOICES: las opciones de las listas (representación, corte, fondo...). El valor
  interno es una clave fija en inglés ("surface_edges"); canonical() acepta además
  el rótulo en cualquier idioma y los nombres de la v0.2 (vistas y recetas viejas).
- El idioma elegido en el visor se recuerda en ~/.config/aster-view/config.json.
"""
from __future__ import annotations

import json
import locale
import os

LANGS = {"es": "Español", "en": "English", "fr": "Français"}
DEFAULT_LANG = "en"

UI = {
    # barra de arriba
    "tip_rotate": ("Clic: rotar (normal)", "Click: rotate (default)", "Clic : rotation (par défaut)"),
    "tip_pan": ("Mano: arrastrar para desplazar la pieza sin rotarla",
                "Hand: drag to move the part without rotating it",
                "Main : glisser pour déplacer la pièce sans la faire tourner"),
    "tip_probe": ("Clic: leer el valor en un punto", "Click: read the value at a point",
                  "Clic : lire la valeur en un point"),
    "tip_center": ("Clic: centrar la vista en ese punto", "Click: center the view on that point",
                   "Clic : centrer la vue sur ce point"),
    "tip_zoombox": ("Lupa: arrastrá un recuadro sobre la zona a ampliar (clic simple = ×2)",
                    "Magnifier: drag a box over the area to enlarge (single click = ×2)",
                    "Loupe : tracez un rectangle sur la zone à agrandir (clic simple = ×2)"),
    "tip_plane": ("Clic: poner el plano de corte ahí", "Click: put the cutting plane there",
                  "Clic : placer le plan de coupe ici"),
    "tip_zoom_in": ("Acercar", "Zoom in", "Zoom avant"),
    "tip_zoom_out": ("Alejar", "Zoom out", "Zoom arrière"),
    "tip_fit": ("Encuadrar lo visible", "Fit what is visible", "Recadrer sur le visible"),
    "tip_parallel": ("Proyección paralela / perspectiva", "Parallel / perspective projection",
                     "Projection parallèle / perspective"),
    "tip_edges": ("Ver los elementos (superficie con aristas)", "Show the elements (surface with edges)",
                  "Afficher les éléments (surface avec arêtes)"),
    "tip_nodes": ("Ver los nodos", "Show the nodes", "Afficher les nœuds"),
    "tip_png": ("Guardar PNG de la vista", "Save a PNG of the view", "Enregistrer un PNG de la vue"),
    "language": ("Idioma", "Language", "Langue"),
    "zoombox_hint": ("Lupa: arrastrá un recuadro sobre la zona a ampliar",
                     "Magnifier: drag a box over the area to enlarge",
                     "Loupe : tracez un rectangle sur la zone à agrandir"),
    # paneles
    "p_res": ("Resultado", "Result", "Résultat"),
    "p_col": ("Colores y barra", "Colors and color bar", "Couleurs et barre"),
    "p_mesh": ("Malla y vista", "Mesh and view", "Maillage et vue"),
    "p_cut": ("Corte por plano", "Plane cut", "Coupe par un plan"),
    "p_values": ("Valores en puntos", "Point values", "Valeurs en des points"),
    "p_fig": ("Figura para paper", "Paper figure", "Figure pour article"),
    "p_axis": ("Eje cilíndrico (DR, SIRR, SITT…)", "Cylindrical axis (DR, SIRR, SITT…)",
               "Axe cylindrique (DR, SIRR, SITT…)"),
    # resultado
    "field": ("Campo", "Field", "Champ"),
    "component": ("Componente", "Component", "Composante"),
    "step_txt": ("paso {i}/{n}   t = {t}", "step {i}/{n}   t = {t}", "pas {i}/{n}   t = {t}"),
    "cell_reduce": ("Valor por elemento (de sus puntos de Gauss)", "Value per element (from its Gauss points)",
                    "Valeur par élément (de ses points de Gauss)"),
    "shown_elga": ("{r} de los PG por elemento", "{r} of the Gauss points per element",
                   "{r} des points de Gauss par élément"),
    "shown_nodal": ("valores nodales", "nodal values", "valeurs nodales"),
    "info": ("Pintado ({que}): min {lo}   max {hi}   ({d}/{n} con valor, {s})",
             "Shown ({que}): min {lo}   max {hi}   ({d}/{n} with a value, {s})",
             "Affiché ({que}) : min {lo}   max {hi}   ({d}/{n} avec une valeur, {s})"),
    "hidden_cells": ("   · {k} celdas ocultas", "   · {k} cells hidden", "   · {k} mailles masquées"),
    "gauss": ("En los puntos de Gauss: min {lo}   max {hi}", "At the Gauss points: min {lo}   max {hi}",
              "Aux points de Gauss : min {lo}   max {hi}"),
    # colores
    "cmap": ("Mapa (ParaView)", "Colormap (ParaView)", "Palette (ParaView)"),
    "bands": ("Bandas", "Bands", "Bandes"),
    "invert": ("Invertir", "Invert", "Inverser"),
    "log": ("Escala log", "Log scale", "Échelle log"),
    "auto_range": ("Rango automático (lo visible)", "Automatic range (what is visible)",
                   "Plage automatique (le visible)"),
    "min": ("mín", "min", "min"),
    "max": ("máx", "max", "max"),
    "symmetric": ("Simétrico en 0", "Symmetric about 0", "Symétrique autour de 0"),
    "all_steps": ("Todos los instantes", "All time steps", "Tous les instants"),
    "tip_all_steps": ("Rango de la componente en todos los instantes (puede tardar)",
                      "Range of the component over all time steps (may take a while)",
                      "Plage de la composante sur tous les instants (peut être long)"),
    "all_steps_done": ("Rango de todos los instantes aplicado", "Range over all time steps applied",
                       "Plage de tous les instants appliquée"),
    "bar": ("Barra", "Bar", "Barre"),
    "bar_title": ("título (vacío = componente)", "title (empty = component)", "titre (vide = composante)"),
    # malla y vista
    "groups": ("Grupos visibles (vacío = volúmenes)", "Visible groups (empty = volumes)",
               "Groupes visibles (vide = volumes)"),
    "representation": ("Representación", "Representation", "Représentation"),
    "shading": ("Sombreado", "Shading", "Ombrage"),
    "edges": ("Aristas", "Edges", "Arêtes"),
    "tip_edge_color": ("Color de las aristas (en 'Alambre' se colorean con el campo)",
                       "Edge color (in 'Wireframe' they take the field colors)",
                       "Couleur des arêtes (en « Fil de fer » elles prennent les couleurs du champ)"),
    "tip_edge_width": ("Grosor de línea (px)", "Line width (px)", "Épaisseur de ligne (px)"),
    "nodes": ("Nodos", "Nodes", "Nœuds"),
    "tip_show_nodes": ("Mostrar los nodos de la superficie visible", "Show the nodes of the visible surface",
                       "Afficher les nœuds de la surface visible"),
    "tip_node_color": ("Color de los nodos (en 'Puntos' se colorean con el campo)",
                       "Node color (in 'Points' they take the field colors)",
                       "Couleur des nœuds (en « Points » ils prennent les couleurs du champ)"),
    "tip_node_size": ("Tamaño de punto (px)", "Point size (px)", "Taille des points (px)"),
    "opacity": ("Opacidad", "Opacity", "Opacité"),
    "warp": ("Deformada ×", "Deformed ×", "Déformée ×"),
    "hide_nan": ("Ocultar celdas sin valor", "Hide cells without a value", "Masquer les mailles sans valeur"),
    "threshold": ("Umbral", "Threshold", "Seuil"),
    "from": ("desde", "from", "de"),
    "to": ("hasta", "to", "à"),
    "window": ("Ventana a lo largo del eje", "Window along the axis", "Fenêtre le long de l'axe"),
    "background": ("Fondo", "Background", "Fond"),
    "show_text": ("Textos", "Text", "Textes"),
    "triad": ("Triedro", "Axes", "Trièdre"),
    "view_name": ("nombre de vista", "view name", "nom de la vue"),
    "tip_save_view": ("Guardar vista (cámara + todo el estado)", "Save view (camera + full state)",
                      "Enregistrer la vue (caméra + tout l'état)"),
    "saved_views": ("vistas guardadas", "saved views", "vues enregistrées"),
    "tip_load_view": ("Cargar vista", "Load view", "Charger la vue"),
    "view_saved": ("Vista guardada: {p}", "View saved: {p}", "Vue enregistrée : {p}"),
    "view_loaded": ("Vista cargada: {p}", "View loaded: {p}", "Vue chargée : {p}"),
    "png_saved": ("Guardado: {p}", "Saved: {p}", "Enregistré : {p}"),
    # corte
    "mode": ("Modo", "Mode", "Mode"),
    "tip_flip": ("Quedarse con el otro lado", "Keep the other side", "Garder l'autre côté"),
    "normal_k": ("Normal {k}", "Normal {k}", "Normale {k}"),
    "transverse": ("Transversal", "Transverse", "Transversal"),
    "tip_transverse": ("Sección transversal del tubo", "Cross-section of the tube", "Section transversale du tube"),
    "longitudinal": ("Longitudinal", "Longitudinal", "Longitudinal"),
    "tip_longitudinal": ("Plano que contiene al eje, a θ", "Plane that contains the axis, at θ",
                         "Plan qui contient l'axe, à θ"),
    "camera": ("Cámara", "Camera", "Caméra"),
    "tip_camera": ("Plano de frente a la vista", "Plane facing the view", "Plan face à la vue"),
    "long_theta": ("θ del plano longitudinal", "θ of the longitudinal plane", "θ du plan longitudinal"),
    "plane_pos": ("Posición a lo largo de la normal", "Position along the normal", "Position le long de la normale"),
    "origin": ("origen x, y, z", "origin x, y, z", "origine x, y, z"),
    "normal": ("normal nx, ny, nz", "normal nx, ny, nz", "normale nx, ny, nz"),
    "draggable": ("Plano arrastrable", "Draggable plane", "Plan déplaçable"),
    "context": ("Resto translúcido", "Rest translucent", "Reste translucide"),
    "plane_tip": ("Tip: con el modo de clic ▣ (barra de arriba) el plano se ubica donde hagas clic.",
                  "Tip: with the ▣ click mode (top bar) the plane goes where you click.",
                  "Astuce : avec le mode de clic ▣ (barre du haut), le plan se place là où vous cliquez."),
    # valores en puntos
    "values_help": ("Elegí el gotero arriba y hacé clic sobre la pieza. Los valores se actualizan "
                    "al cambiar de instante o de componente.",
                    "Pick the eyedropper above and click on the part. The values follow changes of "
                    "time step or component.",
                    "Choisissez la pipette en haut et cliquez sur la pièce. Les valeurs suivent les "
                    "changements d'instant ou de composante."),
    "clear_points": ("Borrar puntos", "Clear points", "Effacer les points"),
    # figura
    "fig_help": ("Estilo de revista: fondo blanco, sin sombreado, DejaVu Sans 9/10 pt, barra de "
                 "matplotlib. Se encuadra como la vista actual.",
                 "Journal style: white background, no shading, DejaVu Sans 9/10 pt, matplotlib "
                 "color bar. Framed like the current view.",
                 "Style revue : fond blanc, sans ombrage, DejaVu Sans 9/10 pt, barre matplotlib. "
                 "Même cadrage que la vue actuelle."),
    "width": ("Ancho", "Width", "Largeur"),
    "ticks": ("Marcas", "Ticks", "Graduations"),
    "bar_label": ("rótulo de la barra (admite $\\sigma_r$)", "bar label (accepts $\\sigma_r$)",
                  "légende de la barre (accepte $\\sigma_r$)"),
    "factor": ("multiplicar valores por (p. ej. 1000: m → mm)", "multiply values by (e.g. 1000: m → mm)",
               "multiplier les valeurs par (p. ex. 1000 : m → mm)"),
    "scalebar": ("Escala", "Scale bar", "Échelle"),
    "sb_factor": ("unidad/modelo", "unit/model", "unité/modèle"),
    "sb_unit": ("unidad", "unit", "unité"),
    "file_name": ("nombre del archivo", "file name", "nom du fichier"),
    "make_figure": ("Generar figura", "Make figure", "Générer la figure"),
    "generating": ("Generando…", "Generating…", "Génération…"),
    "fig_done": ("PDF: {pdf}\nPNG 600 dpi: {png}\nReceta: {rec}\nLaTeX: {tex}",
                 "PDF: {pdf}\nPNG 600 dpi: {png}\nRecipe: {rec}\nLaTeX: {tex}",
                 "PDF : {pdf}\nPNG 600 dpi : {png}\nRecette : {rec}\nLaTeX : {tex}"),
    "fig_no_sb": ("(sin escala de longitud: activá la proyección paralela)",
                  "(no scale bar: turn on the parallel projection)",
                  "(pas d'échelle : activez la projection parallèle)"),
    "error": ("Error: {e}", "Error: {e}", "Erreur : {e}"),
    # eje
    "axis_point": ("punto x, y, z", "point x, y, z", "point x, y, z"),
    "axis_dir": ("dirección", "direction", "direction"),
    # diseño v0.3: pipeline, pestañas, secciones, barra de herramientas, información
    "pipeline": ("Pipeline", "Pipeline", "Pipeline"),
    "f_warp": ("Deformada (DEPL)", "Deformed shape (DEPL)", "Déformée (DEPL)"),
    "f_threshold": ("Umbral", "Threshold", "Seuil"),
    "f_clip": ("Corte", "Cut", "Coupe"),
    "f_window": ("Ventana axial", "Axial window", "Fenêtre axiale"),
    "tip_eye": ("Prender / apagar", "Turn on / off", "Activer / désactiver"),
    "tab_props": ("Propiedades", "Properties", "Propriétés"),
    "tab_info": ("Información", "Information", "Information"),
    "tab_values": ("Valores", "Values", "Valeurs"),
    "tab_fig": ("Figura", "Figure", "Figure"),
    "sec_coloring": ("Coloreado", "Coloring", "Coloration"),
    "sec_styling": ("Estilo", "Styling", "Style"),
    "sec_view": ("Vista", "View", "Vue"),
    "sec_mesh": ("Malla", "Mesh", "Maillage"),
    "sec_fields": ("Campos", "Fields", "Champs"),
    "sec_shown": ("Lo que se ve", "What is shown", "Ce qui est affiché"),
    "sec_saved": ("Vistas guardadas", "Saved views", "Vues enregistrées"),
    "enabled": ("Activado", "Enabled", "Activé"),
    "range": ("Rango", "Range", "Plage"),
    "colormap": ("Mapa", "Colormap", "Palette"),
    "color_bar": ("Barra de colores", "Color bar", "Barre de couleurs"),
    "edge_style": ("Aristas", "Edges", "Arêtes"),
    "node_style": ("Nodos", "Nodes", "Nœuds"),
    "show_nodes_lbl": ("mostrar", "show", "afficher"),
    "presets": ("Atajos", "Presets", "Raccourcis"),
    "plane": ("Plano", "Plane", "Plan"),
    "time": ("Tiempo", "Time", "Temps"),
    "cells_wo_value": ("Celdas sin valor", "Cells without value", "Mailles sans valeur"),
    "hide": ("ocultar", "hide", "masquer"),
    "warp_help": ("La malla se dibuja desplazada DEPL × escala, en el mismo instante que el campo.",
                  "The mesh is drawn displaced by DEPL × scale, at the same time step as the field.",
                  "Le maillage est dessiné déplacé de DEPL × échelle, au même instant que le champ."),
    "thr_help": ("Se muestran solo las celdas cuyo valor (el pintado) cae en el rango.",
                 "Only the cells whose value (as painted) is in the range are shown.",
                 "Seules les mailles dont la valeur (affichée) est dans la plage sont montrées."),
    "win_help": ("Se muestran solo las celdas cuyo centro cae en la ventana, medida a lo largo del eje cilíndrico.",
                 "Only the cells whose center is inside the window, measured along the cylindrical axis, are shown.",
                 "Seules les mailles dont le centre est dans la fenêtre, mesurée le long de l'axe cylindrique, "
                 "sont montrées."),
    "info_file": ("Archivo", "File", "Fichier"),
    "info_nodes": ("Nodos", "Nodes", "Nœuds"),
    "info_cells": ("Celdas", "Cells", "Mailles"),
    "info_bounds": ("Límites", "Bounds", "Limites"),
    "col_field": ("campo", "field", "champ"),
    "col_support": ("soporte", "support", "support"),
    "col_comps": ("comp.", "comp.", "comp."),
    "col_steps": ("inst.", "steps", "inst."),
    "col_value": ("valor", "value", "valeur"),
    "col_node": ("nodo", "node", "nœud"),
    "no_picks": ("Sin puntos todavía.", "No points yet.", "Pas encore de points."),
    "tip_side": ("Mostrar / ocultar el panel", "Show / hide the panel", "Afficher / masquer le panneau"),
    "tip_color_by": ("Colorear por (campo y componente)", "Color by (field and component)",
                     "Colorer par (champ et composante)"),
    "tip_rep": ("Representación", "Representation", "Représentation"),
    "tip_cmap": ("Mapa de colores", "Colormap", "Palette de couleurs"),
    "tip_invert": ("Invertir el mapa de colores", "Invert the colormap", "Inverser la palette"),
    "tip_rescale": ("Reescalar a lo visible", "Rescale to the visible data", "Recalibrer sur les données visibles"),
    "tip_bar": ("Mostrar / ocultar la barra de colores", "Show / hide the color bar",
                "Afficher / masquer la barre de couleurs"),
    "tip_first": ("Primer instante", "First time step", "Premier instant"),
    "tip_prev": ("Instante anterior", "Previous time step", "Instant précédent"),
    "tip_play": ("Reproducir / pausa", "Play / pause", "Lecture / pause"),
    "tip_next": ("Instante siguiente", "Next time step", "Instant suivant"),
    "tip_last": ("Último instante", "Last time step", "Dernier instant"),
    "tip_theme": ("Tema claro / oscuro", "Light / dark theme", "Thème clair / sombre"),
    "auto_short": ("Rango automático", "Auto range", "Plage auto"),
    "theta_short": ("θ longitudinal", "Longitudinal θ", "θ longitudinal"),
    "pos_short": ("Posición", "Position", "Position"),
    "label_short": ("Rótulo", "Label", "Légende"),
    "factor_short": ("Factor", "Factor", "Facteur"),
    "sb_short": ("Unidad", "Unit", "Unité"),
    "bar_where": ("Ubicación", "Placement", "Emplacement"),
    "bar_drag_help": ("La barra también se arrastra con el mouse en la vista, y se estira tirando de un borde.",
                      "The bar can also be dragged with the mouse in the view, and resized by pulling an edge.",
                      "La barre se déplace aussi à la souris dans la vue, et se redimensionne en tirant un bord."),
}

# opciones de las listas: clave interna -> (es, en, fr)
CHOICES = {
    "representation": {
        "surface": ("Superficie", "Surface", "Surface"),
        "surface_edges": ("Superficie con aristas", "Surface with edges", "Surface avec arêtes"),
        "wireframe": ("Alambre", "Wireframe", "Fil de fer"),
        "points": ("Puntos", "Points", "Points"),
    },
    "clip_mode": {
        "none": ("Ninguno", "None", "Aucun"),
        "clip": ("Recortar", "Clip", "Découper"),
        "slice": ("Sección", "Slice", "Section"),
        "crinkle": ("Celdas enteras", "Whole cells", "Mailles entières"),
    },
    "cell_reduce": {
        "mean": ("promedio", "mean", "moyenne"),
        "min": ("mínimo", "minimum", "minimum"),
        "max": ("máximo", "maximum", "maximum"),
        "absmax": ("máx. |valor|", "max |value|", "max |valeur|"),
    },
    "background": {
        "light_gradient": ("Degradado claro", "Light gradient", "Dégradé clair"),
        "white": ("Blanco", "White", "Blanc"),
        "light_gray": ("Gris claro", "Light gray", "Gris clair"),
        "paraview_gray": ("Gris ParaView", "ParaView gray", "Gris ParaView"),
        "dark_gradient": ("Degradado oscuro", "Dark gradient", "Dégradé sombre"),
        "black": ("Negro", "Black", "Noir"),
        "custom": ("Personalizado", "Custom", "Personnalisé"),
    },
    "fig_width": {
        "1col": ("1 columna (3,46 in)", "1 column (3.46 in)", "1 colonne (3,46 in)"),
        "1.5col": ("1,5 columnas (5,2 in)", "1.5 columns (5.2 in)", "1,5 colonne (5,2 in)"),
        "2col": ("2 columnas (7,1 in)", "2 columns (7.1 in)", "2 colonnes (7,1 in)"),
    },
    "bar_pos": {
        "right": ("derecha", "right", "droite"),
        "left": ("izquierda", "left", "gauche"),
        "top": ("arriba (horizontal)", "top (horizontal)", "haut (horizontale)"),
        "bottom": ("abajo (horizontal)", "bottom (horizontal)", "bas (horizontale)"),
        "custom": ("donde la dejé", "where I left it", "là où je l'ai mise"),
    },
    "fig_bar": {
        "horizontal": ("horizontal", "horizontal", "horizontale"),
        "vertical": ("vertical", "vertical", "verticale"),
        "none": ("ninguna", "none", "aucune"),
    },
}

# nombres de otras versiones que también se aceptan
LEGACY = {
    "cmap": {"Cool to Warm (extendido)": "Cool to Warm (Extended)",
             "Blue Orange (divergente)": "Blue Orange (divergent)",
             "Azul-rojo (RdBu)": "RdBu", "Azul-rojo": "RdBu", "Grises": "Grayscale",
             "Frío-cálido": "Cool to Warm", "Arcoíris (jet)": "Jet", "Plasma": "Inferno"},
    "cell_reduce": {"average": "mean", "abs": "absmax", "maxabs": "absmax"},
    "clip_mode": {"section": "slice", "cut": "clip", "whole": "crinkle"},
    "background": {"gradient": "light_gradient", "gray": "light_gray", "grey": "light_gray"},
}


def _norm(s):
    return " ".join(str(s).strip().lower().split())


def canonical(kind, value):
    """Clave interna de una opción a partir de la clave, del rótulo en cualquier idioma
    o de un nombre viejo. Lo que no se reconoce vuelve igual (p. ej. '#rrggbb')."""
    if value is None:
        return None
    if kind in CHOICES and value in CHOICES[kind]:
        return value
    legacy = LEGACY.get(kind, {})
    if value in legacy:
        return legacy[value]
    n = _norm(value)
    for k, labels in CHOICES.get(kind, {}).items():
        if n == _norm(k) or any(n == _norm(lab) for lab in labels):
            return k
    for k, v in legacy.items():
        if n == _norm(k):
            return v
    return value


def _index(lang):
    return list(LANGS).index(lang if lang in LANGS else DEFAULT_LANG)


def tr(lang, key, **kw):
    s = UI[key][_index(lang)]
    return s.format(**kw) if kw else s


def choice_label(lang, kind, key):
    labels = CHOICES[kind].get(key)
    return labels[_index(lang)] if labels else str(key)


def items(lang, kind, keys=None):
    """Lista para un v-select: [{'title': rótulo, 'value': clave}]."""
    keys = list(CHOICES[kind]) if keys is None else keys
    return [{"title": choice_label(lang, kind, k), "value": k} for k in keys]


def ui_table(lang):
    i = _index(lang)
    return {k: v[i] for k, v in UI.items()}


# ---------------------------------------------------------------- configuración
def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "aster-view", "config.json")


def load_config():
    try:
        with open(config_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(**kw):
    d = load_config()
    d.update(kw)
    p = config_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
    except OSError:
        pass


def _lang_code(s):
    s = (s or "").strip().lower().replace("_", "-")
    return s.split("-")[0] if s else ""


def resolve_lang(explicit=None):
    """--lang > el último elegido en el visor > ASTER_VIEW_LANG > idioma del sistema > inglés."""
    for cand in (explicit, load_config().get("language"), os.environ.get("ASTER_VIEW_LANG")):
        c = _lang_code(cand)
        if c in LANGS:
            return c
    try:
        sys_lang = locale.getlocale()[0] or os.environ.get("LANG", "")
    except ValueError:
        sys_lang = os.environ.get("LANG", "")
    c = _lang_code(sys_lang)
    return c if c in LANGS else DEFAULT_LANG
