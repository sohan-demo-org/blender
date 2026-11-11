# SPDX-FileCopyrightText: 2025 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
USD round-trip audit for point instancers.

Builds a small scene in-memory (no external assets), exports it to USD, re-imports
it into an empty file and checks which instancing properties survive the trip.

Tests marked with ``unittest.expectedFailure`` document known losses in the
current exporter/importer; they are *not* expected to pass until those gaps are
fixed.

Run with::

    blender -b --factory-startup --python tests/python/bl_usd_roundtrip_point_instancers_test.py -- \
        --testdir <ABSOLUTE>/tests/files/usd
"""

import math
import os
import pathlib
import sys
import tempfile
import unittest
from pxr import Sdf, Usd, UsdGeom, UsdShade, Vt

import bpy
import mathutils

sys.path.append(str(pathlib.Path(__file__).parent.absolute()))
from modules.colored_print import (print_message, use_message_colors)


args = None

# Per-point data shared by the Geometry Nodes instancers.
POSITIONS = [(0, 0, 0), (2, 0, 0), (0, 2, 0), (2, 2, 0), (1, 1, 1)]
PROTO_INDEX = [0, 1, 0, 1, 1]
IDS = [100, 101, 102, 103, 104]
ROT_EULER = [(0, 0, 0), (0, 0, math.radians(90)), (math.radians(30), 0, 0),
             (0, math.radians(45), math.radians(10)), (0.3, 0.6, 0.9)]
SCALES = [(1, 1, 1), (2, 2, 2), (0.5, 1, 1.5), (1, 2, 1), (0.25, 0.25, 0.25)]
MASK = [True, True, False, True, True]
MY_FLOAT = [0.1, 0.2, 0.3, 0.4, 0.5]

GN_OBJECTS_LOCATION = (0, 0, 5)
PROTO_CUBE_LOCATION = (10, 0, 0)
PROTO_CONE_LOCATION = (0, 10, 0)


def make_material(name, rgba):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = rgba
    return m


def build_scene():
    """Build the point-instancer audit scene in the current (empty) file."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)

    scene_coll = bpy.context.scene.collection

    mat_red = make_material("MatRed", (1, 0, 0, 1))
    mat_blue = make_material("MatBlue", (0, 0, 1, 1))
    mat_green = make_material("MatGreen", (0, 1, 0, 1))

    # Prototype objects with non-identity transforms and distinct materials.
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    proto_cube = bpy.context.active_object
    proto_cube.name = proto_cube.data.name = "ProtoCube"
    proto_cube.location = PROTO_CUBE_LOCATION
    proto_cube.rotation_euler = (0, 0, math.radians(45))
    proto_cube.scale = (0.5, 0.5, 0.5)
    proto_cube.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cone_add(radius1=0.5, depth=1.0, vertices=8)
    proto_cone = bpy.context.active_object
    proto_cone.name = proto_cone.data.name = "ProtoCone"
    proto_cone.location = PROTO_CONE_LOCATION
    proto_cone.scale = (1, 1, 2)
    proto_cone.data.materials.append(mat_blue)

    # Collection of prototypes, used by the Collection Info variant and by the
    # legacy collection instance.
    proto_coll = bpy.data.collections.new("ProtoCollection")
    scene_coll.children.link(proto_coll)
    bpy.ops.mesh.primitive_cube_add(size=0.4)
    coll_proto_a = bpy.context.active_object
    coll_proto_a.name = coll_proto_a.data.name = "CollProtoA"
    coll_proto_a.location = (-10, 0, 0)
    coll_proto_a.data.materials.append(mat_green)
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.3, subdivisions=1)
    coll_proto_b = bpy.context.active_object
    coll_proto_b.name = coll_proto_b.data.name = "CollProtoB"
    coll_proto_b.location = (-10, 2, 0)
    coll_proto_b.data.materials.append(mat_blue)
    for ob in (coll_proto_a, coll_proto_b):
        for c in ob.users_collection:
            c.objects.unlink(ob)
        proto_coll.objects.link(ob)

    def point_mesh(name):
        me = bpy.data.meshes.new(name)
        me.from_pydata(POSITIONS, [], [])

        def attr(nm, typ, values):
            a = me.attributes.new(nm, typ, 'POINT')
            if typ in {'FLOAT_VECTOR', 'FLOAT_COLOR'}:
                key = 'vector' if typ == 'FLOAT_VECTOR' else 'color'
                a.data.foreach_set(key, [c for v in values for c in v])
            else:
                a.data.foreach_set('value', values)

        attr("proto_index", 'INT', PROTO_INDEX)
        attr("id", 'INT', IDS)
        attr("rot", 'FLOAT_VECTOR', ROT_EULER)
        attr("scl", 'FLOAT_VECTOR', SCALES)
        attr("mask", 'BOOLEAN', MASK)
        attr("my_float", 'FLOAT', MY_FLOAT)
        return me

    def gn_instancer(name, location, instance_source):
        ob = bpy.data.objects.new(name, point_mesh(name))
        scene_coll.objects.link(ob)
        ob.location = location
        mod = ob.modifiers.new("GN", 'NODES')
        tree = bpy.data.node_groups.new(name + "_tree", 'GeometryNodeTree')
        tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        mod.node_group = tree
        nodes, links = tree.nodes, tree.links
        group_in = nodes.new('NodeGroupInput')
        group_out = nodes.new('NodeGroupOutput')
        iop = nodes.new('GeometryNodeInstanceOnPoints')
        iop.inputs['Pick Instance'].default_value = True
        if instance_source == 'objects':
            join = nodes.new('GeometryNodeJoinGeometry')
            for proto in (proto_cube, proto_cone):
                info = nodes.new('GeometryNodeObjectInfo')
                info.inputs['Object'].default_value = proto
                info.inputs['As Instance'].default_value = True
                links.new(info.outputs['Geometry'], join.inputs['Geometry'])
            links.new(join.outputs['Geometry'], iop.inputs['Instance'])
        else:
            info = nodes.new('GeometryNodeCollectionInfo')
            info.inputs['Collection'].default_value = proto_coll
            info.inputs['Separate Children'].default_value = True
            links.new(info.outputs['Instances'], iop.inputs['Instance'])

        def named(nm, dtype):
            na = nodes.new('GeometryNodeInputNamedAttribute')
            na.data_type = dtype
            na.inputs['Name'].default_value = nm
            return na

        links.new(group_in.outputs['Geometry'], iop.inputs['Points'])
        links.new(named("proto_index", 'INT').outputs['Attribute'], iop.inputs['Instance Index'])
        links.new(named("rot", 'FLOAT_VECTOR').outputs['Attribute'], iop.inputs['Rotation'])
        links.new(named("scl", 'FLOAT_VECTOR').outputs['Attribute'], iop.inputs['Scale'])
        links.new(iop.outputs['Instances'], group_out.inputs['Geometry'])
        return ob

    gn_instancer("GNObjectsInstancer", GN_OBJECTS_LOCATION, 'objects')
    gn_instancer("GNCollectionInstancer", (0, 20, 5), 'collection')

    # Legacy vertex instancing.
    bpy.ops.mesh.primitive_plane_add(size=4.0)
    vert_parent = bpy.context.active_object
    vert_parent.name = vert_parent.data.name = "VertInstancer"
    vert_parent.location = (30, 0, 0)
    vert_parent.instance_type = 'VERTS'
    vert_parent.use_instance_vertices_rotation = True
    vert_parent.show_instancer_for_render = False
    bpy.ops.mesh.primitive_cube_add(size=0.5)
    vert_child = bpy.context.active_object
    vert_child.name = vert_child.data.name = "VertChild"
    vert_child.data.materials.append(mat_red)
    vert_child.parent = vert_parent
    vert_child.location = (0, 0, 1)

    # Legacy face instancing.
    bpy.ops.mesh.primitive_grid_add(size=4.0, x_subdivisions=2, y_subdivisions=2)
    face_parent = bpy.context.active_object
    face_parent.name = face_parent.data.name = "FaceInstancer"
    face_parent.location = (40, 0, 0)
    face_parent.instance_type = 'FACES'
    face_parent.use_instance_faces_scale = True
    face_parent.instance_faces_scale = 0.5
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    face_child = bpy.context.active_object
    face_child.name = face_child.data.name = "FaceChild"
    face_child.data.materials.append(mat_blue)
    face_child.parent = face_parent
    face_child.location = (0, 0, 0.5)

    # Legacy collection instance (Empty).
    coll_inst = bpy.data.objects.new("CollInstanceEmpty", None)
    scene_coll.objects.link(coll_inst)
    coll_inst.instance_type = 'COLLECTION'
    coll_inst.instance_collection = proto_coll
    coll_inst.location = (50, 0, 0)
    coll_inst.rotation_euler = (0, 0, math.radians(30))
    coll_inst.scale = (2, 2, 2)

    bpy.context.view_layer.update()


