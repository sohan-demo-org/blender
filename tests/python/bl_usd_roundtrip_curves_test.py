# SPDX-FileCopyrightText: 2025 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
USD round-trip audit for curve-like objects (legacy Curve, Curves/hair, Text).

Every test builds a small scene with non-default values, exports it to .usda,
re-imports it into an empty file and compares the result with what was set.

Properties that survive the trip are asserted. Properties that are currently
lost are either marked with ``unittest.expectedFailure`` (the assertion states
what *should* survive) or are asserted in their current lossy form with a
comment stating that the assertion documents a known gap. Nothing here is a
fix; the file is an inventory of the current behaviour.

Run with:
  blender -b --factory-startup --python tests/python/bl_usd_roundtrip_curves_test.py -- \
      --testdir /abs/path/to/tests/files/usd
"""

import math
import os
import pathlib
import sys
import tempfile
import unittest
from pxr import Usd, UsdGeom, UsdShade

import bpy
import bmesh

sys.path.append(str(pathlib.Path(__file__).parent.absolute()))
from modules.colored_print import (print_message, use_message_colors)


args = None

# Blender curve type / handle type / knot mode enum values (DNA_curves_types.h).
CURVE_TYPE_CATMULL_ROM = 0
CURVE_TYPE_POLY = 1
CURVE_TYPE_BEZIER = 2
CURVE_TYPE_NURBS = 3
BEZIER_HANDLE_FREE = 0
BEZIER_HANDLE_VECTOR = 2
BEZIER_HANDLE_ALIGN = 3
NURBS_KNOT_MODE_NORMAL = 0
NURBS_KNOT_MODE_ENDPOINT = 1
NURBS_KNOT_MODE_BEZIER = 2
NORMAL_MODE_Z_UP = 1


def _link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _new_curves(name, counts, curve_type):
    """New Curves data-block with all curves of one type. Uses set_types() so the
    runtime type counts are updated (writing the raw attribute is not enough)."""
    hc = bpy.data.hair_curves.new(name)
    hc.add_curves(counts)
    hc.set_types(type=curve_type, indices=list(range(len(hc.curves))))
    return hc


def _attr(data, name):
    """Return the values of a Curves attribute as a plain python list."""
    attr = data.attributes[name]
    out = []
    for item in attr.data:
        if hasattr(item, "value"):
            out.append(item.value)
        elif hasattr(item, "vector"):
            out.append(tuple(item.vector))
        elif hasattr(item, "color"):
            out.append(tuple(item.color))
    return out


def build_scene():
    """Scene with every curve-like object type and non-default values everywhere."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)

    mat = bpy.data.materials.new("CurveMat")

    # Legacy Curve: 3D bezier, bevel + extrude, transforms, material,
    # per-point radius/tilt, mixed handle types.
    cu = bpy.data.curves.new("LegacyBezier3D", 'CURVE')
    cu.dimensions = '3D'
    cu.resolution_u = 24
    cu.render_resolution_u = 32
    cu.bevel_depth = 0.1
    cu.bevel_resolution = 3
    cu.extrude = 0.05
    cu.offset = 0.02
    cu.twist_mode = 'Z_UP'
    cu.twist_smooth = 0.5
    cu.use_fill_caps = True
    cu.fill_mode = 'HALF'
    cu.taper_radius_mode = 'ADD'
    cu.materials.append(mat)
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(3)
    sp.resolution_u = 16
    sp.use_smooth = False
    cos = [(0, 0, 0), (1, 1, 0.5), (2, 0, 1), (3, 1, 0)]
    hls = [(-0.5, -0.5, 0.0), (0.5, 1.2, 0.5), (1.6, 0.6, 1.0), (2.6667, 0.6667, 0.3333)]
    hrs = [(0.5, 0.5, 0.2), (1.5, 0.8, 0.5), (2.4, -0.6, 1.0), (3.3333, 1.3333, -0.3333)]
    types = ['FREE', 'FREE', 'ALIGNED', 'VECTOR']
    for i, bp in enumerate(sp.bezier_points):
        bp.handle_left_type = types[i]
        bp.handle_right_type = types[i]
        bp.co = cos[i]
        bp.handle_left = hls[i]
        bp.handle_right = hrs[i]
        bp.radius = 0.5 + 0.25 * i
        bp.tilt = math.radians(10 * (i + 1))
    ob = _link(bpy.data.objects.new("LegacyBezier3D", cu))
    ob.location = (1, 2, 3)
    ob.rotation_euler = (0.1, 0.2, 0.3)
    ob.scale = (1, 2, 1.5)

    # Legacy Curve: cyclic bezier, no bevel.
    cu = bpy.data.curves.new("LegacyBezierCyclic", 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(2)
    sp.use_cyclic_u = True
    for i, bp in enumerate(sp.bezier_points):
        a = math.radians(120 * i)
        bp.handle_left_type = bp.handle_right_type = 'FREE'
        bp.co = (math.cos(a), math.sin(a), 0.1 * i)
        bp.handle_left = (math.cos(a) - 0.3 * math.sin(a) * -1, math.sin(a) - 0.3 * math.cos(a), 0.1 * i)
        bp.handle_right = (math.cos(a) + 0.3 * math.sin(a) * -1, math.sin(a) + 0.3 * math.cos(a), 0.1 * i)
        bp.radius = 1.0 + 0.5 * i
        bp.tilt = 0.2 * i
    _link(bpy.data.objects.new("LegacyBezierCyclic", cu))

    # Legacy Curve: 2D, cyclic, filled + extruded (a filled face in Blender).
    cu = bpy.data.curves.new("LegacyBezier2D", 'CURVE')
    cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'
    cu.extrude = 0.1
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(3)
    sp.use_cyclic_u = True
    for i, (x, y) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
        bp = sp.bezier_points[i]
        bp.handle_left_type = bp.handle_right_type = 'VECTOR'
        bp.co = (x, y, 0)
    _link(bpy.data.objects.new("LegacyBezier2D", cu))

    # Legacy Curve: NURBS order 3, endpoint knots, non-uniform weights.
    cu = bpy.data.curves.new("LegacyNurbs", 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('NURBS')
    sp.points.add(5)
    sp.order_u = 3
    sp.use_endpoint_u = True
    sp.resolution_u = 20
    for i, p in enumerate(sp.points):
        p.co = (0.5 * i, math.sin(i), 0.2 * i, 1.0 + 0.5 * i)
        p.radius = 0.1 * (i + 1)
        p.tilt = 0.1 * i
    _link(bpy.data.objects.new("LegacyNurbs", cu))

    # Legacy Curve: cyclic NURBS, order 4, uniform knots, weights.
    cu = bpy.data.curves.new("LegacyNurbsCyclic", 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('NURBS')
    sp.points.add(5)
    sp.order_u = 4
    sp.use_cyclic_u = True
    for i, p in enumerate(sp.points):
        a = math.radians(60 * i)
        p.co = (2 * math.cos(a), 2 * math.sin(a), 0.1 * i, 1.0 if i % 2 == 0 else 1.2)
        p.radius = 0.3 + 0.1 * i
    _link(bpy.data.objects.new("LegacyNurbsCyclic", cu))

    # Legacy Curve: NURBS with bezier knots.
    cu = bpy.data.curves.new("LegacyNurbsBezierKnots", 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('NURBS')
    sp.points.add(6)
    sp.order_u = 4
    sp.use_bezier_u = True
    for i, p in enumerate(sp.points):
        p.co = (i, 0.5 * (i % 2), 0, 1.0)
    _link(bpy.data.objects.new("LegacyNurbsBezierKnots", cu))

    # Legacy Curve: cyclic poly spline with bevel, per-point radius/tilt.
    cu = bpy.data.curves.new("LegacyPoly", 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = 0.2
    sp = cu.splines.new('POLY')
    sp.points.add(4)
    sp.use_cyclic_u = True
    for i, p in enumerate(sp.points):
        p.co = (i, 0.1 * i * i, 0.3 * i, 1.0)
        p.radius = 0.2 * (i + 1)
        p.tilt = 0.3 * i
    _link(bpy.data.objects.new("LegacyPoly", cu))

    # Legacy Curve: two poly splines in one object.
    cu = bpy.data.curves.new("LegacyMultiPoly", 'CURVE')
    for j in range(2):
        sp = cu.splines.new('POLY')
        sp.points.add(2)
        for i, p in enumerate(sp.points):
            p.co = (i, j, 0, 1.0)
            p.radius = 1.0 + j
    _link(bpy.data.objects.new("LegacyMultiPoly", cu))

    # Legacy Curve: mixed spline types (bezier + poly).
    cu = bpy.data.curves.new("LegacyMixed", 'CURVE')
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(1)
    sp.bezier_points[1].co = (1, 0, 0)
    sp = cu.splines.new('POLY')
    sp.points.add(1)
    sp.points[0].co = (0, 1, 0, 1)
    sp.points[1].co = (1, 1, 0, 1)
    _link(bpy.data.objects.new("LegacyMixed", cu))

    # Text object.
    ft = bpy.data.curves.new("TextObj", 'FONT')
    ft.body = "USD"
    ft.size = 1.5
    ft.extrude = 0.1
    ft.bevel_depth = 0.02
    _link(bpy.data.objects.new("TextObj", ft))

    # Surface mesh for hair parenting.
    me = bpy.data.meshes.new("SurfaceMesh")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers.new(name="UVMap")
    surf = _link(bpy.data.objects.new("SurfaceMesh", me))

    # Curves: Catmull-Rom hair, 2 curves, every attribute type, parented to the surface.
    hc = _new_curves("HairCatmullRom", [5, 6], 'CATMULL_ROM')
    k = 0
    for ci, c in enumerate(hc.curves):
        for pi, p in enumerate(c.points):
            p.position = (ci, pi * 0.3, 0.1 * pi * pi)
            p.radius = 0.01 * (k + 1)
            k += 1
    for name, dtype, domain in (
            ("my_float", 'FLOAT', 'POINT'), ("my_color", 'FLOAT_COLOR', 'POINT'),
            ("my_bcolor", 'BYTE_COLOR', 'POINT'), ("my_int", 'INT', 'CURVE'),
            ("my_bool", 'BOOLEAN', 'POINT'), ("my_vec", 'FLOAT_VECTOR', 'POINT'),
            ("my_uv", 'FLOAT2', 'CURVE'), ("my_int8", 'INT8', 'CURVE'),
            ("my_quat", 'QUATERNION', 'CURVE'), ("surface_uv_coordinate", 'FLOAT2', 'CURVE'),
            ("resolution", 'INT', 'CURVE'), ("normal_mode", 'INT8', 'CURVE'),
            ("tilt", 'FLOAT', 'POINT')):
        hc.attributes.new(name, dtype, domain)
    n = len(hc.points)
    for i, d in enumerate(hc.attributes["my_float"].data):
        d.value = i / (n - 1)
    for i, d in enumerate(hc.attributes["my_color"].data):
        d.color = (i / (n - 1), 0.5, 1 - i / (n - 1), 0.25)
    for i, d in enumerate(hc.attributes["my_bcolor"].data):
        d.color = (0.0, i / (n - 1), 1.0, 1.0)
    for i, d in enumerate(hc.attributes["my_int"].data):
        d.value = 7 + i
    for i, d in enumerate(hc.attributes["my_bool"].data):
        d.value = bool(i % 2)
    for i, d in enumerate(hc.attributes["my_vec"].data):
        d.vector = (i, -i, 0.5)
    for i, d in enumerate(hc.attributes["my_uv"].data):
        d.vector = (0.25 + 0.5 * i, 0.75)
    for i, d in enumerate(hc.attributes["my_int8"].data):
        d.value = 3 + i
    hc.attributes["my_quat"].data[0].value = (0.7071, 0.7071, 0, 0)
    hc.attributes["my_quat"].data[1].value = (0.7071, 0, 0.7071, 0)
    for i, d in enumerate(hc.attributes["surface_uv_coordinate"].data):
        d.vector = (0.1 + 0.2 * i, 0.3)
    for d in hc.attributes["resolution"].data:
        d.value = 7
    for d in hc.attributes["normal_mode"].data:
        d.value = NORMAL_MODE_Z_UP
    for i, d in enumerate(hc.attributes["tilt"].data):
        d.value = 0.05 * i
    hc.materials.append(mat)
    hc.surface = surf
    hc.surface_uv_map = "UVMap"
    ob = _link(bpy.data.objects.new("HairCatmullRom", hc))
    ob.parent = surf
    ob.location = (0.5, 0.5, 0)

    # Curves: cyclic Catmull-Rom.
    hc = _new_curves("HairCatmullRomCyclic", [6], 'CATMULL_ROM')
    for pi, p in enumerate(hc.curves[0].points):
        a = math.radians(60 * pi)
        p.position = (math.cos(a), math.sin(a), 0.1 * pi)
        p.radius = 0.02 * (pi + 1)
    hc.attributes.new("cyclic", 'BOOLEAN', 'CURVE').data[0].value = True
    _link(bpy.data.objects.new("HairCatmullRomCyclic", hc))

    # Curves: cyclic poly with a custom float attribute.
    hc = _new_curves("HairPoly", [4], 'POLY')
    for pi, p in enumerate(hc.curves[0].points):
        p.position = (pi, pi % 2, 0.5)
        p.radius = 0.1 * (pi + 1)
    hc.attributes.new("cyclic", 'BOOLEAN', 'CURVE')
    hc.attributes.new("my_float", 'FLOAT', 'POINT')
    hc.attributes["cyclic"].data[0].value = True
    for i, d in enumerate(hc.attributes["my_float"].data):
        d.value = 1.5 * i
    _link(bpy.data.objects.new("HairPoly", hc))

    # Curves: Bezier with explicit handles, handle types and resolution.
    hc = _new_curves("HairBezier", [4], 'BEZIER')
    for name, dtype, domain in (
            ("handle_left", 'FLOAT_VECTOR', 'POINT'), ("handle_right", 'FLOAT_VECTOR', 'POINT'),
            ("handle_type_left", 'INT8', 'POINT'), ("handle_type_right", 'INT8', 'POINT'),
            ("resolution", 'INT', 'CURVE'), ("my_float", 'FLOAT', 'POINT')):
        hc.attributes.new(name, dtype, domain)
    htypes = [BEZIER_HANDLE_FREE, BEZIER_HANDLE_VECTOR, BEZIER_HANDLE_ALIGN, BEZIER_HANDLE_FREE]
    for pi, p in enumerate(hc.curves[0].points):
        p.position = (pi, 0.5 * (pi % 2), 0.0)
        p.radius = 0.05 * (pi + 1)
        hc.attributes["handle_left"].data[pi].vector = (pi - 0.3, 0.5 * (pi % 2) + 0.2, 0.1)
        hc.attributes["handle_right"].data[pi].vector = (pi + 0.3, 0.5 * (pi % 2) - 0.2, -0.1)
        hc.attributes["handle_type_left"].data[pi].value = htypes[pi]
        hc.attributes["handle_type_right"].data[pi].value = htypes[pi]
        hc.attributes["my_float"].data[pi].value = 2.5 * pi
    hc.attributes["resolution"].data[0].value = 5
    _link(bpy.data.objects.new("HairBezier", hc))

    # Curves: NURBS order 3, endpoint knots, weights, custom attribute.
    hc = _new_curves("HairNurbs", [6], 'NURBS')
    for pi, p in enumerate(hc.curves[0].points):
        p.position = (pi * 0.5, math.cos(pi), 0.0)
        p.radius = 0.05 * (pi + 1)
    hc.attributes.new("nurbs_order", 'INT8', 'CURVE')
    hc.attributes.new("knots_mode", 'INT8', 'CURVE')
    hc.attributes.new("nurbs_weight", 'FLOAT', 'POINT')
    hc.attributes.new("my_float", 'FLOAT', 'POINT')
    hc.attributes["nurbs_order"].data[0].value = 3
    hc.attributes["knots_mode"].data[0].value = NURBS_KNOT_MODE_ENDPOINT
    for i, d in enumerate(hc.attributes["nurbs_weight"].data):
        d.value = 1.0 + 0.25 * i
    for i, d in enumerate(hc.attributes["my_float"].data):
        d.value = 3.5 * i
    _link(bpy.data.objects.new("HairNurbs", hc))

    # Curves: cyclic NURBS order 4 with a custom attribute.
    hc = _new_curves("HairNurbsCyclic", [6], 'NURBS')
    for pi, p in enumerate(hc.curves[0].points):
        a = math.radians(60 * pi)
        p.position = (2 * math.cos(a), 2 * math.sin(a), 0.0)
        p.radius = 0.05 * (pi + 1)
    hc.attributes.new("nurbs_order", 'INT8', 'CURVE')
    hc.attributes.new("cyclic", 'BOOLEAN', 'CURVE')
    hc.attributes.new("my_float", 'FLOAT', 'POINT')
    hc.attributes["nurbs_order"].data[0].value = 4
    hc.attributes["cyclic"].data[0].value = True
    for i, d in enumerate(hc.attributes["my_float"].data):
        d.value = 4.5 * i
    _link(bpy.data.objects.new("HairNurbsCyclic", hc))

    # Curves: mixed curve types in one object (catmull-rom + poly).
    hc = bpy.data.hair_curves.new("HairMixed")
    hc.add_curves([3, 3])
    hc.set_types(type='CATMULL_ROM', indices=[0])
    hc.set_types(type='POLY', indices=[1])
    for ci, c in enumerate(hc.curves):
        for pi, p in enumerate(c.points):
            p.position = (pi, ci, 0)
    _link(bpy.data.objects.new("HairMixed", hc))

    bpy.context.view_layer.update()


class USDCurvesRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.testdir = args.testdir
        if os.environ.get("BLENDER_TEST_COLOR") is not None:
            use_message_colors()

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.tempdir = pathlib.Path(self._tempdir.name)
        self.assertTrue(self.testdir.exists(), 'Test dir {0} should exist'.format(self.testdir))
        print_message(self._testMethodName, 'SUCCESS', 'RUN')
        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))

    def tearDown(self):
        self._tempdir.cleanup()
        result = self._outcome.result
        ok = all(test != self for test, _ in result.errors + result.failures)
        print_message(self._testMethodName, 'SUCCESS' if ok else 'FAILURE', 'PASSED' if ok else 'FAILED')

    # ---- helpers ---------------------------------------------------------------------------

    def roundtrip(self, export_kwargs=None, import_kwargs=None):
        """Build the scene, export it, re-import into an empty file. Returns the USD stage."""
        build_scene()
        usd_path = str(self.tempdir / "curves_roundtrip.usda")
        res = bpy.ops.wm.usd_export(filepath=usd_path, **(export_kwargs or {}))
        self.assertEqual({'FINISHED'}, res)
        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))
        res = bpy.ops.wm.usd_import(filepath=usd_path, **(import_kwargs or {}))
        self.assertEqual({'FINISHED'}, res)
        stage = Usd.Stage.Open(usd_path)
        self.assertTrue(stage)
        return stage

    def obj(self, name):
        ob = bpy.data.objects.get(name)
        self.assertIsNotNone(ob, f"Object {name} missing after import")
        return ob

    def curves_ob(self, name):
        ob = self.obj(name)
        self.assertEqual('CURVES', ob.type, f"{name} did not re-import as a Curves object")
        return ob

    def assertVecListAlmostEqual(self, expected, actual, places=4):
        self.assertEqual(len(expected), len(actual))
        for e, a in zip(expected, actual):
            self.assertEqual(len(e), len(a))
            for ec, ac in zip(e, a):
                self.assertAlmostEqual(ec, ac, places=places)

    def assertListAlmostEqual(self, expected, actual, places=4):
        self.assertEqual(len(expected), len(actual))
        for e, a in zip(expected, actual):
            self.assertAlmostEqual(e, a, places=places)

    def prim_property_names(self, prim):
        return {p.GetName() for p in prim.GetProperties()}

    # ---- which schema is written, which type comes back -------------------------------------

    def test_schemas_written(self):
        stage = self.roundtrip()

        def kind(path):
            prim = stage.GetPrimAtPath(path)
            self.assertTrue(prim.IsValid(), path)
            return prim.GetTypeName()

        # Legacy bezier/poly and new Catmull-Rom/bezier/poly -> UsdGeomBasisCurves.
        self.assertEqual("BasisCurves", kind("/root/LegacyBezier3D/LegacyBezier3D"))
        self.assertEqual("BasisCurves", kind("/root/LegacyBezierCyclic/LegacyBezierCyclic"))
        self.assertEqual("BasisCurves", kind("/root/LegacyBezier2D/LegacyBezier2D"))
        self.assertEqual("BasisCurves", kind("/root/LegacyPoly/LegacyPoly"))
        self.assertEqual("BasisCurves", kind("/root/LegacyMultiPoly/LegacyMultiPoly"))
        self.assertEqual("BasisCurves", kind("/root/SurfaceMesh/HairCatmullRom/HairCatmullRom"))
        self.assertEqual("BasisCurves", kind("/root/HairCatmullRomCyclic/HairCatmullRomCyclic"))
        self.assertEqual("BasisCurves", kind("/root/HairPoly/HairPoly"))
        self.assertEqual("BasisCurves", kind("/root/HairBezier/HairBezier"))
        # Legacy and new NURBS -> UsdGeomNurbsCurves.
        self.assertEqual("NurbsCurves", kind("/root/LegacyNurbs/LegacyNurbs"))
        self.assertEqual("NurbsCurves", kind("/root/LegacyNurbsCyclic/LegacyNurbsCyclic"))
        self.assertEqual("NurbsCurves", kind("/root/LegacyNurbsBezierKnots/LegacyNurbsBezierKnots"))
        self.assertEqual("NurbsCurves", kind("/root/HairNurbs/HairNurbs"))
        self.assertEqual("NurbsCurves", kind("/root/HairNurbsCyclic/HairNurbsCyclic"))
        # Text -> tessellated UsdGeomMesh.
        self.assertEqual("Mesh", kind("/root/TextObj/TextObj"))

        bc = UsdGeom.BasisCurves(stage.GetPrimAtPath("/root/LegacyBezier3D/LegacyBezier3D"))
        self.assertEqual("cubic", bc.GetTypeAttr().Get())
        self.assertEqual("bezier", bc.GetBasisAttr().Get())
        self.assertEqual("nonperiodic", bc.GetWrapAttr().Get())
        bc = UsdGeom.BasisCurves(stage.GetPrimAtPath("/root/LegacyPoly/LegacyPoly"))
        self.assertEqual("linear", bc.GetTypeAttr().Get())
        self.assertEqual("periodic", bc.GetWrapAttr().Get())
        bc = UsdGeom.BasisCurves(stage.GetPrimAtPath("/root/SurfaceMesh/HairCatmullRom/HairCatmullRom"))
        self.assertEqual("catmullRom", bc.GetBasisAttr().Get())
        self.assertEqual("pinned", bc.GetWrapAttr().Get())
        bc = UsdGeom.BasisCurves(stage.GetPrimAtPath("/root/HairCatmullRomCyclic/HairCatmullRomCyclic"))
        self.assertEqual("periodic", bc.GetWrapAttr().Get())

    def test_mixed_curve_types_not_exported(self):
        # Known gap: a Curves object (or legacy Curve) with more than one curve type in it
        # is skipped by the exporter with a warning; only the Xform is written.
        stage = self.roundtrip()
        for name in ("HairMixed", "LegacyMixed"):
            xform = stage.GetPrimAtPath(f"/root/{name}")
            self.assertTrue(xform.IsValid())
            self.assertEqual("Xform", xform.GetTypeName())
            self.assertEqual([], list(xform.GetChildren()), f"{name} should have no geometry prim")
            self.assertEqual('EMPTY', self.obj(name).type)

    def test_reimported_object_types(self):
        self.roundtrip()
        # Legacy Curve objects never come back as legacy Curve: always the new Curves type.
        for name in ("LegacyBezierCyclic", "LegacyNurbs", "LegacyNurbsCyclic",
                     "LegacyNurbsBezierKnots", "LegacyMultiPoly"):
            self.assertEqual('CURVES', self.obj(name).type, name)
        for name in ("HairCatmullRom", "HairCatmullRomCyclic", "HairPoly", "HairBezier",
                     "HairNurbs", "HairNurbsCyclic"):
            self.assertEqual('CURVES', self.obj(name).type, name)
        self.assertEqual('MESH', self.obj("TextObj").type)
        self.assertEqual(0, len([ob for ob in bpy.data.objects if ob.type == 'CURVE']))
        self.assertEqual(0, len([ob for ob in bpy.data.objects if ob.type == 'FONT']))

    # ---- legacy bezier ----------------------------------------------------------------------

    def test_legacy_bezier_cyclic_points_radius_tilt(self):
        self.roundtrip()
        ob = self.curves_ob("LegacyBezierCyclic")
        hc = ob.data
        self.assertEqual([CURVE_TYPE_BEZIER], _attr(hc, "curve_type"))
        self.assertEqual([True], _attr(hc, "cyclic"))
        expected = [(math.cos(math.radians(120 * i)), math.sin(math.radians(120 * i)), 0.1 * i) for i in range(3)]
        self.assertVecListAlmostEqual(expected, _attr(hc, "position"))
        self.assertListAlmostEqual([1.0, 1.5, 2.0], _attr(hc, "radius"))
        self.assertListAlmostEqual([0.0, 0.2, 0.4], _attr(hc, "tilt"))

    def test_legacy_bezier_widths_written_as_double_radius(self):
        stage = self.roundtrip()
        bc = UsdGeom.BasisCurves(stage.GetPrimAtPath("/root/LegacyBezierCyclic/LegacyBezierCyclic"))
        self.assertListAlmostEqual([2.0, 3.0, 4.0], list(bc.GetWidthsAttr().Get()))
        self.assertEqual("varying", bc.GetWidthsInterpolation())
        # Tilt is written as a generic "tilt" primvar, with varying interpolation on bezier.
        tilt = UsdGeom.PrimvarsAPI(bc.GetPrim()).GetPrimvar("tilt")
        self.assertTrue(tilt.IsDefined())
        self.assertListAlmostEqual([0.0, 0.2, 0.4], list(tilt.Get()))
        # 3 control points of a cyclic bezier -> 9 USD points (control + handles per segment).
        self.assertEqual([9], list(bc.GetCurveVertexCountsAttr().Get()))

    def test_legacy_bezier_handle_positions(self):
        self.roundtrip()
        hc = self.curves_ob("LegacyBezier3D.001").data
        hl = _attr(hc, "handle_left")
        hr = _attr(hc, "handle_right")
        # Interior handles survive through the USD bezier point stream.
        self.assertVecListAlmostEqual([(0.5, 1.2, 0.5), (1.6, 0.6, 1.0), (2.6667, 0.6667, 0.3333)], hl[1:])
        self.assertVecListAlmostEqual([(0.5, 0.5, 0.2), (1.5, 0.8, 0.5), (2.4, -0.6, 1.0)], hr[:3])
        # Known gap (documented): the very first left handle and the very last right handle of a
        # non-cyclic bezier are not part of the USD point stream; the importer mirrors the
        # opposite handle instead. Set (-0.5, -0.5, 0.0) -> comes back as the mirror of
        # handle_right[0] about the control point.
        self.assertVecListAlmostEqual([(-0.5, -0.5, -0.2)], hl[:1])

    @unittest.expectedFailure
    def test_legacy_bezier_first_left_handle(self):
        # Lost at export: first left handle of a non-cyclic bezier is not written.
        self.roundtrip()
        hc = self.curves_ob("LegacyBezier3D.001").data
        self.assertVecListAlmostEqual([(-0.5, -0.5, 0.0)], _attr(hc, "handle_left")[:1])

    @unittest.expectedFailure
    def test_legacy_bezier_handle_types(self):
        # Lost at export: handle types (FREE/VECTOR/ALIGNED/AUTO) are not written to USD;
        # the importer sets everything to ALIGN.
        self.roundtrip()
        hc = self.curves_ob("LegacyBezier3D.001").data
        self.assertEqual([BEZIER_HANDLE_FREE, BEZIER_HANDLE_FREE, BEZIER_HANDLE_ALIGN, BEZIER_HANDLE_VECTOR],
                         _attr(hc, "handle_type_left"))

    def test_legacy_bezier_handle_types_collapse_to_align(self):
        # Documents the known gap above in its current form.
        self.roundtrip()
        hc = self.curves_ob("LegacyBezier3D.001").data
        self.assertEqual([BEZIER_HANDLE_ALIGN] * 4, _attr(hc, "handle_type_left"))
        self.assertEqual([BEZIER_HANDLE_ALIGN] * 4, _attr(hc, "handle_type_right"))

    def test_legacy_bezier_3d_points_radius_tilt_transform(self):
        self.roundtrip()
        parent = self.obj("LegacyBezier3D")
        # Object transform survives on the parent Xform (which becomes an Empty, see below).
        self.assertVecListAlmostEqual([(1, 2, 3)], [tuple(parent.location)])
        self.assertVecListAlmostEqual([(0.1, 0.2, 0.3)], [tuple(parent.rotation_euler)])
        self.assertVecListAlmostEqual([(1, 2, 1.5)], [tuple(parent.scale)])
        hc = self.curves_ob("LegacyBezier3D.001").data
        self.assertVecListAlmostEqual([(0, 0, 0), (1, 1, 0.5), (2, 0, 1), (3, 1, 0)], _attr(hc, "position"))
        self.assertListAlmostEqual([0.5, 0.75, 1.0, 1.25], _attr(hc, "radius"))
        self.assertListAlmostEqual([math.radians(10 * (i + 1)) for i in range(4)], _attr(hc, "tilt"))

    def test_legacy_bevel_extrude_duplicates_curve_instead_of_mesh(self):
        # Known gap (documented): a legacy curve with bevel/extrude evaluates to a mesh, which
        # the depsgraph exposes as an extra geometry-component instance. The exporter writes
        # that instance with the curves writer, so the .usda contains the *same* BasisCurves
        # twice (<name> and a child Xform <name>_0) and no Mesh for the bevel geometry. On
        # import the object becomes an Empty with two identical Curves children.
        stage = self.roundtrip()
        for name in ("LegacyBezier3D", "LegacyPoly", "LegacyBezier2D"):
            main = stage.GetPrimAtPath(f"/root/{name}/{name}")
            dup = stage.GetPrimAtPath(f"/root/{name}/{name}_0/{name}")
            self.assertEqual("BasisCurves", main.GetTypeName(), name)
            self.assertEqual("BasisCurves", dup.GetTypeName(), name)
            self.assertEqual(UsdGeom.BasisCurves(main).GetPointsAttr().Get(),
                             UsdGeom.BasisCurves(dup).GetPointsAttr().Get())
            mesh_prims = [p for p in Usd.PrimRange(stage.GetPrimAtPath(f"/root/{name}"))
                          if p.GetTypeName() == "Mesh"]
            self.assertEqual([], mesh_prims, f"{name}: no Mesh is written for the bevel geometry")

            self.assertEqual('EMPTY', self.obj(name).type)
            children = [ob for ob in bpy.data.objects if ob.parent == self.obj(name)]
            self.assertEqual(2, len(children), name)
            self.assertTrue(all(ob.type == 'CURVES' for ob in children))
        # A legacy curve without bevel/extrude is written once and stays a single object.
        self.assertFalse(stage.GetPrimAtPath("/root/LegacyBezierCyclic/LegacyBezierCyclic_0").IsValid())
        self.assertEqual('CURVES', self.obj("LegacyBezierCyclic").type)

    @unittest.expectedFailure
    def test_legacy_bevel_geometry_written_as_mesh(self):
        # Lost at export: bevel_depth/extrude geometry is neither written as a Mesh nor as
        # a curve attribute.
        stage = self.roundtrip()
        mesh_prims = [p for p in Usd.PrimRange(stage.GetPrimAtPath("/root/LegacyBezier3D"))
                      if p.GetTypeName() == "Mesh"]
        self.assertGreater(len(mesh_prims), 0)

    def test_legacy_curve_shape_settings_not_written(self):
        # Known gap (documented): none of the legacy Curve data-block settings are written.
        stage = self.roundtrip()
        prim = stage.GetPrimAtPath("/root/LegacyBezier3D/LegacyBezier3D")
        names = " ".join(self.prim_property_names(prim)).lower()
        for lost in ("bevel", "extrude", "offset", "resolution", "twist", "fill", "taper",
                     "dimensions", "softbody", "smooth"):
            self.assertNotIn(lost, names, f"{lost} unexpectedly written for legacy curve")
        # ... and the Curves object that comes back has no attribute for them either.
        hc = self.curves_ob("LegacyBezier3D.001").data
        attr_names = {a.name for a in hc.attributes}
        self.assertEqual({"position", "radius", "tilt", "curve_type", "handle_left", "handle_right",
                          "handle_type_left", "handle_type_right"}, attr_names)

    @unittest.expectedFailure
    def test_legacy_curve_resolution_preserved(self):
        # Lost at export: resolution_u / render_resolution_u / spline resolution are excluded.
        self.roundtrip()
        hc = self.curves_ob("LegacyBezier3D.001").data
        self.assertIn("resolution", {a.name for a in hc.attributes})

    @unittest.expectedFailure
    def test_legacy_2d_curve_dimensions_and_fill(self):
        # Lost at export: 2D/3D dimension and fill_mode are not written; the 2D filled face
        # comes back as a plain cyclic bezier Curves object.
        self.roundtrip()
        ob = self.obj("LegacyBezier2D.001")
        self.assertEqual('CURVE', ob.type)
        self.assertEqual('2D', ob.data.dimensions)

    def test_legacy_2d_curve_points_cyclic(self):
        self.roundtrip()
        hc = self.curves_ob("LegacyBezier2D.001").data
        self.assertEqual([True], _attr(hc, "cyclic"))
        self.assertVecListAlmostEqual([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], _attr(hc, "position"))

    def test_legacy_material_binding_written_but_not_assigned(self):
        stage = self.roundtrip()
        prim = stage.GetPrimAtPath("/root/LegacyBezier3D/LegacyBezier3D")
        binding = UsdShade.MaterialBindingAPI(prim).GetDirectBinding()
        self.assertEqual("/root/_materials/CurveMat", str(binding.GetMaterialPath()))
        # Known gap (documented): the curves importer does not read material bindings, and
        # with the default options the material is not even created.
        self.assertIsNone(bpy.data.materials.get("CurveMat"))
        self.assertEqual(0, len(self.curves_ob("LegacyBezier3D.001").material_slots))
        self.assertEqual(0, len(self.curves_ob("HairCatmullRom").material_slots))

    @unittest.expectedFailure
    def test_legacy_material_assigned_after_import(self):
        # Lost at import: material:binding on BasisCurves/NurbsCurves is ignored.
        self.roundtrip()
        self.assertEqual("CurveMat", self.curves_ob("LegacyBezier3D.001").material_slots[0].material.name)

    def test_material_created_with_import_all_materials_option(self):
        # With import_all_materials=True the material data-block exists, but is still not
        # assigned to any curve (known gap, documented).
        self.roundtrip(import_kwargs={"import_all_materials": True})
        self.assertIsNotNone(bpy.data.materials.get("CurveMat"))
        self.assertEqual(0, len(self.curves_ob("LegacyBezier3D.001").material_slots))

    # ---- legacy NURBS -----------------------------------------------------------------------

    def test_legacy_nurbs_order_knots_weights(self):
        stage = self.roundtrip()
        nc = UsdGeom.NurbsCurves(stage.GetPrimAtPath("/root/LegacyNurbs/LegacyNurbs"))
        self.assertEqual([3], list(nc.GetOrderAttr().Get()))
        self.assertEqual([6], list(nc.GetCurveVertexCountsAttr().Get()))
        self.assertEqual([0, 0, 0, 1, 2, 3, 4, 4, 4], list(nc.GetKnotsAttr().Get()))
        self.assertListAlmostEqual([1.0, 1.5, 2.0, 2.5, 3.0, 3.5], list(nc.GetPointWeightsAttr().Get()))
        self.assertListAlmostEqual([0.2, 0.4, 0.6, 0.8, 1.0, 1.2], list(nc.GetWidthsAttr().Get()))

        hc = self.curves_ob("LegacyNurbs").data
        self.assertEqual([CURVE_TYPE_NURBS], _attr(hc, "curve_type"))
        self.assertEqual([3], _attr(hc, "nurbs_order"))
        self.assertEqual([NURBS_KNOT_MODE_ENDPOINT], _attr(hc, "knots_mode"))
        self.assertEqual([False], _attr(hc, "cyclic"))
        self.assertListAlmostEqual([1.0, 1.5, 2.0, 2.5, 3.0, 3.5], _attr(hc, "nurbs_weight"))
        self.assertVecListAlmostEqual([(0.5 * i, math.sin(i), 0.2 * i) for i in range(6)], _attr(hc, "position"))
        self.assertListAlmostEqual([0.1 * (i + 1) for i in range(6)], _attr(hc, "radius"))
        self.assertListAlmostEqual([0.1 * i for i in range(6)], _attr(hc, "tilt"))

    def test_legacy_nurbs_cyclic(self):
        stage = self.roundtrip()
        nc = UsdGeom.NurbsCurves(stage.GetPrimAtPath("/root/LegacyNurbsCyclic/LegacyNurbsCyclic"))
        # Cyclic NURBS: 6 control points become 9 (order-1 points repeated) with uniform knots.
        self.assertEqual([9], list(nc.GetCurveVertexCountsAttr().Get()))
        self.assertEqual(list(range(13)), list(nc.GetKnotsAttr().Get()))
        self.assertListAlmostEqual([1, 1.2, 1, 1.2, 1, 1.2, 1, 1.2, 1], list(nc.GetPointWeightsAttr().Get()))
        hc = self.curves_ob("LegacyNurbsCyclic").data
        self.assertEqual([True], _attr(hc, "cyclic"))
        self.assertEqual([4], _attr(hc, "nurbs_order"))
        self.assertEqual([NURBS_KNOT_MODE_NORMAL], _attr(hc, "knots_mode"))
        self.assertEqual(6, len(hc.points))
        self.assertListAlmostEqual([1, 1.2, 1, 1.2, 1, 1.2], _attr(hc, "nurbs_weight"))
        self.assertListAlmostEqual([0.3 + 0.1 * i for i in range(6)], _attr(hc, "radius"))

    def test_legacy_nurbs_bezier_knots(self):
        stage = self.roundtrip()
        nc = UsdGeom.NurbsCurves(stage.GetPrimAtPath("/root/LegacyNurbsBezierKnots/LegacyNurbsBezierKnots"))
        self.assertEqual([0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3], list(nc.GetKnotsAttr().Get()))
        hc = self.curves_ob("LegacyNurbsBezierKnots").data
        self.assertEqual([NURBS_KNOT_MODE_BEZIER], _attr(hc, "knots_mode"))
        self.assertEqual([4], _attr(hc, "nurbs_order"))

    # ---- legacy poly ------------------------------------------------------------------------

    def test_legacy_poly(self):
        stage = self.roundtrip()
        bc = UsdGeom.BasisCurves(stage.GetPrimAtPath("/root/LegacyPoly/LegacyPoly"))
        self.assertEqual("linear", bc.GetTypeAttr().Get())
        self.assertEqual("vertex", bc.GetWidthsInterpolation())
        hc = self.curves_ob("LegacyPoly.001").data
        self.assertEqual([CURVE_TYPE_POLY], _attr(hc, "curve_type"))
        self.assertEqual([True], _attr(hc, "cyclic"))
        self.assertVecListAlmostEqual([(i, 0.1 * i * i, 0.3 * i) for i in range(5)], _attr(hc, "position"))
        self.assertListAlmostEqual([0.2 * (i + 1) for i in range(5)], _attr(hc, "radius"))
        self.assertListAlmostEqual([0.3 * i for i in range(5)], _attr(hc, "tilt"))

        hc = self.curves_ob("LegacyMultiPoly").data
        self.assertEqual(2, len(hc.curves))
        self.assertEqual([CURVE_TYPE_POLY, CURVE_TYPE_POLY], _attr(hc, "curve_type"))
        self.assertListAlmostEqual([1, 1, 1, 2, 2, 2], _attr(hc, "radius"))

    # ---- new Curves (hair) ------------------------------------------------------------------

    def test_curves_catmull_rom_points_radius_and_attributes(self):
        stage = self.roundtrip()
        prim = stage.GetPrimAtPath("/root/SurfaceMesh/HairCatmullRom/HairCatmullRom")
        pv = UsdGeom.PrimvarsAPI(prim)
        self.assertEqual("vertex", pv.GetPrimvar("my_float").GetInterpolation())
        self.assertEqual("uniform", pv.GetPrimvar("my_int").GetInterpolation())
        self.assertEqual("color4f[]", str(pv.GetPrimvar("my_color").GetTypeName()))
        self.assertEqual("color4f[]", str(pv.GetPrimvar("my_bcolor").GetTypeName()))
        self.assertEqual("uchar[]", str(pv.GetPrimvar("my_int8").GetTypeName()))
        self.assertEqual("quatf[]", str(pv.GetPrimvar("my_quat").GetTypeName()))
        self.assertEqual("texCoord2f[]", str(pv.GetPrimvar("my_uv").GetTypeName()))
        self.assertEqual("bool[]", str(pv.GetPrimvar("my_bool").GetTypeName()))
        self.assertTrue(pv.GetPrimvar("surface_uv_coordinate").IsDefined())
        self.assertTrue(pv.GetPrimvar("tilt").IsDefined())

        ob = self.curves_ob("HairCatmullRom")
        hc = ob.data
        self.assertEqual([5, 6], [c.points_length for c in hc.curves])
        n = len(hc.points)
        expected_pos = [(ci, pi * 0.3, 0.1 * pi * pi) for ci, cnt in enumerate((5, 6)) for pi in range(cnt)]
        self.assertVecListAlmostEqual(expected_pos, _attr(hc, "position"))
        self.assertListAlmostEqual([0.01 * (k + 1) for k in range(n)], _attr(hc, "radius"))
        self.assertListAlmostEqual([i / (n - 1) for i in range(n)], _attr(hc, "my_float"))
        self.assertVecListAlmostEqual([(i / (n - 1), 0.5, 1 - i / (n - 1), 0.25) for i in range(n)],
                                      _attr(hc, "my_color"))
        self.assertEqual([7, 8], _attr(hc, "my_int"))
        self.assertEqual([3, 4], _attr(hc, "my_int8"))
        self.assertEqual([bool(i % 2) for i in range(n)], _attr(hc, "my_bool"))
        self.assertVecListAlmostEqual([(i, -i, 0.5) for i in range(n)], _attr(hc, "my_vec"))
        self.assertVecListAlmostEqual([(0.25, 0.75), (0.75, 0.75)], _attr(hc, "my_uv"))
        self.assertVecListAlmostEqual([(0.7071, 0.7071, 0, 0), (0.7071, 0, 0.7071, 0)], _attr(hc, "my_quat"))
        self.assertVecListAlmostEqual([(0.1, 0.3), (0.3, 0.3)], _attr(hc, "surface_uv_coordinate"))
        self.assertListAlmostEqual([0.05 * i for i in range(n)], _attr(hc, "tilt"))
        self.assertEqual({"my_float": 'FLOAT', "my_color": 'FLOAT_COLOR', "my_int": 'INT', "my_int8": 'INT8',
                          "my_bool": 'BOOLEAN', "my_vec": 'FLOAT_VECTOR', "my_uv": 'FLOAT2',
                          "my_quat": 'QUATERNION', "surface_uv_coordinate": 'FLOAT2'},
                         {a.name: a.data_type for a in hc.attributes if a.name in (
                             "my_float", "my_color", "my_int", "my_int8", "my_bool", "my_vec", "my_uv",
                             "my_quat", "surface_uv_coordinate")})

    def test_curves_byte_color_attribute_promoted_to_float_color(self):
        # Altered (documented): BYTE_COLOR is written as color4f and comes back as FLOAT_COLOR.
        self.roundtrip()
        hc = self.curves_ob("HairCatmullRom").data
        self.assertEqual('FLOAT_COLOR', hc.attributes["my_bcolor"].data_type)
        n = len(hc.points)
        self.assertVecListAlmostEqual([(0.0, i / (n - 1), 1.0, 1.0) for i in range(n)], _attr(hc, "my_bcolor"), places=2)

    @unittest.expectedFailure
    def test_curves_byte_color_type_preserved(self):
        self.roundtrip()
        self.assertEqual('BYTE_COLOR', self.curves_ob("HairCatmullRom").data.attributes["my_bcolor"].data_type)

    def test_curves_builtin_attributes_excluded(self):
        # Known gap (documented): resolution and normal_mode are explicitly excluded by the
        # exporter, so they are neither written nor re-imported.
        stage = self.roundtrip()
        prim = stage.GetPrimAtPath("/root/SurfaceMesh/HairCatmullRom/HairCatmullRom")
        names = self.prim_property_names(prim)
        self.assertNotIn("primvars:resolution", names)
        self.assertNotIn("primvars:normal_mode", names)
        hc = self.curves_ob("HairCatmullRom").data
        self.assertNotIn("resolution", {a.name for a in hc.attributes})
        self.assertNotIn("normal_mode", {a.name for a in hc.attributes})
        hc = self.curves_ob("HairBezier").data
        self.assertNotIn("resolution", {a.name for a in hc.attributes})

    @unittest.expectedFailure
    def test_curves_resolution_and_normal_mode_preserved(self):
        self.roundtrip()
        hc = self.curves_ob("HairCatmullRom").data
        self.assertEqual([7, 7], _attr(hc, "resolution"))
        self.assertEqual([NORMAL_MODE_Z_UP, NORMAL_MODE_Z_UP], _attr(hc, "normal_mode"))

    def test_curves_surface_parenting(self):
        self.roundtrip()
        ob = self.curves_ob("HairCatmullRom")
        # The object parent relation survives as the USD hierarchy: the hair sits under the
        # surface's Xform. That Xform comes back as an Empty; the mesh is a sibling child.
        self.assertIsNotNone(ob.parent)
        self.assertEqual("SurfaceMesh", ob.parent.name)
        self.assertEqual('EMPTY', ob.parent.type)
        self.assertEqual('MESH', self.obj("SurfaceMesh.001").type)
        self.assertVecListAlmostEqual([(0.5, 0.5, 0)], [tuple(ob.location)])
        # Known gap (documented): Curves.surface / surface_uv_map are not written.
        self.assertIsNone(ob.data.surface)
        self.assertEqual("", ob.data.surface_uv_map)

    @unittest.expectedFailure
    def test_curves_surface_pointer_preserved(self):
        self.roundtrip()
        hc = self.curves_ob("HairCatmullRom").data
        self.assertIsNotNone(hc.surface)
        self.assertEqual("UVMap", hc.surface_uv_map)

    def test_curves_cyclic(self):
        self.roundtrip()
        hc = self.curves_ob("HairCatmullRomCyclic").data
        self.assertEqual([True], _attr(hc, "cyclic"))
        self.assertEqual(6, len(hc.points))
        self.assertListAlmostEqual([0.02 * (i + 1) for i in range(6)], _attr(hc, "radius"))
        hc = self.curves_ob("HairPoly").data
        self.assertEqual([True], _attr(hc, "cyclic"))
        self.assertEqual([CURVE_TYPE_POLY], _attr(hc, "curve_type"))
        self.assertVecListAlmostEqual([(i, i % 2, 0.5) for i in range(4)], _attr(hc, "position"))
        self.assertListAlmostEqual([0.1 * (i + 1) for i in range(4)], _attr(hc, "radius"))
        self.assertListAlmostEqual([1.5 * i for i in range(4)], _attr(hc, "my_float"))

    def test_curves_bezier(self):
        stage = self.roundtrip()
        bc = UsdGeom.BasisCurves(stage.GetPrimAtPath("/root/HairBezier/HairBezier"))
        self.assertEqual([10], list(bc.GetCurveVertexCountsAttr().Get()))
        self.assertEqual("varying", bc.GetWidthsInterpolation())
        self.assertListAlmostEqual([0.1, 0.2, 0.3, 0.4], list(bc.GetWidthsAttr().Get()))
        pv = UsdGeom.PrimvarsAPI(bc.GetPrim())
        self.assertEqual("varying", pv.GetPrimvar("my_float").GetInterpolation())

        hc = self.curves_ob("HairBezier").data
        self.assertEqual([CURVE_TYPE_BEZIER], _attr(hc, "curve_type"))
        self.assertVecListAlmostEqual([(i, 0.5 * (i % 2), 0.0) for i in range(4)], _attr(hc, "position"))
        self.assertListAlmostEqual([0.05 * (i + 1) for i in range(4)], _attr(hc, "radius"))
        self.assertListAlmostEqual([2.5 * i for i in range(4)], _attr(hc, "my_float"))
        # Here all original handles survive because handle_left[0] happened to be the mirror
        # of handle_right[0] (see the legacy bezier test for the general case).
        self.assertVecListAlmostEqual([(i - 0.3, 0.5 * (i % 2) + 0.2, 0.1) for i in range(4)], _attr(hc, "handle_left"))
        self.assertVecListAlmostEqual([(i + 0.3, 0.5 * (i % 2) - 0.2, -0.1) for i in range(4)], _attr(hc, "handle_right"))
        # Known gap (documented): handle types collapse to ALIGN.
        self.assertEqual([BEZIER_HANDLE_ALIGN] * 4, _attr(hc, "handle_type_left"))
        self.assertEqual([BEZIER_HANDLE_ALIGN] * 4, _attr(hc, "handle_type_right"))

    def test_curves_nurbs(self):
        stage = self.roundtrip()
        nc = UsdGeom.NurbsCurves(stage.GetPrimAtPath("/root/HairNurbs/HairNurbs"))
        self.assertEqual([3], list(nc.GetOrderAttr().Get()))
        self.assertEqual([0, 0, 0, 1, 2, 3, 4, 4, 4], list(nc.GetKnotsAttr().Get()))
        self.assertListAlmostEqual([1.0 + 0.25 * i for i in range(6)], list(nc.GetPointWeightsAttr().Get()))
        hc = self.curves_ob("HairNurbs").data
        self.assertEqual([CURVE_TYPE_NURBS], _attr(hc, "curve_type"))
        self.assertEqual([3], _attr(hc, "nurbs_order"))
        self.assertEqual([NURBS_KNOT_MODE_ENDPOINT], _attr(hc, "knots_mode"))
        self.assertListAlmostEqual([1.0 + 0.25 * i for i in range(6)], _attr(hc, "nurbs_weight"))
        self.assertVecListAlmostEqual([(i * 0.5, math.cos(i), 0.0) for i in range(6)], _attr(hc, "position"))
        self.assertListAlmostEqual([0.05 * (i + 1) for i in range(6)], _attr(hc, "radius"))
        self.assertListAlmostEqual([3.5 * i for i in range(6)], _attr(hc, "my_float"))

    def test_curves_nurbs_cyclic(self):
        stage = self.roundtrip()
        nc = UsdGeom.NurbsCurves(stage.GetPrimAtPath("/root/HairNurbsCyclic/HairNurbsCyclic"))
        self.assertEqual([9], list(nc.GetCurveVertexCountsAttr().Get()))
        self.assertEqual(list(range(13)), list(nc.GetKnotsAttr().Get()))
        # Known gap (documented): custom primvars are not written for cyclic NURBS.
        self.assertFalse(UsdGeom.PrimvarsAPI(nc.GetPrim()).GetPrimvar("my_float").IsDefined())
        hc = self.curves_ob("HairNurbsCyclic").data
        self.assertEqual([True], _attr(hc, "cyclic"))
        self.assertEqual([4], _attr(hc, "nurbs_order"))
        self.assertEqual(6, len(hc.points))
        self.assertListAlmostEqual([0.05 * (i + 1) for i in range(6)], _attr(hc, "radius"))
        self.assertNotIn("my_float", {a.name for a in hc.attributes})

    @unittest.expectedFailure
    def test_curves_nurbs_cyclic_custom_attribute_preserved(self):
        # Lost at export: custom attributes on cyclic NURBS curves are skipped (TODO in exporter).
        self.roundtrip()
        hc = self.curves_ob("HairNurbsCyclic").data
        self.assertListAlmostEqual([4.5 * i for i in range(6)], _attr(hc, "my_float"))

    # ---- text -------------------------------------------------------------------------------

    def test_text_exported_as_mesh(self):
        stage = self.roundtrip()
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/root/TextObj/TextObj"))
        self.assertGreater(len(mesh.GetPointsAttr().Get()), 0)
        ob = self.obj("TextObj")
        self.assertEqual('MESH', ob.type)
        self.assertGreater(len(ob.data.vertices), 0)
        self.assertGreater(len(ob.data.polygons), 0)

    @unittest.expectedFailure
    def test_text_body_preserved(self):
        # Lost at export: text is tessellated; body/font/size/extrude are not written.
        self.roundtrip()
        ob = self.obj("TextObj")
        self.assertEqual('FONT', ob.type)
        self.assertEqual("USD", ob.data.body)

    # ---- operator options -------------------------------------------------------------------

    def test_export_curves_option_off(self):
        stage = self.roundtrip(export_kwargs={"export_curves": False})
        curve_prims = [p for p in Usd.PrimRange(stage.GetPseudoRoot())
                       if p.GetTypeName() in ("BasisCurves", "NurbsCurves")]
        self.assertEqual([], curve_prims)
        # Text is a mesh and is unaffected by export_curves.
        self.assertEqual("Mesh", stage.GetPrimAtPath("/root/TextObj/TextObj").GetTypeName())
        # The curve objects are skipped entirely (not even an Xform is written).
        self.assertFalse(stage.GetPrimAtPath("/root/SurfaceMesh/HairCatmullRom").IsValid())
        self.assertFalse(stage.GetPrimAtPath("/root/LegacyNurbs").IsValid())
        self.assertIsNone(bpy.data.objects.get("HairCatmullRom"))
        self.assertIsNone(bpy.data.objects.get("LegacyNurbs"))

    def test_import_curves_option_off(self):
        self.roundtrip(import_kwargs={"import_curves": False})
        self.assertEqual([], [ob for ob in bpy.data.objects if ob.type == 'CURVES'])
        self.assertEqual('EMPTY', self.obj("HairCatmullRom").type)
        self.assertEqual('EMPTY', self.obj("LegacyNurbs").type)
        self.assertEqual('MESH', self.obj("TextObj").type)

    def test_merge_parent_xform_does_not_remove_bevel_duplicate(self):
        # Even with merge_parent_xform the beveled legacy curve still produces an Empty with
        # two Curves children (known gap, documented).
        stage = self.roundtrip(export_kwargs={"merge_parent_xform": True})
        self.assertEqual("BasisCurves", stage.GetPrimAtPath("/root/LegacyBezier3D/LegacyBezier3D_0").GetTypeName())
        self.assertEqual('EMPTY', self.obj("LegacyBezier3D").type)
        self.assertEqual('CURVES', self.obj("LegacyBezier3D_0").type)
        # Un-beveled curves merge into a single Curves object with the transform intact.
        self.assertEqual('CURVES', self.obj("HairCatmullRom").type)
        self.assertVecListAlmostEqual([(0.5, 0.5, 0)], [tuple(self.obj("HairCatmullRom").location)])


def main():
    global args
    import argparse

    if '--' in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index('--') + 1:]
    else:
        argv = sys.argv

    parser = argparse.ArgumentParser()
    parser.add_argument('--testdir', required=True, type=pathlib.Path)
    args, remaining = parser.parse_known_args(argv)

    unittest.main(argv=remaining, verbosity=0)


if __name__ == "__main__":
    main()
