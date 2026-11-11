# SPDX-FileCopyrightText: 2025 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
USD round-trip audit for lights: export a scene of Blender lights to USD, import it
back into an empty file and compare the key light properties.

Properties that currently survive the trip are asserted directly. Properties that are
known to be lost or altered are covered by tests decorated with `unittest.expectedFailure`
(naming the lost property), or asserted with their current lossy value and a comment, so
this file both documents the known gaps and goes red when behavior changes.
"""

import math
import os
import pathlib
import sys
import tempfile
import unittest
from pxr import Usd, UsdLux

import bpy

sys.path.append(str(pathlib.Path(__file__).parent.absolute()))
from modules.colored_print import (print_message, use_message_colors)


args = None

# Non-default values shared by every light in the test scene.
COMMON = dict(
    specular_factor=0.4,
    diffuse_factor=0.7,
    volume_factor=0.3,
    transmission_factor=0.6,
    use_shadow=False,
    exposure=1.5,
    normalize=False,
    use_temperature=True,
    temperature=4500.0,
)


class AbstractUSDTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.testdir = args.testdir
        if os.environ.get("BLENDER_TEST_COLOR") is not None:
            use_message_colors()

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.tempdir = pathlib.Path(self._tempdir.name)

        self.assertTrue(self.testdir.exists(), 'Test dir {0} should exist'.format(self.testdir))
        self.assertTrue(self.tempdir.exists(), 'Temp dir {0} should exist'.format(self.tempdir))

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


class USDLightRoundTripTest(AbstractUSDTest):

    @staticmethod
    def add_light(name, light_type, **props):
        light = bpy.data.lights.new(name, light_type)
        ob = bpy.data.objects.new(name, light)
        bpy.context.scene.collection.objects.link(ob)
        for key, value in props.items():
            setattr(light, key, value)
        return ob, light

    def build_scene(self):
        """Create one light of every Blender type/shape with non-default values everywhere."""
        scene = bpy.context.scene
        scene.frame_start = 1
        scene.frame_end = 10
        scene.frame_set(1)

        ob, light = self.add_light("Point", 'POINT', color=(0.9, 0.2, 0.1), energy=123.0,
                                   shadow_soft_size=0.37, use_soft_falloff=False,
                                   use_custom_distance=True, cutoff_distance=12.5,
                                   shadow_filter_radius=2.5, shadow_jitter_overblur=25.0,
                                   use_shadow_jitter=True, shadow_maximum_resolution=0.01,
                                   use_absolute_resolution=True, **COMMON)
        light["light_custom_int"] = 7
        ob["object_custom_float"] = 2.5
        ob.location = (1.0, 2.0, 3.0)

        self.add_light("Sun", 'SUN', color=(0.2, 0.9, 0.3), energy=3.3, angle=math.radians(5.0),
                       shadow_cascade_count=3, **COMMON)

        self.add_light("Spot", 'SPOT', color=(0.3, 0.4, 0.9), energy=77.0, shadow_soft_size=0.11,
                       spot_size=math.radians(50.0), spot_blend=0.35, show_cone=True, use_square=True, **COMMON)

        self.add_light("Spot_point", 'SPOT', energy=55.0, shadow_soft_size=0.0,
                       spot_size=math.radians(50.0), spot_blend=0.35)

        self.add_light("Area_square", 'AREA', shape='SQUARE', size=1.7, energy=44.0,
                       spread=math.radians(100.0), **COMMON)
        self.add_light("Area_rect", 'AREA', shape='RECTANGLE', size=0.8, size_y=2.3, energy=45.0,
                       spread=math.radians(100.0), **COMMON)
        self.add_light("Area_disk", 'AREA', shape='DISK', size=1.9, energy=46.0,
                       spread=math.radians(100.0), **COMMON)
        self.add_light("Area_ellipse", 'AREA', shape='ELLIPSE', size=1.2, size_y=2.6, energy=47.0,
                       spread=math.radians(100.0), **COMMON)

        # Energy keyframed over a few frames.
        ob, light = self.add_light("Point_anim", 'POINT', shadow_soft_size=0.2)
        for frame, energy in ((1, 10.0), (5, 50.0), (10, 100.0)):
            light.energy = energy
            light.keyframe_insert("energy", frame=frame)
        scene.frame_set(1)

        # Light linking on the Point light: a receiver and a blocker collection.
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, -2))
        cube = bpy.context.active_object
        receivers = bpy.data.collections.new("Light Receivers")
        receivers.objects.link(cube)
        blockers = bpy.data.collections.new("Light Blockers")
        blockers.objects.link(cube)
        point = bpy.data.objects["Point"]
        point.light_linking.receiver_collection = receivers
        point.light_linking.blocker_collection = blockers

    def round_trip(self, export_kwargs=None, import_kwargs=None, name="lights_roundtrip.usda"):
        """Build the scene, export it, reopen the empty file and import the result."""
        self.build_scene()

        usd_path = self.tempdir / name
        res = bpy.ops.wm.usd_export(filepath=str(usd_path), **(export_kwargs or {}))
        self.assertEqual({'FINISHED'}, res, f"Unable to export to {usd_path}")

        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))
        res = bpy.ops.wm.usd_import(filepath=str(usd_path), **(import_kwargs or {}))
        self.assertEqual({'FINISHED'}, res, f"Unable to import USD file {usd_path}")

        return usd_path

    # ---------------------------------------------------------------------------------------
    # Properties that survive the round trip.

    def test_light_types_round_trip(self):
        """Every Blender light type comes back as the same type (shapes see test below)."""
        self.round_trip()

        lights = [o for o in bpy.data.objects if o.type == 'LIGHT']
        self.assertEqual(9, len(lights), f"Expected 9 lights after import; found {len(lights)}")

        self.assertEqual(bpy.data.lights["Point"].type, 'POINT')
        self.assertEqual(bpy.data.lights["Point_anim"].type, 'POINT')
        self.assertEqual(bpy.data.lights["Sun"].type, 'SUN')
        self.assertEqual(bpy.data.lights["Spot"].type, 'SPOT')
        # A spot with radius 0 is written with treatAsPoint=1 but must still come back as a spot.
        self.assertEqual(bpy.data.lights["Spot_point"].type, 'SPOT')
        for name in ("Area_square", "Area_rect", "Area_disk", "Area_ellipse"):
            self.assertEqual(bpy.data.lights[name].type, 'AREA', name)

    def test_usd_light_schemas_written(self):
        """Check which UsdLux schema and attributes the exporter writes for each light."""
        usd_path = self.round_trip()
        stage = Usd.Stage.Open(str(usd_path))

        def prim(name):
            p = stage.GetPrimAtPath(f"/root/{name}/{name}")
            self.assertTrue(p.IsValid(), f"Missing light prim for {name}")
            return p

        self.assertTrue(prim("Point").IsA(UsdLux.SphereLight))
        self.assertTrue(prim("Spot").IsA(UsdLux.SphereLight))
        self.assertTrue(prim("Spot").HasAPI(UsdLux.ShapingAPI))
        self.assertTrue(prim("Sun").IsA(UsdLux.DistantLight))
        self.assertTrue(prim("Area_square").IsA(UsdLux.RectLight))
        self.assertTrue(prim("Area_rect").IsA(UsdLux.RectLight))
        self.assertTrue(prim("Area_disk").IsA(UsdLux.DiskLight))
        self.assertTrue(prim("Area_ellipse").IsA(UsdLux.DiskLight))

        # Blender watts are converted to USD intensity: energy / pi (energy / 4 for sun lights).
        point = UsdLux.LightAPI(prim("Point"))
        self.assertAlmostEqual(point.GetIntensityAttr().Get(), 123.0 / math.pi, 4)
        self.assertAlmostEqual(point.GetExposureAttr().Get(), 1.5, 5)
        self.assertEqual(point.GetColorAttr().Get(), (0.9, 0.2, 0.1))
        self.assertAlmostEqual(point.GetDiffuseAttr().Get(), 0.7, 5)
        self.assertAlmostEqual(point.GetSpecularAttr().Get(), 0.4, 5)
        self.assertEqual(point.GetEnableColorTemperatureAttr().Get(), True)
        self.assertAlmostEqual(point.GetColorTemperatureAttr().Get(), 4500.0, 3)
        self.assertAlmostEqual(UsdLux.SphereLight(prim("Point")).GetRadiusAttr().Get(), 0.37, 5)
        self.assertEqual(prim("Point").GetAttribute("userProperties:light_custom_int").Get(), 7)
        self.assertEqual(
            stage.GetPrimAtPath("/root/Point").GetAttribute("userProperties:object_custom_float").Get(), 2.5)

        sun = UsdLux.LightAPI(prim("Sun"))
        self.assertAlmostEqual(sun.GetIntensityAttr().Get(), 3.3 / 4.0, 5)
        # Blender's full sun angle is written as the USD half angle, in degrees.
        self.assertAlmostEqual(UsdLux.DistantLight(prim("Sun")).GetAngleAttr().Get(), 2.5, 5)

        shaping = UsdLux.ShapingAPI(prim("Spot"))
        self.assertAlmostEqual(shaping.GetShapingConeAngleAttr().Get(), 25.0, 5)
        self.assertAlmostEqual(shaping.GetShapingConeSoftnessAttr().Get(), 0.35, 5)

        rect = UsdLux.RectLight(prim("Area_rect"))
        self.assertAlmostEqual(rect.GetWidthAttr().Get(), 0.8, 5)
        self.assertAlmostEqual(rect.GetHeightAttr().Get(), 2.3, 5)
        self.assertAlmostEqual(UsdLux.DiskLight(prim("Area_disk")).GetRadiusAttr().Get(), 1.9 / 2.0, 5)

    def test_common_properties_preserved(self):
        """Color, energy, exposure, normalize, temperature, diffuse/specular factors and custom props."""
        self.round_trip()

        for name in ("Point", "Sun", "Spot", "Area_square", "Area_rect", "Area_disk", "Area_ellipse"):
            light = bpy.data.lights[name]
            self.assertAlmostEqual(light.exposure, 1.5, 5, name)
            self.assertEqual(light.normalize, False, name)
            self.assertEqual(light.use_temperature, True, name)
            self.assertAlmostEqual(light.temperature, 4500.0, 3, name)
            self.assertAlmostEqual(light.diffuse_factor, 0.7, 5, name)
            self.assertAlmostEqual(light.specular_factor, 0.4, 5, name)

        # Energy survives numerically (watts -> intensity -> watts).
        self.assertAlmostEqual(bpy.data.lights["Point"].energy, 123.0, 4)
        self.assertAlmostEqual(bpy.data.lights["Sun"].energy, 3.3, 4)
        self.assertAlmostEqual(bpy.data.lights["Spot"].energy, 77.0, 4)
        self.assertAlmostEqual(bpy.data.lights["Spot_point"].energy, 55.0, 4)
        self.assertAlmostEqual(bpy.data.lights["Area_square"].energy, 44.0, 4)
        self.assertAlmostEqual(bpy.data.lights["Area_rect"].energy, 45.0, 4)
        self.assertAlmostEqual(bpy.data.lights["Area_disk"].energy, 46.0, 4)
        self.assertAlmostEqual(bpy.data.lights["Area_ellipse"].energy, 47.0, 4)

        point = bpy.data.lights["Point"]
        self.assertEqual(tuple(round(c, 5) for c in point.color), (0.9, 0.2, 0.1))
        self.assertEqual(tuple(round(c, 5) for c in bpy.data.lights["Sun"].color), (0.2, 0.9, 0.3))
        self.assertEqual(tuple(round(c, 5) for c in bpy.data.lights["Spot"].color), (0.3, 0.4, 0.9))

        # Custom properties survive with the default export/import options.
        self.assertEqual(point["light_custom_int"], 7)
        self.assertAlmostEqual(bpy.data.objects["Point"]["object_custom_float"], 2.5, 5)
        self.assertEqual(tuple(round(c, 5) for c in bpy.data.objects["Point"].location), (1.0, 2.0, 3.0))

    def test_shape_properties_preserved(self):
        """Radius, sun angle, spot cone, and rect/disk area sizes."""
        self.round_trip()

        self.assertAlmostEqual(bpy.data.lights["Point"].shadow_soft_size, 0.37, 5)
        self.assertAlmostEqual(bpy.data.lights["Spot"].shadow_soft_size, 0.11, 5)
        self.assertAlmostEqual(bpy.data.lights["Spot_point"].shadow_soft_size, 0.0, 5)
        self.assertAlmostEqual(bpy.data.lights["Sun"].angle, math.radians(5.0), 5)

        for name in ("Spot", "Spot_point"):
            self.assertAlmostEqual(bpy.data.lights[name].spot_size, math.radians(50.0), 5, name)
            self.assertAlmostEqual(bpy.data.lights[name].spot_blend, 0.35, 5, name)

        rect = bpy.data.lights["Area_rect"]
        self.assertEqual(rect.shape, 'RECTANGLE')
        self.assertAlmostEqual(rect.size, 0.8, 5)
        self.assertAlmostEqual(rect.size_y, 2.3, 5)

        disk = bpy.data.lights["Area_disk"]
        self.assertEqual(disk.shape, 'DISK')
        self.assertAlmostEqual(disk.size, 1.9, 5)

    def test_area_square_and_ellipse_are_altered(self):
        """Documents a known gap: USD has no square or ellipse light, so the shapes collapse."""
        self.round_trip()

        # SQUARE is written as a RectLight with width == height and read back as RECTANGLE.
        square = bpy.data.lights["Area_square"]
        self.assertEqual(square.shape, 'RECTANGLE')
        self.assertAlmostEqual(square.size, 1.7, 5)
        self.assertAlmostEqual(square.size_y, 1.7, 5)

        # ELLIPSE is written as a DiskLight with radius (size + size_y) / 4 and read back as a
        # DISK of the average diameter; size_y is left at its default.
        ellipse = bpy.data.lights["Area_ellipse"]
        self.assertEqual(ellipse.shape, 'DISK')
        self.assertAlmostEqual(ellipse.size, (1.2 + 2.6) / 2.0, 5)
        self.assertAlmostEqual(ellipse.size_y, 0.25, 5)

    def test_light_intensity_scale_option(self):
        """The import option light_intensity_scale multiplies the imported energy."""
        self.round_trip(import_kwargs={"light_intensity_scale": 2.0})
        self.assertAlmostEqual(bpy.data.lights["Point"].energy, 246.0, 4)
        self.assertAlmostEqual(bpy.data.lights["Sun"].energy, 6.6, 4)

    def test_custom_properties_need_export_option(self):
        """Custom properties are only preserved with export_custom_properties (on by default)."""
        self.round_trip(export_kwargs={"export_custom_properties": False})
        self.assertNotIn("light_custom_int", bpy.data.lights["Point"].keys())
        self.assertNotIn("object_custom_float", bpy.data.objects["Point"].keys())

    def test_animation_written_on_export(self):
        """With export_animation the keyframed energy is written as intensity timeSamples."""
        usd_path = self.round_trip(export_kwargs={"export_animation": True})
        stage = Usd.Stage.Open(str(usd_path))
        intensity = UsdLux.LightAPI(stage.GetPrimAtPath("/root/Point_anim/Point_anim")).GetIntensityAttr()
        self.assertEqual(intensity.GetTimeSamples(), [float(f) for f in range(1, 11)])
        self.assertAlmostEqual(intensity.Get(1), 10.0 / math.pi, 4)
        self.assertAlmostEqual(intensity.Get(5), 50.0 / math.pi, 4)
        self.assertAlmostEqual(intensity.Get(10), 100.0 / math.pi, 4)

    # ---------------------------------------------------------------------------------------
    # Known losses. Each test names the lost property and is expected to fail until fixed.

    @unittest.expectedFailure
    def test_lost_animation_on_import(self):
        """Lost at import: light animation (energy keyframes). The importer reads a single time."""
        self.round_trip(export_kwargs={"export_animation": True})
        light = bpy.data.lights["Point_anim"]
        self.assertIsNotNone(light.animation_data)
        bpy.context.scene.frame_set(10)
        self.assertAlmostEqual(light.energy, 100.0, 3)

    @unittest.expectedFailure
    def test_lost_use_shadow(self):
        """Lost at export: use_shadow (cast shadow) is not written to USD."""
        self.round_trip()
        self.assertEqual(bpy.data.lights["Point"].use_shadow, False)

    @unittest.expectedFailure
    def test_lost_volume_factor(self):
        """Lost at export: volume_factor is not written to USD."""
        self.round_trip()
        self.assertAlmostEqual(bpy.data.lights["Point"].volume_factor, 0.3, 5)

    @unittest.expectedFailure
    def test_lost_transmission_factor(self):
        """Lost at export: transmission_factor is not written to USD."""
        self.round_trip()
        self.assertAlmostEqual(bpy.data.lights["Point"].transmission_factor, 0.6, 5)

    @unittest.expectedFailure
    def test_lost_area_spread(self):
        """Lost at export: area light spread is not written to USD."""
        self.round_trip()
        self.assertAlmostEqual(bpy.data.lights["Area_rect"].spread, math.radians(100.0), 5)

    @unittest.expectedFailure
    def test_lost_soft_falloff(self):
        """Lost at export: use_soft_falloff is not written to USD."""
        self.round_trip()
        self.assertEqual(bpy.data.lights["Point"].use_soft_falloff, False)

    @unittest.expectedFailure
    def test_lost_custom_distance(self):
        """Lost at export: use_custom_distance / cutoff_distance are not written to USD."""
        self.round_trip()
        self.assertEqual(bpy.data.lights["Point"].use_custom_distance, True)
        self.assertAlmostEqual(bpy.data.lights["Point"].cutoff_distance, 12.5, 5)

    @unittest.expectedFailure
    def test_lost_spot_show_cone_and_square(self):
        """Lost at export: spot show_cone and use_square are not written to USD."""
        self.round_trip()
        self.assertEqual(bpy.data.lights["Spot"].show_cone, True)
        self.assertEqual(bpy.data.lights["Spot"].use_square, True)

    @unittest.expectedFailure
    def test_lost_light_linking(self):
        """Lost at export: light linking receiver/blocker collections are not written to USD."""
        self.round_trip()
        linking = bpy.data.objects["Point"].light_linking
        self.assertIsNotNone(linking.receiver_collection)
        self.assertIsNotNone(linking.blocker_collection)

    @unittest.expectedFailure
    def test_lost_eevee_shadow_settings(self):
        """Lost at export: EEVEE shadow settings (filter radius, jitter, resolution, cascades)."""
        self.round_trip()
        point = bpy.data.lights["Point"]
        self.assertAlmostEqual(point.shadow_filter_radius, 2.5, 5)
        self.assertAlmostEqual(point.shadow_jitter_overblur, 25.0, 3)
        self.assertEqual(point.use_shadow_jitter, True)
        self.assertAlmostEqual(point.shadow_maximum_resolution, 0.01, 5)
        self.assertEqual(point.use_absolute_resolution, True)
        self.assertEqual(bpy.data.lights["Sun"].shadow_cascade_count, 3)

    @unittest.expectedFailure
    def test_lost_ellipse_shape(self):
        """Lost at export: ELLIPSE shape and its size_y collapse into a DiskLight."""
        self.round_trip()
        self.assertEqual(bpy.data.lights["Area_ellipse"].shape, 'ELLIPSE')


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