def record_instances():
    """Map instancer object name -> list of evaluated instance records (world space)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    out = {}
    for inst in depsgraph.object_instances:
        if not inst.is_instance or inst.parent is None or inst.object.type != 'MESH':
            continue
        loc, rot, scl = inst.matrix_world.decompose()
        out.setdefault(inst.parent.original.name, []).append({
            'object': inst.object.original.name,
            'loc': tuple(loc),
            'quat': tuple(rot),
            'scale': tuple(scl),
            'materials': tuple(s.material.name if s.material else None
                               for s in inst.object.material_slots),
        })
    for recs in out.values():
        recs.sort(key=lambda r: r['loc'])
    return out


def point_instancer_prims(stage):
    return [p for p in stage.Traverse() if p.IsA(UsdGeom.PointInstancer)]


def attribute_values(data, name):
    attr = data.attributes[name]
    if attr.data_type in {'FLOAT_VECTOR', 'FLOAT_COLOR', 'QUATERNION'}:
        key = {'FLOAT_VECTOR': 'vector', 'FLOAT_COLOR': 'color', 'QUATERNION': 'value'}[attr.data_type]
        return [tuple(getattr(d, key)) for d in attr.data]
    return [d.value for d in attr.data]


class AbstractUSDTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.testdir = args.testdir
        if os.environ.get("BLENDER_TEST_COLOR") is not None:
            use_message_colors()

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.tempdir = pathlib.Path(self._tempdir.name)

        self.assertTrue(self.testdir.exists(),
                        'Test dir {0} should exist'.format(self.testdir))
        self.assertTrue(self.tempdir.exists(),
                        'Temp dir {0} should exist'.format(self.tempdir))

        print_message(self._testMethodName, 'SUCCESS', 'RUN')

        # Make sure we always start with a known-empty file.
        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))

    def tearDown(self):
        self._tempdir.cleanup()

        result = self._outcome.result
        ok = all(test != self for test, _ in result.errors + result.failures)
        if not ok:
            print_message(self._testMethodName, 'FAILURE', 'FAILED')
        else:
            print_message(self._testMethodName, 'SUCCESS', 'PASSED')


class USDPointInstancerRoundTripTest(AbstractUSDTest):

    def export_scene(self, use_instancing, name="point_instancers.usda"):
        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))
        build_scene()
        self.original = record_instances()
        path = self.tempdir / name
        res = bpy.ops.wm.usd_export(filepath=str(path), use_instancing=use_instancing, evaluation_mode="RENDER")
        self.assertEqual({'FINISHED'}, res)
        return path

    def reimport(self, path, **kwargs):
        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))
        res = bpy.ops.wm.usd_import(filepath=str(path), **kwargs)
        self.assertEqual({'FINISHED'}, res)
        bpy.context.view_layer.update()
        return record_instances()

    def assertVecAlmostEqual(self, a, b, places=5):
        self.assertEqual(len(a), len(b))
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=places)

    def assertInstancesMatch(self, expected, actual, places=5, quat_places=5):
        """Compare evaluated instance lists (count, prototype, world transform, material)."""
        self.assertEqual(len(expected), len(actual))
        for e, a in zip(expected, actual):
            self.assertEqual(e['object'], a['object'].split('.')[0])
            self.assertVecAlmostEqual(e['loc'], a['loc'], places)
            self.assertVecAlmostEqual(e['scale'], a['scale'], places)
            self.assertVecAlmostEqual(e['quat'], a['quat'], quat_places)
            self.assertEqual([m.split('.')[0] for m in e['materials']],
                             [m.split('.')[0] for m in a['materials']])

    # ------------------------------------------------------------------
    # Export: which Blender instancing paths become a UsdGeomPointInstancer.
    # ------------------------------------------------------------------

    def test_export_instancing_on_writes_pointinstancer(self):
        """use_instancing=True: GN Instance-on-Points becomes a UsdGeomPointInstancer."""
        path = self.export_scene(use_instancing=True)
        stage = Usd.Stage.Open(str(path))

        instancers = {str(p.GetPath()) for p in point_instancer_prims(stage)}
        self.assertEqual(instancers, {"/root/GNObjectsInstancer/GNObjectsInstancer",
                                      "/root/GNCollectionInstancer/GNCollectionInstancer"})

        pi = UsdGeom.PointInstancer(stage.GetPrimAtPath("/root/GNObjectsInstancer/GNObjectsInstancer"))
        self.assertEqual(list(pi.GetProtoIndicesAttr().Get()), PROTO_INDEX)
        self.assertEqual(list(pi.GetIdsAttr().Get()), IDS)
        self.assertEqual(pi.GetIdsAttr().GetTypeName(), Sdf.ValueTypeNames.Int64Array)
        positions = pi.GetPositionsAttr().Get()
        self.assertEqual(len(positions), len(POSITIONS))
        for p, expected in zip(positions, POSITIONS):
            self.assertVecAlmostEqual(tuple(p), expected)
        scales = pi.GetScalesAttr().Get()
        for s, expected in zip(scales, SCALES):
            self.assertVecAlmostEqual(tuple(s), expected)
        # Orientations are written as half-precision quaternions.
        self.assertEqual(pi.GetOrientationsAttr().GetTypeName(), Sdf.ValueTypeNames.QuathArray)
        for q, euler in zip(pi.GetOrientationsAttr().Get(), ROT_EULER):
            expected = mathutils.Euler(euler).to_quaternion()
            self.assertAlmostEqual(q.GetReal(), expected.w, places=3)
            self.assertVecAlmostEqual(tuple(q.GetImaginary()), tuple(expected)[1:], places=3)

        # Prototypes are nested under <instancer>/Prototypes/Prototype_N and
        # reference the prototype objects, which are demoted to "over" so they
        # are not imaged in the scene.
        protos = [str(t) for t in pi.GetPrototypesRel().GetTargets()]
        self.assertEqual(protos, ["/root/GNObjectsInstancer/GNObjectsInstancer/Prototypes/Prototype_0",
                                  "/root/GNObjectsInstancer/GNObjectsInstancer/Prototypes/Prototype_1"])
        refs = []
        for proto in protos:
            prim = stage.GetPrimAtPath(proto)
            ref_items = prim.GetMetadata("references").prependedItems
            refs.append(str(ref_items[0].primPath))
        self.assertEqual(refs, ["/root/ProtoCone", "/root/ProtoCube"])
        for ref in refs:
            prim = stage.GetPrimAtPath(ref)
            self.assertEqual(prim.GetSpecifier(), Sdf.SpecifierOver)
            self.assertTrue(prim.GetChild(ref.split('/')[-1]).IsA(UsdGeom.Mesh))
            # Prototype mesh keeps its material binding (via a per-prototype copy).
            mesh = prim.GetChild(ref.split('/')[-1])
            self.assertTrue(mesh.HasAPI(UsdShade.MaterialBindingAPI))

        # Custom per-instance attributes are written as primvars.
        pv_api = UsdGeom.PrimvarsAPI(pi)
        self.assertTrue(pv_api.HasPrimvar("my_float"))
        self.assertVecAlmostEqual(list(pv_api.GetPrimvar("my_float").Get()), MY_FLOAT)

        # The empty base mesh of the GN object is written as a sibling Mesh prim.
        self.assertTrue(stage.GetPrimAtPath("/root/GNObjectsInstancer/GNObjectsInstancer_base").IsA(UsdGeom.Mesh))

    def test_export_mask_not_written_as_invisible_ids(self):
        """KNOWN GAP: a boolean 'mask' instance attribute is skipped by the exporter, so
        invisibleIds is never authored (documents current lossy behaviour)."""
        path = self.export_scene(use_instancing=True)
        stage = Usd.Stage.Open(str(path))
        pi = UsdGeom.PointInstancer(stage.GetPrimAtPath("/root/GNObjectsInstancer/GNObjectsInstancer"))
        self.assertFalse(pi.GetInvisibleIdsAttr().HasAuthoredValue())
        self.assertFalse(UsdGeom.PrimvarsAPI(pi).HasPrimvar("mask"))

    def test_export_instancing_off_flattens(self):
        """use_instancing=False (the default): no PointInstancer, every instance is a real Xform+Mesh."""
        path = self.export_scene(use_instancing=False)
        stage = Usd.Stage.Open(str(path))
        self.assertEqual(point_instancer_prims(stage), [])

        parent = stage.GetPrimAtPath("/root/GNObjectsInstancer")
        copies = [c for c in parent.GetChildren() if c.GetName().startswith("Proto")]
        self.assertEqual(len(copies), len(POSITIONS))
        self.assertEqual(sorted(c.GetName() for c in copies),
                         ["ProtoCone_100", "ProtoCone_102", "ProtoCube_101", "ProtoCube_103", "ProtoCube_104"])
        for c in copies:
            self.assertTrue(c.GetChild(c.GetName().split('_')[0]).IsA(UsdGeom.Mesh))
        # The prototype objects themselves stay real (def) scene prims.
        self.assertEqual(stage.GetPrimAtPath("/root/ProtoCube").GetSpecifier(), Sdf.SpecifierDef)

    def test_export_legacy_instancing_never_pointinstancer(self):
        """Legacy vertex/face/collection instancing never becomes a PointInstancer:
        with use_instancing it is written as instanceable Xform references, otherwise as copies."""
        for use_instancing in (True, False):
            path = self.export_scene(use_instancing=use_instancing, name=f"legacy_{use_instancing}.usda")
            stage = Usd.Stage.Open(str(path))
            instancers = {str(p.GetPath()) for p in point_instancer_prims(stage)}
            for name in ("VertInstancer", "FaceInstancer", "CollInstanceEmpty"):
                self.assertFalse(any(name in p for p in instancers), name)
                parent = stage.GetPrimAtPath(f"/root/{name}")
                self.assertTrue(parent.IsA(UsdGeom.Xform))
                kids = [c for c in parent.GetChildren() if c.IsA(UsdGeom.Xform)]
                if name == "CollInstanceEmpty":
                    self.assertEqual(sorted(c.GetName() for c in kids), ["CollProtoA_0", "CollProtoB_1"])
                else:
                    # 4 instances + the original child object itself (which Blender does not draw).
                    self.assertEqual(len(kids), 5)
                for kid in kids:
                    self.assertEqual(kid.IsInstanceable(), use_instancing)
                    if use_instancing:
                        ref = kid.GetMetadata("references").prependedItems[0].primPath
                        self.assertTrue(str(ref).startswith("/root/prototypes/"))
                    else:
                        self.assertTrue(any(c.IsA(UsdGeom.Mesh) for c in kid.GetChildren()))
            # The vertex instancer's own mesh is hidden for render and so is not exported;
            # the face instancer's mesh is exported.
            self.assertFalse(stage.GetPrimAtPath("/root/VertInstancer/VertInstancer").IsValid())
            self.assertTrue(stage.GetPrimAtPath("/root/FaceInstancer/FaceInstancer").IsA(UsdGeom.Mesh))

    # ------------------------------------------------------------------
    # Round trip: export with use_instancing=True, re-import with defaults.
    # ------------------------------------------------------------------

    def test_roundtrip_pointinstancer_becomes_pointcloud_with_geometry_nodes(self):
        path = self.export_scene(use_instancing=True)
        reimported = self.reimport(path)

        # Object type: the Mesh+GN instancer comes back as Empty > PointCloud (+ GN) and an empty base mesh.
        xform = bpy.data.objects["GNObjectsInstancer"]
        self.assertEqual(xform.type, 'EMPTY')
        self.assertVecAlmostEqual(tuple(xform.location), GN_OBJECTS_LOCATION)
        pc = bpy.data.objects["GNObjectsInstancer.001"]
        self.assertEqual(pc.type, 'POINTCLOUD')
        self.assertEqual(pc.parent, xform)
        self.assertEqual([m.type for m in pc.modifiers], ['NODES'])
        base = bpy.data.objects["GNObjectsInstancer_base"]
        self.assertEqual(base.type, 'MESH')
        self.assertEqual(len(base.data.vertices), 0)

        nodes = pc.modifiers[0].node_group.nodes
        iop = [n for n in nodes if n.bl_idname == 'GeometryNodeInstanceOnPoints'][0]
        self.assertTrue(iop.inputs['Pick Instance'].default_value)
        coll_info = [n for n in nodes if n.bl_idname == 'GeometryNodeCollectionInfo'][0]
        self.assertTrue(coll_info.inputs['Separate Children'].default_value)
        self.assertEqual(coll_info.inputs['Collection'].default_value.name, "GNObjectsInstancer")

        # Per-point attributes.
        self.assertEqual(len(pc.data.points), len(POSITIONS))
        for p, expected in zip(attribute_values(pc.data, "position"), POSITIONS):
            self.assertVecAlmostEqual(p, expected)
        self.assertEqual(attribute_values(pc.data, "id"), IDS)
        self.assertEqual(pc.data.attributes["id"].data_type, 'INT')  # int64 in USD -> int32 in Blender
        self.assertEqual(attribute_values(pc.data, "proto_index"), PROTO_INDEX)
        for s, expected in zip(attribute_values(pc.data, "scale"), SCALES):
            self.assertVecAlmostEqual(s, expected)
        for q, euler in zip(attribute_values(pc.data, "orientation"), ROT_EULER):
            expected = mathutils.Euler(euler).to_quaternion()
            # Half-precision quaternions: ~1e-4 error.
            self.assertVecAlmostEqual(q, tuple(expected), places=3)
        # No invisibleIds were written, so every instance is visible.
        self.assertEqual(attribute_values(pc.data, "mask"), [True] * len(POSITIONS))

        # Prototype collections are nested per instancer and ordered by prototype index.
        protos_coll = bpy.data.collections["prototypes"]
        self.assertTrue(protos_coll.hide_viewport and protos_coll.hide_render)
        inst_coll = bpy.data.collections["GNObjectsInstancer"]
        self.assertIn(inst_coll.name, [c.name for c in protos_coll.children])
        proto_colls = sorted(c.name.split('.')[0] for c in inst_coll.children)
        self.assertEqual(proto_colls, ["proto_0", "proto_1"])
        proto_meshes = {}
        for c in inst_coll.children:
            meshes = [o for o in c.all_objects if o.type == 'MESH']
            self.assertEqual(len(meshes), 1)
            proto_meshes[c.name.split('.')[0]] = meshes[0]
        self.assertEqual(proto_meshes["proto_0"].name, "ProtoCone")
        self.assertEqual(proto_meshes["proto_1"].name, "ProtoCube")
        # Prototype materials survive (as duplicated material data-blocks).
        self.assertEqual(proto_meshes["proto_0"].material_slots[0].material.name.split('.')[0], "MatBlue")
        self.assertEqual(proto_meshes["proto_1"].material_slots[0].material.name.split('.')[0], "MatRed")

        # Evaluated instances: count, prototype, world transform (within half-float error) and material.
        self.assertInstancesMatch(self.original["GNObjectsInstancer"],
                                  reimported["GNObjectsInstancer.001"], places=3, quat_places=3)
        self.assertInstancesMatch(self.original["GNCollectionInstancer"],
                                  reimported["GNCollectionInstancer.001"], places=3, quat_places=3)

    def test_roundtrip_instancing_off_realizes_meshes(self):
        """Default export (use_instancing=False) round-trips geometry but realizes every instance."""
        path = self.export_scene(use_instancing=False)
        self.reimport(path)
        self.assertEqual([o for o in bpy.data.objects if o.type == 'POINTCLOUD'], [])
        parent = bpy.data.objects["GNObjectsInstancer"]
        self.assertEqual(parent.type, 'EMPTY')
        copies = [o for o in bpy.data.objects if o.parent == parent and o.type == 'MESH'
                  and o.name.startswith("Proto")]
        self.assertEqual(len(copies), len(POSITIONS))
        copies.sort(key=lambda o: tuple(o.matrix_world.translation))
        for ob, expected in zip(copies, self.original["GNObjectsInstancer"]):
            self.assertEqual(ob.name.split('.')[0], expected['object'])
            self.assertVecAlmostEqual(tuple(ob.matrix_world.translation), expected['loc'])
            self.assertEqual(ob.material_slots[0].material.name, expected['materials'][0])
        # Materials are not duplicated on this path.
        self.assertEqual(sorted(m.name for m in bpy.data.materials), ["MatBlue", "MatGreen", "MatRed"])

    def test_roundtrip_legacy_instancing_becomes_collection_instances(self):
        """Legacy vertex/face/collection instancing comes back as one collection-instance Empty
        per instance (not as the original instance_type), plus an extra copy of the child object."""
        path = self.export_scene(use_instancing=True)
        reimported = self.reimport(path)

        for name, child in (("VertInstancer", "VertChild"), ("FaceInstancer", "FaceChild")):
            parent = bpy.data.objects[name]
            self.assertEqual(parent.type, 'EMPTY')
            self.assertEqual(parent.instance_type, 'NONE')
            kids = [o for o in bpy.data.objects if o.parent == parent and o.name.startswith(child)]
            self.assertEqual(len(kids), 5)  # 4 instances + the original child object
            for kid in kids:
                self.assertEqual(kid.type, 'EMPTY')
                self.assertEqual(kid.instance_type, 'COLLECTION')
                self.assertEqual(kid.instance_collection.name.split('.')[0], "proto")
            # The 4 real instances keep their baked world transforms and material.
            expected = self.original[name]
            actual = [r for k in kids for r in reimported.get(k.name, [])]
            actual.sort(key=lambda r: r['loc'])
            extra = [r for r in actual if not any(
                all(abs(a - b) < 1e-4 for a, b in zip(r['loc'], e['loc'])) for e in expected)]
            self.assertEqual(len(extra), 1)
            actual = [r for r in actual if r not in extra]
            self.assertInstancesMatch(expected, actual)

        coll_inst = bpy.data.objects["CollInstanceEmpty"]
        self.assertEqual(coll_inst.type, 'EMPTY')
        self.assertEqual(coll_inst.instance_type, 'NONE')  # was 'COLLECTION'
        kids = sorted((o for o in bpy.data.objects if o.parent == coll_inst), key=lambda o: o.name)
        self.assertEqual([o.name for o in kids], ["CollProtoA_0", "CollProtoB_1"])
        actual = sorted((r for k in kids for r in reimported[k.name]), key=lambda r: r['loc'])
        self.assertInstancesMatch(self.original["CollInstanceEmpty"], actual)

    def test_roundtrip_support_scene_instancing_off_realizes_legacy(self):
        path = self.export_scene(use_instancing=True)
        self.reimport(path, support_scene_instancing=False)
        kids = [o for o in bpy.data.objects if o.parent == bpy.data.objects["VertInstancer"]]
        self.assertEqual(len(kids), 5)
        for kid in kids:
            self.assertEqual(kid.instance_type, 'NONE')
            # Realized mesh copy (plus an Empty created from the prototype's "_materials" Scope).
            self.assertEqual(sorted(c.type for c in kid.children), ['EMPTY', 'MESH'])
        # The PointInstancer path is unaffected by this option.
        self.assertEqual(bpy.data.objects["GNObjectsInstancer.001"].type, 'POINTCLOUD')

    # ------------------------------------------------------------------
    # Known losses, documented as expected failures.
    # ------------------------------------------------------------------

    @unittest.expectedFailure
    def test_roundtrip_invisible_ids(self):
        """LOST: a 'mask' attribute is never exported as invisibleIds, and imported invisibleIds
        (mask=False) are dropped from the geometry on re-export instead of being re-authored."""
        path = self.export_scene(use_instancing=True)
        stage = Usd.Stage.Open(str(path))
        pi = UsdGeom.PointInstancer(stage.GetPrimAtPath("/root/GNObjectsInstancer/GNObjectsInstancer"))
        self.assertEqual(list(pi.GetInvisibleIdsAttr().Get() or []), [102])

    @unittest.expectedFailure
    def test_roundtrip_invisible_ids_reexport(self):
        """LOST on re-export: invisibleIds -> mask attribute on import works, but exporting again
        drops the hidden instance entirely (4 instances, no invisibleIds)."""
        path = self.export_scene(use_instancing=True)
        stage = Usd.Stage.Open(str(path))
        pi = UsdGeom.PointInstancer(stage.GetPrimAtPath("/root/GNObjectsInstancer/GNObjectsInstancer"))
        pi.CreateInvisibleIdsAttr().Set(Vt.Int64Array([102]))
        stage.GetRootLayer().Save()
        del stage

        self.reimport(path)
        pc = bpy.data.objects["GNObjectsInstancer.001"]
        self.assertEqual(attribute_values(pc.data, "mask"), MASK)  # import side is fine

        out = self.tempdir / "reexport.usda"
        bpy.ops.wm.usd_export(filepath=str(out), use_instancing=True, evaluation_mode="RENDER")
        stage = Usd.Stage.Open(str(out))
        pi = [UsdGeom.PointInstancer(p) for p in point_instancer_prims(stage)
              if "GNObjectsInstancer" in str(p.GetPath())][0]
        self.assertEqual(list(pi.GetIdsAttr().Get()), IDS)
        self.assertEqual(list(pi.GetInvisibleIdsAttr().Get() or []), [102])

    @unittest.expectedFailure
    def test_roundtrip_custom_instance_attributes(self):
        """LOST at import: custom per-instance attributes are written as primvars on the
        PointInstancer but the importer does not read them onto the point cloud."""
        path = self.export_scene(use_instancing=True)
        self.reimport(path)
        pc = bpy.data.objects["GNObjectsInstancer.001"]
        self.assertIn("my_float", pc.data.attributes)

    @unittest.expectedFailure
    def test_roundtrip_orientation_precision(self):
        """ALTERED: orientations are written as quath (half float), so instance rotations
        only survive to ~3 decimal places."""
        path = self.export_scene(use_instancing=True)
        self.reimport(path)
        pc = bpy.data.objects["GNObjectsInstancer.001"]
        for q, euler in zip(attribute_values(pc.data, "orientation"), ROT_EULER):
            self.assertVecAlmostEqual(q, tuple(mathutils.Euler(euler).to_quaternion()), places=5)

    @unittest.expectedFailure
    def test_roundtrip_prototype_object_stays_in_scene(self):
        """LOST with use_instancing=True: the prototype object itself is exported as an 'over'
        and so no longer exists as a visible scene object after re-import."""
        path = self.export_scene(use_instancing=True)
        self.reimport(path)
        visible_cubes = [o for o in bpy.data.objects if o.name.startswith("ProtoCube") and o.visible_get()]
        self.assertEqual(len(visible_cubes), 1)
        self.assertVecAlmostEqual(tuple(visible_cubes[0].matrix_world.translation), PROTO_CUBE_LOCATION)

    @unittest.expectedFailure
    def test_roundtrip_materials_not_duplicated(self):
        """ALTERED: each prototype gets its own copy of its Material prim, so re-import creates
        duplicate material data-blocks (MatBlue, MatBlue.001, ...)."""
        path = self.export_scene(use_instancing=True)
        self.reimport(path)
        self.assertEqual(sorted(m.name for m in bpy.data.materials), ["MatBlue", "MatGreen", "MatRed"])

    @unittest.expectedFailure
    def test_roundtrip_collection_instance_stays_single(self):
        """ALTERED: a legacy collection instance Empty comes back as a plain Empty with one
        collection-instance child per prototype object, not as one instance of one collection."""
        path = self.export_scene(use_instancing=True)
        self.reimport(path)
        coll_inst = bpy.data.objects["CollInstanceEmpty"]
        self.assertEqual(coll_inst.instance_type, 'COLLECTION')


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
