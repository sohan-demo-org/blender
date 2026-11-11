# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Round-trip audit for cameras: build a scene, export it to USD, import the result into an empty
file and compare the camera properties.

Properties that survive the trip are asserted to be equal. Properties that do not survive are
asserted with their current (lossy) value and marked with a "Known gap" comment, so this file
documents the present behavior and will flag any change to it.
"""

import math
import os
import pathlib
import sys
import tempfile
import unittest
from pxr import Usd, UsdGeom

import bpy

sys.path.append(str(pathlib.Path(__file__).parent.absolute()))
from modules.colored_print import (print_message, use_message_colors)


args = None

RES_X = 1920
RES_Y = 1080


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
        self.open_empty()

    def tearDown(self):
        self._tempdir.cleanup()

        result = self._outcome.result
        ok = all(test != self for test, _ in result.errors + result.failures)
        if not ok:
            print_message(self._testMethodName, 'FAILURE', 'FAILED')
        else:
            print_message(self._testMethodName, 'SUCCESS', 'PASSED')

    def open_empty(self):
        bpy.ops.wm.open_mainfile(filepath=str(self.testdir / "empty.blend"))
        scene = bpy.context.scene
        scene.render.resolution_x = RES_X
        scene.render.resolution_y = RES_Y
        scene.render.pixel_aspect_x = 1.0
        scene.render.pixel_aspect_y = 1.0


class USDCameraRoundtripTest(AbstractUSDTest):
    @staticmethod
    def add_camera(name, location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0)):
        """Add a camera object called `name` with camera data called `name + "Data"`."""
        cam = bpy.data.cameras.new(name + "Data")
        ob = bpy.data.objects.new(name, cam)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = location
        ob.rotation_euler = rotation
        return ob, cam

    @staticmethod
    def flatten(matrix):
        return [v for row in matrix for v in row]

    @classmethod
    def sample(cls, ob, frames=(1,)):
        """Evaluated world matrix, projection matrix and a few camera values per frame."""
        scene = bpy.context.scene
        result = {}
        for frame in frames:
            scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            ob_eval = ob.evaluated_get(depsgraph)
            cam_eval = ob_eval.data
            result[frame] = {
                "matrix_world": cls.flatten(ob_eval.matrix_world),
                "projection": cls.flatten(ob_eval.calc_matrix_camera(depsgraph, x=RES_X, y=RES_Y)),
                "lens": cam_eval.lens,
                "shift_x": cam_eval.shift_x,
                "clip_end": cam_eval.clip_end,
                "focus_distance": cam_eval.dof.focus_distance,
                "fstop": cam_eval.dof.aperture_fstop,
            }
        scene.frame_set(1)
        return result

    def assert_list_almost_equal(self, expected, actual, places, msg):
        self.assertEqual(len(expected), len(actual), msg)
        for i, (e, a) in enumerate(zip(expected, actual)):
            self.assertAlmostEqual(e, a, places, f"{msg} (index {i})")

    def roundtrip(self, name, export_kwargs=None, import_kwargs=None, unit_scale=None):
        """Export the current scene, then import the result into the empty file."""
        usd_path = self.tempdir / f"{name}.usda"
        res = bpy.ops.wm.usd_export(filepath=str(usd_path), **(export_kwargs or {}))
        self.assertEqual({'FINISHED'}, res, f"Unable to export to {usd_path}")

        self.open_empty()
        if unit_scale is not None:
            bpy.context.scene.unit_settings.scale_length = unit_scale
        res = bpy.ops.wm.usd_import(filepath=str(usd_path), **(import_kwargs or {}))
        self.assertEqual({'FINISHED'}, res, f"Unable to import {usd_path}")
        return Usd.Stage.Open(str(usd_path))

    def add_main_camera(self):
        """A perspective camera with non-default values on all the key properties."""
        ob, cam = self.add_camera("CamPersp", (1.0, -2.0, 3.0), (math.radians(60), 0.0, math.radians(30)))
        cam.type = 'PERSP'
        cam.lens = 85.0
        cam.lens_unit = 'FOV'
        cam.sensor_fit = 'VERTICAL'
        cam.sensor_width = 24.0
        cam.sensor_height = 20.0
        cam.shift_x = 0.1
        cam.shift_y = -0.05
        cam.clip_start = 0.25
        cam.clip_end = 250.0
        cam.ortho_scale = 7.5
        cam.dof.use_dof = True
        cam.dof.focus_distance = 3.5
        cam.dof.aperture_fstop = 1.4
        cam.dof.aperture_blades = 6
        cam.dof.aperture_rotation = 0.3
        cam.dof.aperture_ratio = 1.5
        cam.display_size = 2.0
        cam.show_limits = True
        cam.passepartout_alpha = 0.9
        cam["audit_prop"] = 1.5
        ob["audit_ob_prop"] = 7
        return ob, cam

    def test_perspective_preserved(self):
        """Properties of a perspective camera that survive the round trip with default options."""
        ob, cam = self.add_main_camera()
        before = self.sample(ob)[1]

        stage = self.roundtrip("persp")

        # Units: with metersPerUnit = 1 the lens/aperture values are tenths of a meter (cm),
        # the clipping range and focus distance are in meters.
        self.assertAlmostEqual(1.0, UsdGeom.GetStageMetersPerUnit(stage))
        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath("/root/CamPersp/CamPerspData"))
        self.assertTrue(usd_cam)
        self.assertEqual("perspective", usd_cam.GetProjectionAttr().Get())
        self.assertAlmostEqual(0.85, usd_cam.GetFocalLengthAttr().Get(), 5)
        self.assertAlmostEqual(0.2, usd_cam.GetVerticalApertureAttr().Get(), 5)
        self.assert_list_almost_equal([0.25, 250.0], list(usd_cam.GetClippingRangeAttr().Get()), 5, "clippingRange")
        self.assertAlmostEqual(3.5, usd_cam.GetFocusDistanceAttr().Get(), 5)
        self.assertAlmostEqual(1.4, usd_cam.GetFStopAttr().Get(), 5)

        ob = bpy.data.objects["CamPerspData"]
        cam = ob.data
        self.assertEqual('CAMERA', ob.type)
        self.assertEqual("CamPerspData", cam.name)
        self.assertEqual('PERSP', cam.type)
        self.assertAlmostEqual(85.0, cam.lens, 4)
        self.assertAlmostEqual(20.0, cam.sensor_height, 4)
        self.assertAlmostEqual(0.25, cam.clip_start, 5)
        self.assertAlmostEqual(250.0, cam.clip_end, 3)
        self.assertTrue(cam.dof.use_dof)
        self.assertAlmostEqual(3.5, cam.dof.focus_distance, 5)
        self.assertAlmostEqual(1.4, cam.dof.aperture_fstop, 5)
        self.assertAlmostEqual(1.5, cam["audit_prop"], 5)
        self.assertEqual(7, ob["audit_ob_prop"])

        # The object transform and the resulting framing (projection matrix at the render
        # resolution used for the export) are unchanged.
        after = self.sample(ob)[1]
        self.assert_list_almost_equal(before["matrix_world"], after["matrix_world"], 5, "matrix_world")
        self.assert_list_almost_equal(before["projection"], after["projection"], 4, "projection matrix")

    def test_perspective_known_gaps(self):
        """Properties of a perspective camera that are lost or altered with default options."""
        self.add_main_camera()
        bpy.context.scene.camera = bpy.data.objects["CamPersp"]

        stage = self.roundtrip("persp_gaps")

        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath("/root/CamPersp/CamPerspData"))
        # Vertical fit: the horizontal aperture is derived from the render aspect ratio
        # (20 mm * 1920 / 1080) instead of the sensor width (24 mm).
        self.assertAlmostEqual(0.355556, usd_cam.GetHorizontalApertureAttr().Get(), 5)
        self.assertAlmostEqual(0.02, usd_cam.GetHorizontalApertureOffsetAttr().Get(), 5)
        self.assertAlmostEqual(-0.01, usd_cam.GetVerticalApertureOffsetAttr().Get(), 5)

        ob = bpy.data.objects["CamPerspData"]
        cam = ob.data

        # Known gap: the active scene camera is not written, nothing is assigned on import.
        self.assertIsNone(bpy.context.scene.camera)

        # Known gap: the imported object takes the name of the camera data ("CamPerspData"),
        # the object name ("CamPersp") is only kept as a custom string property.
        self.assertNotIn("CamPersp", bpy.data.objects)

        # Known gap: sensor fit is not written, the importer derives it from the apertures.
        self.assertEqual('HORIZONTAL', cam.sensor_fit)
        # Known gap: sensor width (24) is replaced by the render-aspect derived aperture.
        self.assertAlmostEqual(35.5556, cam.sensor_width, 3)
        # Known gap: shift X/Y (0.1 / -0.05) are re-expressed relative to the new, larger sensor
        # size. The framing is the same (see test_perspective_preserved), the values are not.
        self.assertAlmostEqual(0.05625, cam.shift_x, 5)
        self.assertAlmostEqual(-0.028125, cam.shift_y, 5)

        # Known gap: lens unit (FOV) is not written.
        self.assertEqual('MILLIMETERS', cam.lens_unit)
        # Known gap: aperture blades / rotation / ratio (6 / 0.3 / 1.5) are not written.
        self.assertEqual(0, cam.dof.aperture_blades)
        self.assertAlmostEqual(0.0, cam.dof.aperture_rotation, 5)
        self.assertAlmostEqual(1.0, cam.dof.aperture_ratio, 5)
        # Known gap: orthographic scale (7.5) of a perspective camera is not written.
        self.assertAlmostEqual(6.0, cam.ortho_scale, 5)
        # Known gap: viewport display settings (2.0 / True / 0.9) are not written.
        self.assertAlmostEqual(1.0, cam.display_size, 5)
        self.assertFalse(cam.show_limits)
        self.assertAlmostEqual(0.5, cam.passepartout_alpha, 5)

    def test_sensor_fit_known_gaps(self):
        """Sensor size for horizontal and automatic sensor fit."""
        for name, fit in (("CamHoriz", 'HORIZONTAL'), ("CamAuto", 'AUTO')):
            ob, cam = self.add_camera(name)
            cam.lens = 24.0
            cam.sensor_fit = fit
            cam.sensor_width = 30.0
            cam.sensor_height = 10.0
            cam.shift_x = -0.2
            cam.shift_y = 0.15
        before = {name: self.sample(bpy.data.objects[name])[1] for name in ("CamHoriz", "CamAuto")}

        self.roundtrip("sensor_fit")

        for name in ("CamHoriz", "CamAuto"):
            ob = bpy.data.objects[name + "Data"]
            cam = ob.data
            self.assertAlmostEqual(24.0, cam.lens, 4)
            self.assertAlmostEqual(30.0, cam.sensor_width, 4)
            self.assertAlmostEqual(-0.2, cam.shift_x, 5)
            self.assertAlmostEqual(0.15, cam.shift_y, 5)
            after = self.sample(ob)[1]
            self.assert_list_almost_equal(before[name]["projection"], after["projection"], 4, "projection matrix")

            # Known gap: 'AUTO' sensor fit comes back as 'HORIZONTAL'.
            self.assertEqual('HORIZONTAL', cam.sensor_fit)
            # Known gap: sensor height (10) is replaced by the render-aspect derived aperture
            # (30 mm * 1080 / 1920).
            self.assertAlmostEqual(16.875, cam.sensor_height, 4)

    def test_dof_focus_object_known_gap(self):
        """Depth of field driven by a focus object."""
        target = bpy.data.objects.new("FocusTarget", None)
        bpy.context.scene.collection.objects.link(target)
        target.location = (8.0, 0.0, -6.0)
        ob, cam = self.add_camera("CamFocusObj", (8.0, 0.0, 1.0))
        cam.dof.use_dof = True
        cam.dof.focus_object = target
        cam.dof.focus_distance = 2.0
        cam.dof.aperture_fstop = 5.6

        self.roundtrip("focus_object")

        cam = bpy.data.objects["CamFocusObjData"].data
        self.assertTrue(cam.dof.use_dof)
        self.assertAlmostEqual(5.6, cam.dof.aperture_fstop, 5)
        self.assertIn("FocusTarget", bpy.data.objects)
        # Known gap: the focus object link is not written. The distance to the object (7 m) is
        # baked into the focus distance, replacing the camera's own value (2 m).
        self.assertIsNone(cam.dof.focus_object)
        self.assertAlmostEqual(7.0, cam.dof.focus_distance, 5)

    def test_dof_disabled_known_gap(self):
        """Depth of field values of a camera with depth of field turned off."""
        ob, cam = self.add_camera("CamDofOff")
        cam.dof.use_dof = False
        cam.dof.focus_distance = 7.0
        cam.dof.aperture_fstop = 4.0

        stage = self.roundtrip("dof_off")

        prim = stage.GetPrimAtPath("/root/CamDofOff/CamDofOffData")
        self.assertFalse(prim.GetAttribute("fStop").HasAuthoredValue())
        self.assertFalse(prim.GetAttribute("focusDistance").HasAuthoredValue())

        cam = bpy.data.objects["CamDofOffData"].data
        self.assertFalse(cam.dof.use_dof)
        # Known gap: with depth of field off, focus distance (7) and f-stop (4) are not written
        # and the importer applies the USD fallback values (0) instead.
        self.assertAlmostEqual(0.0, cam.dof.focus_distance, 5)
        self.assertAlmostEqual(0.0, cam.dof.aperture_fstop, 5)

    def test_ortho_and_panoramic_known_gap(self):
        """Orthographic and panoramic cameras."""
        ob, cam = self.add_camera("CamOrtho", (12.0, 0.0, 1.0), (0.2, 0.0, 0.0))
        cam.type = 'ORTHO'
        cam.ortho_scale = 7.5
        ob, cam = self.add_camera("CamPano", (14.0, 0.0, 1.0))
        cam.type = 'PANO'
        before = {name: self.sample(bpy.data.objects[name])[1] for name in ("CamOrtho", "CamPano")}

        stage = self.roundtrip("ortho_pano")

        for name in ("CamOrtho", "CamPano"):
            # Known gap: only perspective cameras are written. Orthographic and panoramic
            # cameras are exported as a bare Xform and come back as an empty.
            self.assertEqual("Xform", stage.GetPrimAtPath(f"/root/{name}").GetTypeName())
            self.assertFalse(stage.GetPrimAtPath(f"/root/{name}/{name}Data"))
            self.assertNotIn(name + "Data", bpy.data.objects)
            ob = bpy.data.objects[name]
            self.assertEqual('EMPTY', ob.type)
            # The transform does survive.
            after = self.sample_matrix(ob)
            self.assert_list_almost_equal(before[name]["matrix_world"], after, 5, "matrix_world")
        self.assertEqual(0, len(bpy.data.cameras))

    def sample_matrix(self, ob):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return self.flatten(ob.evaluated_get(depsgraph).matrix_world)

    def test_names_merge_parent_xform(self):
        """Object and camera data names with the 'merge_parent_xform' export option."""
        self.add_camera("CamPersp")

        # Exporter option on: one Camera prim named after the object.
        stage = self.roundtrip("merge_export", export_kwargs={"merge_parent_xform": True})
        self.assertEqual("Camera", stage.GetPrimAtPath("/root/CamPersp").GetTypeName())
        ob = bpy.data.objects["CamPersp"]
        self.assertEqual('CAMERA', ob.type)
        # Known gap: with this option the camera data name ("CamPerspData") is lost instead.
        self.assertEqual("CamPersp", ob.data.name)

        # Importer option off: the object name survives, on an extra parent empty.
        self.open_empty()
        self.add_camera("CamPersp")
        self.roundtrip("no_merge_import", import_kwargs={"merge_parent_xform": False})
        self.assertEqual('EMPTY', bpy.data.objects["CamPersp"].type)
        ob = bpy.data.objects["CamPerspData"]
        self.assertEqual('CAMERA', ob.type)
        self.assertEqual(bpy.data.objects["CamPersp"], ob.parent)

    def add_animated_camera(self):
        ob, cam = self.add_camera("CamAnim")
        cam.dof.use_dof = True
        keys = (
            # frame, lens, location X, rotation Z, shift X, clip end, focus distance, f-stop
            (1, 35.0, 0.0, 0.0, 0.0, 100.0, 2.0, 2.8),
            (5, 70.0, 4.0, 1.0, 0.2, 200.0, 6.0, 8.0),
        )
        for frame, lens, loc_x, rot_z, shift_x, clip_end, focus_distance, fstop in keys:
            cam.lens = lens
            cam.keyframe_insert("lens", frame=frame)
            cam.shift_x = shift_x
            cam.keyframe_insert("shift_x", frame=frame)
            cam.clip_end = clip_end
            cam.keyframe_insert("clip_end", frame=frame)
            cam.dof.focus_distance = focus_distance
            cam.dof.keyframe_insert("focus_distance", frame=frame)
            cam.dof.aperture_fstop = fstop
            cam.dof.keyframe_insert("aperture_fstop", frame=frame)
            ob.location = (loc_x, 1.0, 2.0)
            ob.keyframe_insert("location", frame=frame)
            ob.rotation_euler = (1.2, 0.0, rot_z)
            ob.keyframe_insert("rotation_euler", frame=frame)
        scene = bpy.context.scene
        scene.frame_start = 1
        scene.frame_end = 5
        scene.frame_set(1)
        return ob, cam

    def test_animation_exported(self):
        """Animated camera values and transform with the 'export_animation' option on."""
        frames = (1, 2, 3, 4, 5)
        ob, cam = self.add_animated_camera()
        before = self.sample(ob, frames)
        self.assertNotAlmostEqual(before[1]["lens"], before[5]["lens"], 1)

        stage = self.roundtrip("anim", export_kwargs={"export_animation": True})

        self.assertEqual(1.0, stage.GetStartTimeCode())
        self.assertEqual(5.0, stage.GetEndTimeCode())
        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath("/root/CamAnim/CamAnimData"))
        self.assertEqual([1.0, 2.0, 3.0, 4.0, 5.0], usd_cam.GetFocalLengthAttr().GetTimeSamples())

        scene = bpy.context.scene
        self.assertEqual(1, scene.frame_start)
        self.assertEqual(5, scene.frame_end)

        ob = bpy.data.objects["CamAnimData"]
        after = self.sample(ob, frames)
        for frame in frames:
            for key in ("lens", "shift_x", "clip_end", "focus_distance", "fstop"):
                self.assertAlmostEqual(before[frame][key], after[frame][key], 3, f"Frame {frame}: {key}")
            self.assert_list_almost_equal(
                before[frame]["matrix_world"], after[frame]["matrix_world"], 4, f"Frame {frame}: matrix_world")
            self.assert_list_almost_equal(
                before[frame]["projection"], after[frame]["projection"], 4, f"Frame {frame}: projection")

        # The camera data animation comes back as F-Curves, with one key per exported frame
        # instead of the two original keys.
        self.assertIsNotNone(ob.data.animation_data)
        self.assertIsNotNone(ob.data.animation_data.action)
        # Known gap: the object transform animation does not come back as F-Curves, it is driven
        # by a Transform Cache constraint that reads the USD file.
        self.assertIsNone(ob.animation_data)
        self.assertEqual(['TRANSFORM_CACHE'], [c.type for c in ob.constraints])

    def test_animation_not_exported_by_default(self):
        """Animated camera with default export options: only the current frame is written."""
        frames = (1, 5)
        ob, cam = self.add_animated_camera()
        before = self.sample(ob, frames)

        stage = self.roundtrip("anim_default")

        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath("/root/CamAnim/CamAnimData"))
        self.assertEqual([], usd_cam.GetFocalLengthAttr().GetTimeSamples())

        ob = bpy.data.objects["CamAnimData"]
        after = self.sample(ob, frames)
        # Known gap (default options): 'export_animation' is off by default, so the animation is
        # dropped and the camera is frozen at the frame that was current during the export (1).
        self.assertIsNone(ob.data.animation_data)
        self.assertEqual([], [c.type for c in ob.constraints])
        self.assertAlmostEqual(before[1]["lens"], after[5]["lens"], 3)
        self.assert_list_almost_equal(before[1]["matrix_world"], after[5]["matrix_world"], 4, "matrix_world")

        # Known gap: importing a USD file without a time range sets the scene frame range to 0-0
        # ('set_frame_range' import option is on by default).
        scene = bpy.context.scene
        self.assertEqual(0, scene.frame_start)
        self.assertEqual(0, scene.frame_end)

    def test_units_centimeters(self):
        """Stage in centimeters: values are scaled in the file and equal after the round trip."""
        ob, cam = self.add_main_camera()
        before = self.sample(ob)[1]

        stage = self.roundtrip("units_cm", export_kwargs={"convert_scene_units": 'CENTIMETERS'})

        self.assertAlmostEqual(0.01, UsdGeom.GetStageMetersPerUnit(stage))
        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath("/root/CamPersp/CamPerspData"))
        # Tenths of a centimeter are millimeters.
        self.assertAlmostEqual(85.0, usd_cam.GetFocalLengthAttr().Get(), 4)
        self.assertAlmostEqual(20.0, usd_cam.GetVerticalApertureAttr().Get(), 4)
        self.assert_list_almost_equal([25.0, 25000.0], list(usd_cam.GetClippingRangeAttr().Get()), 2, "clippingRange")
        self.assertAlmostEqual(350.0, usd_cam.GetFocusDistanceAttr().Get(), 3)

        ob = bpy.data.objects["CamPerspData"]
        cam = ob.data
        self.assertAlmostEqual(85.0, cam.lens, 4)
        self.assertAlmostEqual(20.0, cam.sensor_height, 4)
        self.assertAlmostEqual(0.25, cam.clip_start, 5)
        self.assertAlmostEqual(250.0, cam.clip_end, 3)
        self.assertAlmostEqual(3.5, cam.dof.focus_distance, 5)
        after = self.sample(ob)[1]
        self.assert_list_almost_equal(before["matrix_world"], after["matrix_world"], 4, "matrix_world")
        self.assert_list_almost_equal(before["projection"], after["projection"], 4, "projection matrix")

    def test_units_scene_unit_scale_known_gap(self):
        """Scene with a unit scale of 0.01 (both the exported and the importing scene)."""
        bpy.context.scene.unit_settings.scale_length = 0.01
        ob, cam = self.add_main_camera()
        before = self.sample(ob)[1]

        stage = self.roundtrip("units_scale_length", unit_scale=0.01)

        # The stage still says 1 meter per unit, but the lens is written as 85 tenths of a unit.
        self.assertAlmostEqual(1.0, UsdGeom.GetStageMetersPerUnit(stage))
        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath("/root/CamPersp/CamPerspData"))
        self.assertAlmostEqual(85.0, usd_cam.GetFocalLengthAttr().Get(), 4)

        ob = bpy.data.objects["CamPerspData"]
        cam = ob.data
        # Known gap: focal length (85 mm) and sensor height (20 mm) come back 100 times larger.
        self.assertAlmostEqual(8500.0, cam.lens, 1)
        self.assertAlmostEqual(2000.0, cam.sensor_height, 1)
        # Clipping, focus distance and the framing are unchanged.
        self.assertAlmostEqual(0.25, cam.clip_start, 5)
        self.assertAlmostEqual(250.0, cam.clip_end, 3)
        self.assertAlmostEqual(3.5, cam.dof.focus_distance, 5)
        after = self.sample(ob)[1]
        self.assert_list_almost_equal(before["projection"], after["projection"], 4, "projection matrix")


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
