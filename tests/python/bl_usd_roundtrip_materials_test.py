# SPDX-FileCopyrightText: 2025 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
USD round-trip audit for materials.

Builds a small scene with non-default values on every material property the
USD exporter could plausibly carry, exports it to .usda, re-imports it into an
empty file and compares property-by-property.

Properties that survive are asserted directly.  Properties that are currently
lost or altered are asserted with their *current* (lossy) value and a comment
stating which stage of the trip loses them, so this test documents known gaps
and starts failing the day one of them is fixed.  A few of the most impactful
gaps are additionally marked with `unittest.expectedFailure`.

Run with:
  blender -b --factory-startup --python tests/python/bl_usd_roundtrip_materials_test.py -- \
      --testdir /abs/path/to/tests/files/usd
"""

import math
import os
import pathlib
import sys
import tempfile
import unittest
from pxr import Usd, UsdShade, Sdf

import bpy

sys.path.append(str(pathlib.Path(__file__).parent.absolute()))
from modules.colored_print import (print_message, use_message_colors)


args = None


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


class USDRoundtripMaterialsTest(AbstractUSDTest):
    """Export the material audit scene to USD, import it back and compare."""

    # ------------------------------------------------------------------
    # Scene construction
    # ------------------------------------------------------------------

    def _image(self, name, colorspace):
        img = bpy.data.images.load(str(self.testdir / "textures" / name))
        img.colorspace_settings.name = colorspace
        return img

    @staticmethod
    def _new_material(name):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        return mat, mat.node_tree, mat.node_tree.nodes["Principled BSDF"]

    def _make_library(self):
        """Create a library .blend holding `MatLinked` and return its path."""
        lib_path = self.tempdir / "lib.blend"
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mat, _nt, principled = self._new_material("MatLinked")
        principled.inputs["Base Color"].default_value = (0.2, 0.3, 0.9, 1.0)
        principled.inputs["Roughness"].default_value = 0.77
        mat.use_fake_user = True
        bpy.ops.wm.save_as_mainfile(filepath=str(lib_path))
        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))
        return lib_path

    def build_scene(self):
        lib_path = self._make_library()

        # MatConst: constant non-default values on every Principled input the
        # exporter maps, a few it does not map, and material-level settings.
        mat, _nt, p = self._new_material("MatConst")
        p.inputs["Base Color"].default_value = (0.8, 0.2, 0.1, 1.0)
        p.inputs["Metallic"].default_value = 0.65
        p.inputs["Roughness"].default_value = 0.35
        p.inputs["IOR"].default_value = 1.8
        p.inputs["Alpha"].default_value = 0.6
        p.inputs["Specular IOR Level"].default_value = 0.7
        p.inputs["Specular Tint"].default_value = (0.9, 0.5, 0.2, 1.0)
        p.inputs["Anisotropic"].default_value = 0.4
        p.inputs["Subsurface Weight"].default_value = 0.3
        p.inputs["Sheen Weight"].default_value = 0.5
        p.inputs["Coat Weight"].default_value = 0.4
        p.inputs["Coat Roughness"].default_value = 0.2
        p.inputs["Emission Color"].default_value = (0.1, 0.9, 0.3, 1.0)
        p.inputs["Emission Strength"].default_value = 2.5
        mat.diffuse_color = (0.1, 0.2, 0.3, 1.0)
        mat.metallic = 0.9
        mat.roughness = 0.1
        mat.surface_render_method = 'BLENDED'
        mat.use_transparent_shadow = False
        mat.use_backface_culling = True
        mat.use_backface_culling_shadow = True
        mat.pass_index = 3
        mat.displacement_method = 'DISPLACEMENT'
        mat["artist_note"] = "hello"

        # MatGlass: transmission + IOR, dithered render method.
        mat, _nt, p = self._new_material("MatGlass")
        p.inputs["Base Color"].default_value = (0.9, 0.95, 1.0, 1.0)
        p.inputs["Transmission Weight"].default_value = 0.75
        p.inputs["IOR"].default_value = 1.33
        p.inputs["Roughness"].default_value = 0.05
        mat.surface_render_method = 'DITHERED'
        mat.use_raytrace_refraction = True

        # MatTex: base color texture via UV Map -> Mapping, a normal map, and
        # metallic driven by one channel of a texture through Separate Color.
        mat, nt, p = self._new_material("MatTex")
        p.inputs["Roughness"].default_value = 0.42
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.name = "BaseColorTex"
        tex.image = self._image("test_single.png", "sRGB")
        tex.extension = 'EXTEND'
        tex.interpolation = 'Closest'
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.name = "Mapping"
        mapping.inputs["Location"].default_value = (0.25, 0.5, 0.7)
        mapping.inputs["Rotation"].default_value = (0.1, 0.2, 0.5)
        mapping.inputs["Scale"].default_value = (2.0, 3.0, 4.0)
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.name = "UVMap2Node"
        uv.uv_map = "UVMap2"
        nt.links.new(uv.outputs["UV"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], p.inputs["Base Color"])
        ntex = nt.nodes.new("ShaderNodeTexImage")
        ntex.name = "NormalTex"
        ntex.image = self._image("test_normal.exr", "Non-Color")
        ntex.extension = 'MIRROR'
        ntex.interpolation = 'Cubic'
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.name = "NormalMapNode"
        nmap.space = 'TANGENT'
        nmap.uv_map = "UVMap2"
        nmap.inputs["Strength"].default_value = 0.8
        nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], p.inputs["Normal"])
        mtex = nt.nodes.new("ShaderNodeTexImage")
        mtex.name = "MetalTex"
        mtex.image = self._image("test_grid_1001.png", "Non-Color")
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.name = "SepColor"
        nt.links.new(mtex.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], p.inputs["Metallic"])

        # MatAlphaTex: alpha driven by the image alpha channel.
        mat, nt, p = self._new_material("MatAlphaTex")
        atex = nt.nodes.new("ShaderNodeTexImage")
        atex.name = "AlphaTex"
        atex.image = bpy.data.images["test_single.png"]
        nt.links.new(atex.outputs["Color"], p.inputs["Base Color"])
        nt.links.new(atex.outputs["Alpha"], p.inputs["Alpha"])
        mat.surface_render_method = 'BLENDED'

        # MatDisp: image-driven displacement with non-default Midlevel/Scale.
        mat, nt, p = self._new_material("MatDisp")
        p.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
        dtex = nt.nodes.new("ShaderNodeTexImage")
        dtex.name = "DispTex"
        dtex.image = self._image("test_displace.exr", "Non-Color")
        disp = nt.nodes.new("ShaderNodeDisplacement")
        disp.name = "Displacement"
        disp.space = 'OBJECT'
        disp.inputs["Midlevel"].default_value = 0.3
        disp.inputs["Scale"].default_value = 0.6
        nt.links.new(dtex.outputs["Color"], disp.inputs["Height"])
        nt.links.new(disp.outputs["Displacement"],
                     nt.nodes["Material Output"].inputs["Displacement"])
        mat.displacement_method = 'BOTH'

        # MatProc: procedural Noise -> Roughness (not expressible in UsdPreviewSurface).
        mat, nt, p = self._new_material("MatProc")
        p.inputs["Base Color"].default_value = (0.2, 0.7, 0.2, 1.0)
        p.inputs["Roughness"].default_value = 0.9  # value "under" the link
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.name = "Noise"
        noise.inputs["Scale"].default_value = 12.0
        nt.links.new(noise.outputs["Fac"], p.inputs["Roughness"])

        # MatMix: Mix Shader of a Diffuse BSDF and the Principled BSDF.
        mat, nt, p = self._new_material("MatMix")
        p.inputs["Base Color"].default_value = (1.0, 0.0, 0.0, 1.0)
        diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
        diffuse.name = "Diffuse"
        diffuse.inputs["Color"].default_value = (0.0, 0.0, 1.0, 1.0)
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.name = "MixShader"
        mix.inputs["Fac"].default_value = 0.3
        out = nt.nodes["Material Output"]
        for link in list(nt.links):
            if link.to_node == out:
                nt.links.remove(link)
        nt.links.new(diffuse.outputs["BSDF"], mix.inputs[1])
        nt.links.new(p.outputs["BSDF"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])

        # MatLinked: linked from the library file.
        with bpy.data.libraries.load(str(lib_path), link=True) as (src, dst):
            dst.materials = ["MatLinked"]
        self.assertIsNotNone(bpy.data.materials["MatLinked"].library)

        # MatUnused: not assigned to any object.
        mat, _nt, p = self._new_material("MatUnused")
        p.inputs["Base Color"].default_value = (0.3, 0.3, 0.3, 1.0)

        def cube(name, mat_names, face_mats, location):
            bpy.ops.mesh.primitive_cube_add(location=location)
            ob = bpy.context.active_object
            ob.name = name
            me = ob.data
            me.name = name + "Mesh"
            me.uv_layers.new(name="UVMap2")
            for mat_name in mat_names:
                me.materials.append(bpy.data.materials[mat_name])
            for poly, index in zip(me.polygons, face_mats):
                poly.material_index = index
            return ob

        cube("CubeA", ["MatConst", "MatGlass", "MatTex", "MatDisp"], [0, 0, 1, 2, 2, 3], (0, 0, 0))
        cube("CubeB", ["MatProc", "MatMix", "MatLinked", "MatAlphaTex"], [0, 0, 1, 1, 2, 3], (3, 0, 0))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def export_and_reimport(self, name="materials", export_kwargs=None, import_kwargs=None):
        """Build the scene, export it and import it back into empty.blend.

        Returns the path of the exported USD file.
        """
        self.build_scene()
        usd_path = self.tempdir / name
        res = bpy.ops.wm.usd_export(filepath=str(usd_path), export_materials=True,
                                    **(export_kwargs or {}))
        self.assertEqual({'FINISHED'}, res, f"Unable to export to {usd_path}")

        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))
        res = bpy.ops.wm.usd_import(filepath=str(usd_path), **(import_kwargs or {}))
        self.assertEqual({'FINISHED'}, res, f"Unable to import USD file {usd_path}")
        return usd_path

    @staticmethod
    def principled(mat_name):
        return bpy.data.materials[mat_name].node_tree.nodes["Principled BSDF"]

    @staticmethod
    def nodes_of_type(mat_name, bl_idname):
        return [n for n in bpy.data.materials[mat_name].node_tree.nodes if n.bl_idname == bl_idname]

    @staticmethod
    def link_source(socket):
        """Return (node bl_idname, output socket name) feeding `socket`, or None."""
        if not socket.is_linked:
            return None
        link = socket.links[0]
        return (link.from_node.bl_idname, link.from_socket.name)

    def assertColorEqual(self, actual, expected, places=5):
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, places=places)

    @staticmethod
    def usd_shader(stage, mat_name, shader_name="Principled_BSDF"):
        return UsdShade.Shader(stage.GetPrimAtPath(f"/root/_materials/{mat_name}/{shader_name}"))

    @staticmethod
    def usd_input_value(shader, name):
        inp = shader.GetInput(name)
        if not inp:
            return None
        return inp.Get()

    @staticmethod
    def usd_input_source(shader, name):
        """Return (source prim name, source output name) for a connected input."""
        inp = shader.GetInput(name)
        if not inp or not inp.HasConnectedSource():
            return None
        source, source_name, _type = inp.GetConnectedSource()
        return (source.GetPrim().GetName(), source_name)

    # ------------------------------------------------------------------
    # Default export (UsdPreviewSurface) / default import
    # ------------------------------------------------------------------

    def test_principled_constants(self):
        """Constant Principled BSDF inputs through UsdPreviewSurface."""
        usd_path = self.export_and_reimport("constants.usda")
        stage = Usd.Stage.Open(str(usd_path))
        shader = self.usd_shader(stage, "MatConst")
        self.assertEqual(shader.GetIdAttr().Get(), "UsdPreviewSurface")
        p = self.principled("MatConst")

        # Preserved.
        self.assertColorEqual(self.usd_input_value(shader, "diffuseColor"), (0.8, 0.2, 0.1))
        self.assertColorEqual(p.inputs["Base Color"].default_value, (0.8, 0.2, 0.1, 1.0))
        self.assertAlmostEqual(self.usd_input_value(shader, "metallic"), 0.65)
        self.assertAlmostEqual(p.inputs["Metallic"].default_value, 0.65)
        self.assertAlmostEqual(self.usd_input_value(shader, "roughness"), 0.35)
        self.assertAlmostEqual(p.inputs["Roughness"].default_value, 0.35)
        self.assertAlmostEqual(self.usd_input_value(shader, "ior"), 1.8)
        self.assertAlmostEqual(p.inputs["IOR"].default_value, 1.8)
        self.assertAlmostEqual(self.usd_input_value(shader, "clearcoat"), 0.4)
        self.assertAlmostEqual(p.inputs["Coat Weight"].default_value, 0.4)
        self.assertAlmostEqual(self.usd_input_value(shader, "clearcoatRoughness"), 0.2)
        self.assertAlmostEqual(p.inputs["Coat Roughness"].default_value, 0.2)

        # KNOWN GAP (import): `Specular IOR Level` is written as `inputs:specular`
        # but the importer never reads `specular`, so the value falls back to 0.5.
        self.assertAlmostEqual(self.usd_input_value(shader, "specular"), 0.7)
        self.assertAlmostEqual(p.inputs["Specular IOR Level"].default_value, 0.5)

        # KNOWN GAP (export, collapsed): emission is written as a single
        # `emissiveColor = color * strength`; the importer restores that color
        # with `Emission Strength = 1.0`, so the two separate values are gone.
        self.assertColorEqual(self.usd_input_value(shader, "emissiveColor"), (0.25, 2.25, 0.75))
        self.assertColorEqual(p.inputs["Emission Color"].default_value, (0.25, 2.25, 0.75, 1.0))
        self.assertAlmostEqual(p.inputs["Emission Strength"].default_value, 1.0)

        # KNOWN GAP (export): a *constant* Alpha is not written.  `Alpha` and
        # `Transmission Weight` both map to `inputs:opacity`; the transmission
        # pass runs last and overwrites opacity with `1 - transmission` (= 1).
        self.assertAlmostEqual(self.usd_input_value(shader, "opacity"), 1.0)
        self.assertAlmostEqual(p.inputs["Alpha"].default_value, 1.0)

        # KNOWN GAP (export): UsdPreviewSurface has no equivalent for these.
        for usd_name in ("specularColor", "anisotropic", "subsurface", "sheen"):
            self.assertFalse(shader.GetInput(usd_name), f"{usd_name} unexpectedly written")
        self.assertColorEqual(p.inputs["Specular Tint"].default_value, (1.0, 1.0, 1.0, 1.0))
        self.assertAlmostEqual(p.inputs["Anisotropic"].default_value, 0.0)
        self.assertAlmostEqual(p.inputs["Subsurface Weight"].default_value, 0.0)
        self.assertAlmostEqual(p.inputs["Sheen Weight"].default_value, 0.0)

    @unittest.expectedFailure
    def test_constant_alpha_roundtrip(self):
        """KNOWN GAP: a constant Principled `Alpha` does not survive export."""
        self.export_and_reimport("alpha.usda")
        self.assertAlmostEqual(self.principled("MatConst").inputs["Alpha"].default_value, 0.6)

    @unittest.expectedFailure
    def test_specular_ior_level_roundtrip(self):
        """KNOWN GAP: `Specular IOR Level` is exported as `specular` but not imported."""
        self.export_and_reimport("specular.usda")
        self.assertAlmostEqual(self.principled("MatConst").inputs["Specular IOR Level"].default_value, 0.7)

    @unittest.expectedFailure
    def test_emission_strength_roundtrip(self):
        """KNOWN GAP: `Emission Strength` is folded into `emissiveColor` on export."""
        self.export_and_reimport("emission.usda")
        p = self.principled("MatConst")
        self.assertAlmostEqual(p.inputs["Emission Strength"].default_value, 2.5)
        self.assertColorEqual(p.inputs["Emission Color"].default_value, (0.1, 0.9, 0.3, 1.0))

    def test_transmission(self):
        """Transmission Weight is carried through `opacity` (inverted)."""
        usd_path = self.export_and_reimport("transmission.usda")
        stage = Usd.Stage.Open(str(usd_path))
        shader = self.usd_shader(stage, "MatGlass")
        self.assertAlmostEqual(self.usd_input_value(shader, "opacity"), 0.25)
        self.assertAlmostEqual(self.usd_input_value(shader, "ior"), 1.33)

        mat = bpy.data.materials["MatGlass"]
        p = mat.node_tree.nodes["Principled BSDF"]
        self.assertAlmostEqual(p.inputs["Transmission Weight"].default_value, 0.75)
        self.assertAlmostEqual(p.inputs["IOR"].default_value, 1.33)
        self.assertAlmostEqual(p.inputs["Roughness"].default_value, 0.05)
        self.assertColorEqual(p.inputs["Base Color"].default_value, (0.9, 0.95, 1.0, 1.0))

        # KNOWN GAP (import, altered): opacity < 1 makes the importer switch the
        # render method to BLENDED, even though the original was DITHERED.
        self.assertEqual(mat.surface_render_method, 'BLENDED')
        # KNOWN GAP (export): EEVEE refraction setting is not written.
        self.assertFalse(mat.use_raytrace_refraction)

    def test_material_settings(self):
        """Material-level (non node) settings."""
        usd_path = self.export_and_reimport("settings.usda")
        stage = Usd.Stage.Open(str(usd_path))
        mat_prim = stage.GetPrimAtPath("/root/_materials/MatConst")

        mat = bpy.data.materials["MatConst"]

        # Preserved: material name and ID custom properties (userProperties:*).
        self.assertTrue(mat_prim.IsValid())
        self.assertEqual(mat_prim.GetAttribute("userProperties:artist_note").Get(), "hello")
        self.assertEqual(mat["artist_note"], "hello")

        # KNOWN GAP (export): none of the EEVEE/viewport material settings are
        # written; the importer recomputes the viewport colors from the
        # Principled inputs and resets everything else to defaults.
        for attr in mat_prim.GetAttributes():
            self.assertFalse(attr.GetName().startswith("userProperties:blender:") and
                             attr.GetName() not in {"userProperties:blender:data_name"},
                             f"unexpected material setting written: {attr.GetName()}")
        self.assertEqual(mat.surface_render_method, 'DITHERED')   # was BLENDED
        self.assertTrue(mat.use_transparent_shadow)                # was False
        self.assertFalse(mat.use_backface_culling)                 # was True
        self.assertFalse(mat.use_backface_culling_shadow)          # was True
        self.assertEqual(mat.pass_index, 0)                        # was 3
        self.assertEqual(mat.displacement_method, 'BUMP')          # was DISPLACEMENT
        # Viewport display color/metallic/roughness are replaced by the
        # Principled values (0.8,0.2,0.1)/0.65/0.35 instead of (0.1,0.2,0.3)/0.9/0.1.
        self.assertColorEqual(mat.diffuse_color, (0.8, 0.2, 0.1, 1.0))
        self.assertAlmostEqual(mat.metallic, 0.65)
        self.assertAlmostEqual(mat.roughness, 0.35)

    def test_textures_mapping_and_normal_map(self):
        """Image textures, UV Map / Mapping nodes and the Normal Map node."""
        usd_path = self.export_and_reimport("textures.usda")
        stage = Usd.Stage.Open(str(usd_path))
        shader = self.usd_shader(stage, "MatTex")

        # UsdShade network written.
        self.assertEqual(self.usd_input_source(shader, "diffuseColor"), ("BaseColorTex", "rgb"))
        self.assertEqual(self.usd_input_source(shader, "metallic"), ("MetalTex", "g"))
        self.assertEqual(self.usd_input_source(shader, "normal"), ("NormalTex", "rgb"))
        base_tex = self.usd_shader(stage, "MatTex", "BaseColorTex")
        self.assertEqual(base_tex.GetIdAttr().Get(), "UsdUVTexture")
        self.assertEqual(self.usd_input_value(base_tex, "wrapS"), "clamp")
        self.assertEqual(self.usd_input_value(base_tex, "wrapT"), "clamp")
        self.assertEqual(self.usd_input_value(base_tex, "sourceColorSpace"), "sRGB")
        self.assertEqual(self.usd_input_source(base_tex, "st"), ("Mapping", "result"))
        normal_tex = self.usd_shader(stage, "MatTex", "NormalTex")
        self.assertEqual(self.usd_input_value(normal_tex, "wrapS"), "mirror")
        self.assertEqual(self.usd_input_value(normal_tex, "sourceColorSpace"), "raw")
        self.assertColorEqual(self.usd_input_value(normal_tex, "scale"), (2, 2, 2, 2))
        self.assertColorEqual(self.usd_input_value(normal_tex, "bias"), (-1, -1, -1, -1))
        transform = self.usd_shader(stage, "MatTex", "Mapping")
        self.assertEqual(transform.GetIdAttr().Get(), "UsdTransform2d")
        self.assertColorEqual(self.usd_input_value(transform, "scale"), (2.0, 3.0))
        self.assertColorEqual(self.usd_input_value(transform, "translation"), (0.25, 0.5))
        self.assertAlmostEqual(self.usd_input_value(transform, "rotation"), math.degrees(0.5), places=4)
        self.assertEqual(self.usd_input_source(transform, "in"), ("UVMap2Node", "result"))
        uv_reader = self.usd_shader(stage, "MatTex", "UVMap2Node")
        self.assertEqual(uv_reader.GetIdAttr().Get(), "UsdPrimvarReader_float2")
        self.assertEqual(self.usd_input_value(uv_reader, "varname"), "UVMap2")
        # KNOWN GAP (export): there is no UsdUVTexture equivalent for
        # interpolation, Normal Map strength, Mapping Z scale/translation or
        # X/Y rotation, so none of them are written.
        self.assertFalse(base_tex.GetInput("interpolation"))
        self.assertFalse(normal_tex.GetInput("strength"))

        # Imported node tree.
        p = self.principled("MatTex")
        self.assertAlmostEqual(p.inputs["Roughness"].default_value, 0.42)
        self.assertEqual(self.link_source(p.inputs["Base Color"]), ("ShaderNodeTexImage", "Color"))
        self.assertEqual(self.link_source(p.inputs["Metallic"]), ("ShaderNodeSeparateColor", "Green"))
        self.assertEqual(self.link_source(p.inputs["Normal"]), ("ShaderNodeNormalMap", "Normal"))

        base_node = p.inputs["Base Color"].links[0].from_node
        self.assertEqual(base_node.image.name, "test_single.png")
        self.assertEqual(base_node.image.colorspace_settings.name, "sRGB")
        self.assertEqual(base_node.extension, 'EXTEND')
        # KNOWN GAP (export): interpolation reverts to Linear (was Closest).
        self.assertEqual(base_node.interpolation, 'Linear')
        # KNOWN GAP (import): node names are not restored from the prim names.
        self.assertEqual(base_node.name, "Image Texture")

        mapping_node = base_node.inputs["Vector"].links[0].from_node
        self.assertEqual(mapping_node.bl_idname, "ShaderNodeMapping")
        scale = mapping_node.inputs["Scale"].default_value
        loc = mapping_node.inputs["Location"].default_value
        rot = mapping_node.inputs["Rotation"].default_value
        self.assertColorEqual(scale[:2], (2.0, 3.0))
        self.assertColorEqual(loc[:2], (0.25, 0.5))
        self.assertAlmostEqual(rot[2], 0.5, places=5)
        # KNOWN GAP (export): Z scale/translation and X/Y rotation are dropped.
        self.assertAlmostEqual(scale[2], 1.0)   # was 4.0
        self.assertAlmostEqual(loc[2], 0.0)     # was 0.7
        self.assertAlmostEqual(rot[0], 0.0)     # was 0.1
        self.assertAlmostEqual(rot[1], 0.0)     # was 0.2

        uv_node = mapping_node.inputs["Vector"].links[0].from_node
        self.assertEqual(uv_node.bl_idname, "ShaderNodeUVMap")
        self.assertEqual(uv_node.uv_map, "UVMap2")

        normal_map = p.inputs["Normal"].links[0].from_node
        self.assertEqual(normal_map.space, 'TANGENT')
        normal_tex_node = normal_map.inputs["Color"].links[0].from_node
        self.assertEqual(normal_tex_node.image.name, "test_normal.exr")
        self.assertEqual(normal_tex_node.image.colorspace_settings.name, "Non-Color")
        self.assertEqual(normal_tex_node.extension, 'MIRROR')
        # KNOWN GAP (export): Normal Map strength (0.8) and its UV map ("UVMap2")
        # are not written.
        self.assertAlmostEqual(normal_map.inputs["Strength"].default_value, 1.0)
        self.assertEqual(normal_map.uv_map, "")
        self.assertEqual(normal_tex_node.interpolation, 'Linear')  # was Cubic

        # Textures whose Vector input was unlinked read the active UV map, which
        # is written as the `st` primvar and comes back with that name.
        metal_tex_node = p.inputs["Metallic"].links[0].from_node.inputs["Color"].links[0].from_node
        self.assertEqual(metal_tex_node.image.name, "test_grid_1001.png")
        self.assertEqual(metal_tex_node.inputs["Vector"].links[0].from_node.uv_map, "st")
        self.assertEqual([uv.name for uv in bpy.data.objects["CubeAMesh"].data.uv_layers], ["st", "UVMap2"])

    @unittest.expectedFailure
    def test_texture_interpolation_roundtrip(self):
        """KNOWN GAP: Image Texture interpolation is not written to UsdUVTexture."""
        self.export_and_reimport("interp.usda")
        base_node = self.principled("MatTex").inputs["Base Color"].links[0].from_node
        self.assertEqual(base_node.interpolation, 'Closest')

    @unittest.expectedFailure
    def test_normal_map_strength_roundtrip(self):
        """KNOWN GAP: Normal Map strength is not written to UsdPreviewSurface."""
        self.export_and_reimport("nmstrength.usda")
        normal_map = self.principled("MatTex").inputs["Normal"].links[0].from_node
        self.assertAlmostEqual(normal_map.inputs["Strength"].default_value, 0.8)

    def test_textured_alpha(self):
        """Alpha driven by a texture channel survives (unlike a constant Alpha)."""
        usd_path = self.export_and_reimport("alpha_tex.usda")
        stage = Usd.Stage.Open(str(usd_path))
        shader = self.usd_shader(stage, "MatAlphaTex")
        self.assertEqual(self.usd_input_source(shader, "opacity"), ("AlphaTex", "a"))

        mat = bpy.data.materials["MatAlphaTex"]
        p = mat.node_tree.nodes["Principled BSDF"]
        self.assertEqual(self.link_source(p.inputs["Alpha"]), ("ShaderNodeTexImage", "Alpha"))
        self.assertEqual(self.link_source(p.inputs["Base Color"]), ("ShaderNodeTexImage", "Color"))
        self.assertEqual(mat.surface_render_method, 'BLENDED')

    def test_displacement(self):
        """Displacement node with non-default Midlevel/Scale in object space."""
        usd_path = self.export_and_reimport("displacement.usda")
        stage = Usd.Stage.Open(str(usd_path))
        mat_prim = stage.GetPrimAtPath("/root/_materials/MatDisp")
        self.assertTrue(mat_prim.GetAttribute("outputs:displacement").HasAuthoredConnections())
        shader = self.usd_shader(stage, "MatDisp")
        self.assertEqual(self.usd_input_source(shader, "displacement"), ("DispTex", "r"))
        disp_tex = self.usd_shader(stage, "MatDisp", "DispTex")
        # Midlevel/Scale are encoded as texture scale/bias: scale, -midlevel*scale.
        self.assertColorEqual(self.usd_input_value(disp_tex, "scale"), (0.6, 0.6, 0.6, 1.0))
        self.assertColorEqual(self.usd_input_value(disp_tex, "bias"), (-0.18, -0.18, -0.18, 0.0))

        mat = bpy.data.materials["MatDisp"]
        output = mat.node_tree.nodes["Material Output"]
        disp_node = output.inputs["Displacement"].links[0].from_node
        self.assertEqual(disp_node.bl_idname, "ShaderNodeDisplacement")
        self.assertEqual(disp_node.space, 'OBJECT')
        self.assertAlmostEqual(disp_node.inputs["Midlevel"].default_value, 0.3)
        self.assertAlmostEqual(disp_node.inputs["Scale"].default_value, 0.6)
        self.assertEqual(mat.displacement_method, 'BOTH')
        # Altered topology: the importer inserts a Separate Color node and
        # feeds the red channel to Height (the original linked Color directly).
        self.assertEqual(self.link_source(disp_node.inputs["Height"]), ("ShaderNodeSeparateColor", "Red"))
        tex_node = disp_node.inputs["Height"].links[0].from_node.inputs["Color"].links[0].from_node
        self.assertEqual(tex_node.image.name, "test_displace.exr")

    def test_inexpressible_networks(self):
        """Networks UsdPreviewSurface cannot express are flattened to constants."""
        usd_path = self.export_and_reimport("inexpressible.usda")
        stage = Usd.Stage.Open(str(usd_path))

        # Noise -> Roughness: KNOWN GAP (export).  The Noise node is dropped and
        # the socket's unlinked default value (0.9) is written instead.
        shader = self.usd_shader(stage, "MatProc")
        self.assertIsNone(self.usd_input_source(shader, "roughness"))
        self.assertAlmostEqual(self.usd_input_value(shader, "roughness"), 0.9)
        self.assertEqual(len(stage.GetPrimAtPath("/root/_materials/MatProc").GetChildren()), 1)
        mat = bpy.data.materials["MatProc"]
        self.assertEqual(sorted(n.bl_idname for n in mat.node_tree.nodes),
                         ["ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"])
        self.assertFalse(mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].is_linked)
        self.assertAlmostEqual(mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value, 0.9)

        # Mix Shader(Diffuse, Principled): KNOWN GAP (export).  Only the first
        # Principled BSDF found is exported; the Diffuse BSDF and the mix are dropped.
        shader = self.usd_shader(stage, "MatMix")
        self.assertColorEqual(self.usd_input_value(shader, "diffuseColor"), (1.0, 0.0, 0.0))
        self.assertEqual(len(stage.GetPrimAtPath("/root/_materials/MatMix").GetChildren()), 1)
        mat = bpy.data.materials["MatMix"]
        self.assertEqual(sorted(n.bl_idname for n in mat.node_tree.nodes),
                         ["ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"])
        self.assertColorEqual(mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value,
                              (1.0, 0.0, 0.0, 1.0))

    def test_names_linking_slots_and_face_assignment(self):
        """Material names, library linking, slots and per-face assignment."""
        usd_path = self.export_and_reimport("slots.usda")
        stage = Usd.Stage.Open(str(usd_path))

        # Preserved: material names (as prim names + userProperties:blender:data_name).
        for name in ("MatConst", "MatGlass", "MatTex", "MatDisp", "MatProc", "MatMix", "MatLinked"):
            prim = stage.GetPrimAtPath(f"/root/_materials/{name}")
            self.assertTrue(prim.IsValid(), name)
            self.assertEqual(prim.GetAttribute("userProperties:blender:data_name").Get(), name)
            self.assertIn(name, bpy.data.materials)

        # KNOWN GAP (export): materials not bound to any exported object are dropped.
        self.assertFalse(stage.GetPrimAtPath("/root/_materials/MatUnused").IsValid())
        self.assertNotIn("MatUnused", bpy.data.materials)

        # KNOWN GAP (export): library linking is flattened; the material comes back local.
        linked = bpy.data.materials["MatLinked"]
        self.assertIsNone(linked.library)
        self.assertColorEqual(linked.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value,
                              (0.2, 0.3, 0.9, 1.0))
        self.assertAlmostEqual(linked.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value, 0.77)

        # Preserved: multiple slots and face assignment via GeomSubsets.
        mesh_prim = stage.GetPrimAtPath("/root/CubeA/CubeAMesh")
        subsets = {c.GetName(): list(c.GetAttribute("indices").Get()) for c in mesh_prim.GetChildren()}
        self.assertEqual(subsets, {"MatConst": [0, 1], "MatGlass": [2], "MatTex": [3, 4], "MatDisp": [5]})

        cube_a = bpy.data.objects["CubeAMesh"]
        self.assertEqual([s.material.name for s in cube_a.material_slots],
                         ["MatConst", "MatGlass", "MatTex", "MatDisp"])
        self.assertEqual([p.material_index for p in cube_a.data.polygons], [0, 0, 1, 2, 2, 3])
        cube_b = bpy.data.objects["CubeBMesh"]
        self.assertEqual([s.material.name for s in cube_b.material_slots],
                         ["MatProc", "MatMix", "MatLinked", "MatAlphaTex"])
        self.assertEqual([p.material_index for p in cube_b.data.polygons], [0, 0, 1, 1, 2, 3])

    # ------------------------------------------------------------------
    # Non-default operator options
    # ------------------------------------------------------------------

    def test_materialx_export(self):
        """`generate_materialx_network` writes an OpenPBR network that carries
        more data than UsdPreviewSurface, but the importer does not read it."""
        usd_path = self.export_and_reimport(
            "materialx.usda",
            export_kwargs={"generate_materialx_network": True, "generate_preview_surface": False})
        stage = Usd.Stage.Open(str(usd_path))

        mat_prim = stage.GetPrimAtPath("/root/_materials/MatConst")
        self.assertTrue(mat_prim.GetAttribute("outputs:mtlx:surface").HasAuthoredConnections())
        # With the preview surface disabled the exporter still writes a
        # minimal UsdPreviewSurface "previewShader" built from the material's
        # *viewport display* settings, not from the node tree.
        preview = self.usd_shader(stage, "MatConst", "previewShader")
        self.assertEqual(preview.GetIdAttr().Get(), "UsdPreviewSurface")
        self.assertColorEqual(self.usd_input_value(preview, "diffuseColor"), (0.1, 0.2, 0.3))
        self.assertAlmostEqual(self.usd_input_value(preview, "metallic"), 0.9)
        self.assertAlmostEqual(self.usd_input_value(preview, "roughness"), 0.1)
        self.assertFalse(preview.GetInput("ior"))
        shader = self.usd_shader(stage, "MatConst", "bnode__Principled_BSDF")
        self.assertEqual(shader.GetIdAttr().Get(), "ND_open_pbr_surface_surfaceshader")
        # MaterialX keeps what UsdPreviewSurface lost...
        self.assertAlmostEqual(self.usd_input_value(shader, "geometry_opacity"), 0.6)
        self.assertAlmostEqual(self.usd_input_value(shader, "emission_luminance"), 2.5)
        self.assertColorEqual(self.usd_input_value(shader, "emission_color"), (0.1, 0.9, 0.3))
        self.assertColorEqual(self.usd_input_value(shader, "specular_color"), (0.9, 0.5, 0.2))
        self.assertAlmostEqual(self.usd_input_value(shader, "subsurface_weight"), 0.3)
        self.assertAlmostEqual(self.usd_input_value(shader, "fuzz_weight"), 0.5)
        proc_shader = self.usd_shader(stage, "MatProc", "bnode__Principled_BSDF")
        self.assertIsNotNone(self.usd_input_source(proc_shader, "specular_roughness"))
        tex_layer = stage.GetRootLayer().ExportToString()
        self.assertIn('string inputs:filtertype = "closest"', tex_layer)
        self.assertIn('string inputs:geomprop = "UVMap2"', tex_layer)
        self.assertIn('uniform token info:id = "ND_normalmap_float"', tex_layer)

        # ...but KNOWN GAP (import): the importer only reads UsdPreviewSurface.
        # It picks up the viewport-display "previewShader" above, so the
        # Principled BSDF comes back with the *viewport* color/metallic/roughness
        # and every other input at its default.
        p = self.principled("MatConst")
        self.assertColorEqual(p.inputs["Base Color"].default_value, (0.1, 0.2, 0.3, 1.0))
        self.assertAlmostEqual(p.inputs["Metallic"].default_value, 0.9)
        self.assertAlmostEqual(p.inputs["Roughness"].default_value, 0.1)
        self.assertAlmostEqual(p.inputs["IOR"].default_value, 1.5)          # was 1.8
        self.assertAlmostEqual(p.inputs["Emission Strength"].default_value, 0.0)
        self.assertEqual(sorted(n.bl_idname for n in bpy.data.materials["MatTex"].node_tree.nodes),
                         ["ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"])

    @unittest.expectedFailure
    def test_materialx_import_roundtrip(self):
        """KNOWN GAP: a MaterialX-only USD file is not read back into the node tree."""
        self.export_and_reimport(
            "materialx_rt.usda",
            export_kwargs={"generate_materialx_network": True, "generate_preview_surface": False})
        self.assertAlmostEqual(self.principled("MatConst").inputs["Metallic"].default_value, 0.65)

    def test_texture_export_modes(self):
        """`export_textures_mode` and texture import modes only change file paths."""
        textures_dir = (self.testdir / "textures").resolve()

        # NEW (default): textures are copied to ./textures next to the USD file.
        usd_path = self.export_and_reimport("tex_new.usda")
        stage = Usd.Stage.Open(str(usd_path))
        tex = self.usd_shader(stage, "MatTex", "BaseColorTex")
        self.assertEqual(self.usd_input_value(tex, "file").path, "./textures/test_single.png")
        self.assertTrue((self.tempdir / "textures" / "test_single.png").exists())
        img = self.principled("MatTex").inputs["Base Color"].links[0].from_node.image
        self.assertEqual(pathlib.Path(img.filepath).resolve(), (self.tempdir / "textures" / "test_single.png").resolve())
        self.assertIsNone(img.packed_file)

        # KEEP: the original file path is written (relative to the USD file).
        usd_path = self.export_and_reimport("tex_keep.usda", export_kwargs={"export_textures_mode": 'KEEP'})
        stage = Usd.Stage.Open(str(usd_path))
        tex = self.usd_shader(stage, "MatTex", "BaseColorTex")
        self.assertEqual(pathlib.Path(self.usd_input_value(tex, "file").resolvedPath).resolve(),
                         textures_dir / "test_single.png")
        img = self.principled("MatTex").inputs["Base Color"].links[0].from_node.image
        self.assertEqual(pathlib.Path(img.filepath).resolve(), textures_dir / "test_single.png")

        # USDZ + IMPORT_PACK: textures come back packed into the .blend.
        usd_path = self.export_and_reimport("tex_pack.usdz", import_kwargs={"import_textures_mode": 'IMPORT_PACK'})
        img = self.principled("MatTex").inputs["Base Color"].links[0].from_node.image
        self.assertIsNotNone(img.packed_file)

    def test_import_options(self):
        """`set_material_blend` and `import_usd_preview` import options."""
        self.export_and_reimport("no_blend.usda", import_kwargs={"set_material_blend": False})
        self.assertEqual(bpy.data.materials["MatGlass"].surface_render_method, 'DITHERED')
        self.assertAlmostEqual(self.principled("MatGlass").inputs["Transmission Weight"].default_value, 0.75)

        self.export_and_reimport("no_preview.usda", import_kwargs={"import_usd_preview": False})
        mat = bpy.data.materials["MatConst"]
        self.assertEqual(len(mat.node_tree.nodes), 0)
        # The material is still created and bound, but it is empty.
        self.assertEqual([s.material.name for s in bpy.data.objects["CubeAMesh"].material_slots],
                         ["MatConst", "MatGlass", "MatTex", "MatDisp"])


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
