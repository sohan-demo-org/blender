/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: Apache-2.0 */

#include "testing/testing.h"

#include "BLI_math_constants.hh"
#include "BLI_rect.hh"

#include "DNA_vec_types.h"

namespace blender::tests {

static void expect_rcti_eq(const rcti &rect, int xmin, int xmax, int ymin, int ymax)
{
  EXPECT_EQ(rect.xmin, xmin);
  EXPECT_EQ(rect.xmax, xmax);
  EXPECT_EQ(rect.ymin, ymin);
  EXPECT_EQ(rect.ymax, ymax);
}

static void expect_rctf_near(
    const rctf &rect, float xmin, float xmax, float ymin, float ymax, float eps = 1e-6f)
{
  EXPECT_NEAR(rect.xmin, xmin, eps);
  EXPECT_NEAR(rect.xmax, xmax, eps);
  EXPECT_NEAR(rect.ymin, ymin, eps);
  EXPECT_NEAR(rect.ymax, ymax, eps);
}

/* -------------------------------------------------------------------- */
/** \name Initialization & Validity
 * \{ */

TEST(rect, InitSanitizes)
{
  rcti ri;
  BLI_rcti_init(&ri, 10, 0, 20, 5);
  expect_rcti_eq(ri, 0, 10, 5, 20);
  EXPECT_TRUE(BLI_rcti_is_valid(&ri));

  rctf rf;
  BLI_rctf_init(&rf, 1.5f, -1.5f, 0.0f, -4.0f);
  expect_rctf_near(rf, -1.5f, 1.5f, -4.0f, 0.0f);
  EXPECT_TRUE(BLI_rctf_is_valid(&rf));
}

TEST(rect, IsEmpty)
{
  rcti ri = {0, 10, 0, 10};
  EXPECT_FALSE(BLI_rcti_is_empty(&ri));
  ri = {0, 0, 0, 10};
  EXPECT_TRUE(BLI_rcti_is_empty(&ri));
  ri = {0, 10, 5, 5};
  EXPECT_TRUE(BLI_rcti_is_empty(&ri));
  ri = {10, 0, 0, 10};
  EXPECT_TRUE(BLI_rcti_is_empty(&ri));

  rctf rf = {0.0f, 0.001f, 0.0f, 0.001f};
  EXPECT_FALSE(BLI_rctf_is_empty(&rf));
  rf = {1.0f, 1.0f, 0.0f, 1.0f};
  EXPECT_TRUE(BLI_rctf_is_empty(&rf));
  rf = {0.0f, 1.0f, 1.0f, -1.0f};
  EXPECT_TRUE(BLI_rctf_is_empty(&rf));
}

TEST(rect, IsValidAndSanitize)
{
  /* A zero-sized rectangle is empty but still valid. */
  rcti ri = {5, 5, 5, 5};
  EXPECT_TRUE(BLI_rcti_is_valid(&ri));
  EXPECT_TRUE(BLI_rcti_is_empty(&ri));

  ri = {10, 0, 3, 7};
  EXPECT_FALSE(BLI_rcti_is_valid(&ri));
  BLI_rcti_sanitize(&ri);
  expect_rcti_eq(ri, 0, 10, 3, 7);

  ri = {0, 10, 7, 3};
  EXPECT_FALSE(BLI_rcti_is_valid(&ri));
  BLI_rcti_sanitize(&ri);
  expect_rcti_eq(ri, 0, 10, 3, 7);

  rctf rf = {2.0f, -2.0f, 4.0f, -4.0f};
  EXPECT_FALSE(BLI_rctf_is_valid(&rf));
  BLI_rctf_sanitize(&rf);
  expect_rctf_near(rf, -2.0f, 2.0f, -4.0f, 4.0f);

  /* Sanitizing an already valid rectangle is a no-op. */
  BLI_rctf_sanitize(&rf);
  expect_rctf_near(rf, -2.0f, 2.0f, -4.0f, 4.0f);
}

TEST(rect, InitPtRadius)
{
  rcti ri;
  const int xy_i[2] = {3, 4};
  BLI_rcti_init_pt_radius(&ri, xy_i, 2);
  expect_rcti_eq(ri, 1, 5, 2, 6);

  BLI_rcti_init_pt_radius(&ri, xy_i, 0);
  expect_rcti_eq(ri, 3, 3, 4, 4);

  rctf rf;
  const float xy_f[2] = {1.5f, -2.5f};
  BLI_rctf_init_pt_radius(&rf, xy_f, 0.5f);
  expect_rctf_near(rf, 1.0f, 2.0f, -3.0f, -2.0f);
}

TEST(rect, MinMax)
{
  rcti ri;
  BLI_rcti_init_minmax(&ri);
  /* Before any point is added the rectangle is inverted, so it is not valid. */
  EXPECT_FALSE(BLI_rcti_is_valid(&ri));

  const int pt_a[2] = {3, -1};
  BLI_rcti_do_minmax_v(&ri, pt_a);
  expect_rcti_eq(ri, 3, 3, -1, -1);

  const int pt_b[2] = {-2, 5};
  const int pt_c[2] = {0, 0};
  BLI_rcti_do_minmax_v(&ri, pt_b);
  BLI_rcti_do_minmax_v(&ri, pt_c);
  expect_rcti_eq(ri, -2, 3, -1, 5);

  rctf rf;
  BLI_rctf_init_minmax(&rf);
  EXPECT_FALSE(BLI_rctf_is_valid(&rf));
  const float pts[3][2] = {{0.5f, 0.25f}, {-1.0f, 2.0f}, {4.0f, -3.0f}};
  for (const float *pt : pts) {
    BLI_rctf_do_minmax_v(&rf, pt);
  }
  expect_rctf_near(rf, -1.0f, 4.0f, -3.0f, 2.0f);
}

TEST(rect, MinMaxRcti)
{
  rcti ri = {0, 5, 0, 5};
  const rcti other = {-1, 3, 2, 8};
  BLI_rcti_do_minmax_rcti(&ri, &other);
  expect_rcti_eq(ri, -1, 5, 0, 8);

  /* Merging into an "init_minmax" rectangle yields the other rectangle. */
  BLI_rcti_init_minmax(&ri);
  BLI_rcti_do_minmax_rcti(&ri, &other);
  expect_rcti_eq(ri, -1, 3, 2, 8);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Center & Size
 * \{ */

TEST(rect, CenterAndSize)
{
  const rcti ri = {0, 5, -4, 10};
  EXPECT_EQ(BLI_rcti_size_x(&ri), 5);
  EXPECT_EQ(BLI_rcti_size_y(&ri), 14);
  /* Integer center truncates. */
  EXPECT_EQ(BLI_rcti_cent_x(&ri), 2);
  EXPECT_EQ(BLI_rcti_cent_y(&ri), 3);
  EXPECT_FLOAT_EQ(BLI_rcti_cent_x_fl(&ri), 2.5f);
  EXPECT_FLOAT_EQ(BLI_rcti_cent_y_fl(&ri), 3.0f);

  const rctf rf = {-1.0f, 2.0f, 0.5f, 1.5f};
  EXPECT_FLOAT_EQ(BLI_rctf_size_x(&rf), 3.0f);
  EXPECT_FLOAT_EQ(BLI_rctf_size_y(&rf), 1.0f);
  EXPECT_FLOAT_EQ(BLI_rctf_cent_x(&rf), 0.5f);
  EXPECT_FLOAT_EQ(BLI_rctf_cent_y(&rf), 1.0f);

  /* Inverted rectangles report negative sizes. */
  const rcti inverted = {10, 0, 10, 0};
  EXPECT_EQ(BLI_rcti_size_x(&inverted), -10);
  EXPECT_EQ(BLI_rcti_size_y(&inverted), -10);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Point & Range Intersection
 * \{ */

TEST(rect, IsectPtInclusive)
{
  const rcti ri = {0, 10, 0, 10};
  EXPECT_TRUE(BLI_rcti_isect_pt(&ri, 5, 5));
  EXPECT_TRUE(BLI_rcti_isect_pt(&ri, 0, 0));
  EXPECT_TRUE(BLI_rcti_isect_pt(&ri, 10, 10));
  EXPECT_FALSE(BLI_rcti_isect_pt(&ri, -1, 5));
  EXPECT_FALSE(BLI_rcti_isect_pt(&ri, 11, 5));
  EXPECT_FALSE(BLI_rcti_isect_pt(&ri, 5, -1));
  EXPECT_FALSE(BLI_rcti_isect_pt(&ri, 5, 11));

  const int in[2] = {10, 0};
  const int out[2] = {10, 11};
  EXPECT_TRUE(BLI_rcti_isect_pt_v(&ri, in));
  EXPECT_FALSE(BLI_rcti_isect_pt_v(&ri, out));

  EXPECT_TRUE(BLI_rcti_isect_x(&ri, 0));
  EXPECT_TRUE(BLI_rcti_isect_x(&ri, 10));
  EXPECT_FALSE(BLI_rcti_isect_x(&ri, 11));
  EXPECT_TRUE(BLI_rcti_isect_y(&ri, 10));
  EXPECT_FALSE(BLI_rcti_isect_y(&ri, -1));
}

TEST(rect, IsectPtFloat)
{
  const rctf rf = {-1.0f, 1.0f, -0.5f, 0.5f};
  EXPECT_TRUE(BLI_rctf_isect_pt(&rf, 0.0f, 0.0f));
  EXPECT_TRUE(BLI_rctf_isect_pt(&rf, -1.0f, 0.5f));
  EXPECT_FALSE(BLI_rctf_isect_pt(&rf, 1.0001f, 0.0f));
  EXPECT_FALSE(BLI_rctf_isect_pt(&rf, 0.0f, -0.5001f));

  const float in[2] = {1.0f, -0.5f};
  const float out[2] = {0.0f, 0.75f};
  EXPECT_TRUE(BLI_rctf_isect_pt_v(&rf, in));
  EXPECT_FALSE(BLI_rctf_isect_pt_v(&rf, out));

  EXPECT_TRUE(BLI_rctf_isect_x(&rf, 1.0f));
  EXPECT_FALSE(BLI_rctf_isect_x(&rf, -1.5f));
  EXPECT_TRUE(BLI_rctf_isect_y(&rf, -0.5f));
  EXPECT_FALSE(BLI_rctf_isect_y(&rf, 0.6f));
}

TEST(rect, Length)
{
  const rcti ri = {0, 10, -5, 5};
  EXPECT_EQ(BLI_rcti_length_x(&ri, -3), 3);
  EXPECT_EQ(BLI_rcti_length_x(&ri, 0), 0);
  EXPECT_EQ(BLI_rcti_length_x(&ri, 5), 0);
  EXPECT_EQ(BLI_rcti_length_x(&ri, 14), 4);
  EXPECT_EQ(BLI_rcti_length_y(&ri, -7), 2);
  EXPECT_EQ(BLI_rcti_length_y(&ri, 5), 0);
  EXPECT_EQ(BLI_rcti_length_y(&ri, 8), 3);

  const rctf rf = {0.0f, 1.0f, 0.0f, 2.0f};
  EXPECT_FLOAT_EQ(BLI_rctf_length_x(&rf, -0.25f), 0.25f);
  EXPECT_FLOAT_EQ(BLI_rctf_length_x(&rf, 0.5f), 0.0f);
  EXPECT_FLOAT_EQ(BLI_rctf_length_x(&rf, 1.5f), 0.5f);
  EXPECT_FLOAT_EQ(BLI_rctf_length_y(&rf, -1.0f), 1.0f);
  EXPECT_FLOAT_EQ(BLI_rctf_length_y(&rf, 2.0f), 0.0f);
  EXPECT_FLOAT_EQ(BLI_rctf_length_y(&rf, 3.0f), 1.0f);
}

TEST(rect, Inside)
{
  const rcti outer = {0, 10, 0, 10};
  const rcti inner = {2, 8, 2, 8};
  const rcti overlapping = {2, 12, 2, 8};
  EXPECT_TRUE(BLI_rcti_inside_rcti(&outer, &inner));
  EXPECT_FALSE(BLI_rcti_inside_rcti(&inner, &outer));
  EXPECT_TRUE(BLI_rcti_inside_rcti(&outer, &outer));
  EXPECT_FALSE(BLI_rcti_inside_rcti(&outer, &overlapping));

  const rctf outer_f = {0.0f, 1.0f, 0.0f, 1.0f};
  const rctf inner_f = {0.25f, 0.75f, 0.0f, 1.0f};
  const rctf outside_f = {-0.1f, 0.5f, 0.0f, 1.0f};
  EXPECT_TRUE(BLI_rctf_inside_rctf(&outer_f, &inner_f));
  EXPECT_FALSE(BLI_rctf_inside_rctf(&inner_f, &outer_f));
  EXPECT_FALSE(BLI_rctf_inside_rctf(&outer_f, &outside_f));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Rectangle Intersection
 * \{ */

TEST(rect, IsectRcti)
{
  const rcti a = {0, 10, 0, 10};
  const rcti b = {5, 15, -5, 5};
  rcti dest;
  EXPECT_TRUE(BLI_rcti_isect(&a, &b, &dest));
  expect_rcti_eq(dest, 5, 10, 0, 5);

  /* Intersection is symmetric. */
  EXPECT_TRUE(BLI_rcti_isect(&b, &a, &dest));
  expect_rcti_eq(dest, 5, 10, 0, 5);

  /* Touching edges count as an (empty) intersection. */
  const rcti touching = {10, 20, 0, 10};
  EXPECT_TRUE(BLI_rcti_isect(&a, &touching, &dest));
  expect_rcti_eq(dest, 10, 10, 0, 10);
  EXPECT_TRUE(BLI_rcti_is_empty(&dest));

  /* Disjoint rectangles clear the destination. */
  const rcti disjoint = {11, 20, 0, 10};
  dest = {1, 2, 3, 4};
  EXPECT_FALSE(BLI_rcti_isect(&a, &disjoint, &dest));
  expect_rcti_eq(dest, 0, 0, 0, 0);

  /* Destination is optional. */
  EXPECT_TRUE(BLI_rcti_isect(&a, &b, nullptr));
  EXPECT_FALSE(BLI_rcti_isect(&a, &disjoint, nullptr));
}

TEST(rect, IsectRctf)
{
  const rctf a = {0.0f, 1.0f, 0.0f, 1.0f};
  const rctf b = {0.5f, 2.0f, 0.25f, 0.75f};
  rctf dest;
  EXPECT_TRUE(BLI_rctf_isect(&a, &b, &dest));
  expect_rctf_near(dest, 0.5f, 1.0f, 0.25f, 0.75f);

  const rctf disjoint_y = {0.0f, 1.0f, 1.5f, 2.0f};
  dest = {9.0f, 9.0f, 9.0f, 9.0f};
  EXPECT_FALSE(BLI_rctf_isect(&a, &disjoint_y, &dest));
  expect_rctf_near(dest, 0.0f, 0.0f, 0.0f, 0.0f);

  EXPECT_TRUE(BLI_rctf_isect(&a, &b, nullptr));
}

TEST(rect, IsectRectRange)
{
  const rcti a = {0, 10, 0, 10};
  const rcti b = {5, 15, -5, 5};
  int range[2];
  EXPECT_TRUE(BLI_rcti_isect_rect_x(&a, &b, range));
  EXPECT_EQ(range[0], 5);
  EXPECT_EQ(range[1], 10);
  EXPECT_TRUE(BLI_rcti_isect_rect_y(&a, &b, range));
  EXPECT_EQ(range[0], 0);
  EXPECT_EQ(range[1], 5);

  /* Only the X ranges are disjoint here. */
  const rcti c = {20, 30, 0, 10};
  EXPECT_FALSE(BLI_rcti_isect_rect_x(&a, &c, range));
  EXPECT_EQ(range[0], 0);
  EXPECT_EQ(range[1], 0);
  EXPECT_TRUE(BLI_rcti_isect_rect_y(&a, &c, nullptr));

  const rctf af = {0.0f, 1.0f, 0.0f, 1.0f};
  const rctf bf = {0.5f, 2.0f, 2.0f, 3.0f};
  float range_f[2];
  EXPECT_TRUE(BLI_rctf_isect_rect_x(&af, &bf, range_f));
  EXPECT_FLOAT_EQ(range_f[0], 0.5f);
  EXPECT_FLOAT_EQ(range_f[1], 1.0f);
  EXPECT_FALSE(BLI_rctf_isect_rect_y(&af, &bf, range_f));
  EXPECT_FLOAT_EQ(range_f[0], 0.0f);
  EXPECT_FLOAT_EQ(range_f[1], 0.0f);
  EXPECT_TRUE(BLI_rctf_isect_rect_x(&af, &bf, nullptr));
}

TEST(rect, IsectSegment)
{
  const rcti ri = {0, 10, 0, 10};
  {
    /* Fully inside. */
    const int s1[2] = {2, 2}, s2[2] = {3, 3};
    EXPECT_TRUE(BLI_rcti_isect_segment(&ri, s1, s2));
  }
  {
    /* One end inside. */
    const int s1[2] = {5, 5}, s2[2] = {50, 5};
    EXPECT_TRUE(BLI_rcti_isect_segment(&ri, s1, s2));
  }
  {
    /* Both ends outside, crossing the rectangle. */
    const int s1[2] = {-5, 5}, s2[2] = {15, 5};
    EXPECT_TRUE(BLI_rcti_isect_segment(&ri, s1, s2));
  }
  {
    /* Both ends on the same outer side. */
    const int s1[2] = {-5, 0}, s2[2] = {-1, 10};
    EXPECT_FALSE(BLI_rcti_isect_segment(&ri, s1, s2));
  }
  {
    /* Passes beyond the top-left corner. */
    const int s1[2] = {-4, 9}, s2[2] = {1, 16};
    EXPECT_FALSE(BLI_rcti_isect_segment(&ri, s1, s2));
  }

  const rctf rf = {0.0f, 1.0f, 0.0f, 1.0f};
  {
    const float s1[2] = {-0.5f, 0.5f}, s2[2] = {1.5f, 0.5f};
    EXPECT_TRUE(BLI_rctf_isect_segment(&rf, s1, s2));
  }
  {
    const float s1[2] = {0.5f, -1.0f}, s2[2] = {0.5f, 2.0f};
    EXPECT_TRUE(BLI_rctf_isect_segment(&rf, s1, s2));
  }
  {
    const float s1[2] = {2.0f, 0.0f}, s2[2] = {3.0f, 1.0f};
    EXPECT_FALSE(BLI_rctf_isect_segment(&rf, s1, s2));
  }
  {
    const float s1[2] = {-0.4f, 0.9f}, s2[2] = {0.1f, 1.6f};
    EXPECT_FALSE(BLI_rctf_isect_segment(&rf, s1, s2));
  }
}

TEST(rect, IsectCircle)
{
  const rcti ri = {0, 10, 0, 10};
  const float center_inside[2] = {5.0f, 5.0f};
  EXPECT_TRUE(BLI_rcti_isect_circle(&ri, center_inside, 0.1f));

  /* Circle to the right of the rectangle, touching it exactly. */
  const float center_right[2] = {13.0f, 5.0f};
  EXPECT_TRUE(BLI_rcti_isect_circle(&ri, center_right, 3.0f));
  EXPECT_FALSE(BLI_rcti_isect_circle(&ri, center_right, 2.9f));

  /* Diagonal from the top-right corner: distance is 5 (3-4-5 triangle). */
  const float center_corner[2] = {13.0f, 14.0f};
  EXPECT_TRUE(BLI_rcti_isect_circle(&ri, center_corner, 5.0f));
  EXPECT_FALSE(BLI_rcti_isect_circle(&ri, center_corner, 4.9f));

  const rctf rf = {0.0f, 10.0f, 0.0f, 10.0f};
  const float center_below_left[2] = {-3.0f, -4.0f};
  EXPECT_TRUE(BLI_rctf_isect_circle(&rf, center_below_left, 5.0f));
  EXPECT_FALSE(BLI_rctf_isect_circle(&rf, center_below_left, 4.9f));
  EXPECT_TRUE(BLI_rctf_isect_circle(&rf, center_inside, 0.0f));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Union
 * \{ */

TEST(rect, Union)
{
  rcti ri = {0, 5, 0, 5};
  const rcti other = {-2, 3, 1, 8};
  BLI_rcti_union(&ri, &other);
  expect_rcti_eq(ri, -2, 5, 0, 8);

  /* Union with a contained rectangle is a no-op. */
  const rcti inner = {0, 1, 1, 2};
  BLI_rcti_union(&ri, &inner);
  expect_rcti_eq(ri, -2, 5, 0, 8);

  rctf rf = {0.0f, 1.0f, 0.0f, 1.0f};
  const rctf other_f = {0.5f, 2.0f, -1.0f, 0.5f};
  BLI_rctf_union(&rf, &other_f);
  expect_rctf_near(rf, 0.0f, 2.0f, -1.0f, 1.0f);
}

TEST(rect, UnionAxis)
{
  rctf rf = {0.0f, 1.0f, 0.0f, 1.0f};
  BLI_rctf_union_x(&rf, 5.0f);
  expect_rctf_near(rf, 0.0f, 5.0f, 0.0f, 1.0f);
  BLI_rctf_union_x(&rf, -3.0f);
  expect_rctf_near(rf, -3.0f, 5.0f, 0.0f, 1.0f);
  BLI_rctf_union_x(&rf, 1.0f);
  expect_rctf_near(rf, -3.0f, 5.0f, 0.0f, 1.0f);

  BLI_rctf_union_y(&rf, -2.0f);
  BLI_rctf_union_y(&rf, 4.0f);
  expect_rctf_near(rf, -3.0f, 5.0f, -2.0f, 4.0f);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Transformations
 * \{ */

TEST(rect, TranslateAndMul)
{
  rcti ri = {0, 10, 0, 10};
  BLI_rcti_translate(&ri, 3, -2);
  expect_rcti_eq(ri, 3, 13, -2, 8);

  ri = {1, 2, 3, 4};
  BLI_rcti_mul(&ri, 2);
  expect_rcti_eq(ri, 2, 4, 6, 8);
  BLI_rcti_mul(&ri, 0);
  expect_rcti_eq(ri, 0, 0, 0, 0);

  rctf rf = {0.0f, 1.0f, 0.0f, 1.0f};
  BLI_rctf_translate(&rf, -0.5f, 0.25f);
  expect_rctf_near(rf, -0.5f, 0.5f, 0.25f, 1.25f);
  BLI_rctf_mul(&rf, 2.0f);
  expect_rctf_near(rf, -1.0f, 1.0f, 0.5f, 2.5f);
}

TEST(rect, Recenter)
{
  rcti ri = {0, 10, 0, 4};
  BLI_rcti_recenter(&ri, 20, 20);
  expect_rcti_eq(ri, 15, 25, 18, 22);
  EXPECT_EQ(BLI_rcti_size_x(&ri), 10);
  EXPECT_EQ(BLI_rcti_size_y(&ri), 4);

  rctf rf = {0.0f, 10.0f, 0.0f, 4.0f};
  BLI_rctf_recenter(&rf, 0.0f, 0.0f);
  expect_rctf_near(rf, -5.0f, 5.0f, -2.0f, 2.0f);
}

TEST(rect, ResizeRcti)
{
  rcti ri = {0, 10, 0, 10};
  BLI_rcti_resize(&ri, 4, 6);
  expect_rcti_eq(ri, 3, 7, 2, 8);

  /* Odd sizes keep the requested size, the extra unit goes to the max side. */
  ri = {0, 10, 0, 10};
  BLI_rcti_resize_x(&ri, 5);
  expect_rcti_eq(ri, 3, 8, 0, 10);
  EXPECT_EQ(BLI_rcti_size_x(&ri), 5);

  ri = {0, 10, 0, 10};
  BLI_rcti_resize_y(&ri, 20);
  expect_rcti_eq(ri, 0, 10, -5, 15);
}

TEST(rect, ResizeRctf)
{
  rctf rf = {0.0f, 10.0f, 0.0f, 10.0f};
  BLI_rctf_resize(&rf, 4.0f, 6.0f);
  expect_rctf_near(rf, 3.0f, 7.0f, 2.0f, 8.0f);

  rf = {0.0f, 10.0f, 0.0f, 10.0f};
  BLI_rctf_resize_x(&rf, 3.0f);
  expect_rctf_near(rf, 3.5f, 6.5f, 0.0f, 10.0f);

  rf = {0.0f, 10.0f, 0.0f, 10.0f};
  BLI_rctf_resize_y(&rf, 0.0f);
  expect_rctf_near(rf, 0.0f, 10.0f, 5.0f, 5.0f);
  EXPECT_TRUE(BLI_rctf_is_empty(&rf));
}

TEST(rect, Pad)
{
  rcti ri = {0, 10, 0, 10};
  BLI_rcti_pad(&ri, 2, 3);
  expect_rcti_eq(ri, -2, 12, -3, 13);
  /* Negative padding shrinks. */
  BLI_rcti_pad(&ri, -3, -4);
  expect_rcti_eq(ri, 1, 9, 1, 9);

  rctf rf = {0.0f, 1.0f, 0.0f, 1.0f};
  BLI_rctf_pad(&rf, 0.5f, 0.25f);
  expect_rctf_near(rf, -0.5f, 1.5f, -0.25f, 1.25f);
}

TEST(rect, PadY)
{
  /* 10 + 10 pixels of padding out of 100 means padding is 20% of the new height. */
  rctf rf = {0.0f, 1.0f, 0.0f, 10.0f};
  BLI_rctf_pad_y(&rf, 100.0f, 10.0f, 10.0f);
  expect_rctf_near(rf, 0.0f, 1.0f, -1.25f, 11.25f);
  EXPECT_NEAR(2.5f / BLI_rctf_size_y(&rf), 20.0f / 100.0f, 1e-6f);

  /* Asymmetric padding. */
  rf = {0.0f, 1.0f, 0.0f, 10.0f};
  BLI_rctf_pad_y(&rf, 100.0f, 0.0f, 20.0f);
  expect_rctf_near(rf, 0.0f, 1.0f, 0.0f, 12.5f);

  /* No padding is a no-op. */
  rf = {0.0f, 1.0f, 0.0f, 10.0f};
  BLI_rctf_pad_y(&rf, 100.0f, 0.0f, 0.0f);
  expect_rctf_near(rf, 0.0f, 1.0f, 0.0f, 10.0f);
}

TEST(rect, Scale)
{
  rcti ri = {0, 10, 0, 20};
  BLI_rcti_scale(&ri, 2.0f);
  expect_rcti_eq(ri, -5, 15, -10, 30);

  ri = {0, 10, 0, 20};
  BLI_rcti_scale(&ri, 1.0f);
  expect_rcti_eq(ri, 0, 10, 0, 20);

  rctf rf = {0.0f, 10.0f, 0.0f, 20.0f};
  BLI_rctf_scale(&rf, 0.5f);
  expect_rctf_near(rf, 2.5f, 7.5f, 5.0f, 15.0f);

  /* Scaling by zero collapses to the center. */
  rf = {0.0f, 10.0f, 0.0f, 20.0f};
  BLI_rctf_scale(&rf, 0.0f);
  expect_rctf_near(rf, 5.0f, 5.0f, 10.0f, 10.0f);
}

TEST(rect, Interp)
{
  const rctf a = {0.0f, 10.0f, 0.0f, 10.0f};
  const rctf b = {10.0f, 20.0f, 10.0f, 30.0f};
  rctf r;
  BLI_rctf_interp(&r, &a, &b, 0.0f);
  expect_rctf_near(r, 0.0f, 10.0f, 0.0f, 10.0f);
  BLI_rctf_interp(&r, &a, &b, 1.0f);
  expect_rctf_near(r, 10.0f, 20.0f, 10.0f, 30.0f);
  BLI_rctf_interp(&r, &a, &b, 0.5f);
  expect_rctf_near(r, 5.0f, 15.0f, 5.0f, 20.0f);
  /* Extrapolation. */
  BLI_rctf_interp(&r, &a, &b, 2.0f);
  expect_rctf_near(r, 20.0f, 30.0f, 20.0f, 50.0f);
}

TEST(rect, TransformPt)
{
  const rctf src = {0.0f, 10.0f, 0.0f, 10.0f};
  const rctf dst = {100.0f, 200.0f, -1.0f, 1.0f};
  float out[2];

  const float mid[2] = {5.0f, 2.5f};
  BLI_rctf_transform_pt_v(&dst, &src, out, mid);
  EXPECT_FLOAT_EQ(out[0], 150.0f);
  EXPECT_FLOAT_EQ(out[1], -0.5f);

  const float corner[2] = {0.0f, 10.0f};
  BLI_rctf_transform_pt_v(&dst, &src, out, corner);
  EXPECT_FLOAT_EQ(out[0], 100.0f);
  EXPECT_FLOAT_EQ(out[1], 1.0f);

  /* Points outside the source map outside the destination. */
  const float outside[2] = {20.0f, -10.0f};
  BLI_rctf_transform_pt_v(&dst, &src, out, outside);
  EXPECT_FLOAT_EQ(out[0], 300.0f);
  EXPECT_FLOAT_EQ(out[1], -3.0f);
}

TEST(rect, TransformCalcMatrix)
{
  const rctf src = {1.0f, 5.0f, 2.0f, 4.0f};
  const rctf dst = {0.0f, 2.0f, 0.0f, 1.0f};

  float m3[3][3];
  BLI_rctf_transform_calc_m3_pivot_min(&dst, &src, m3);
  const float m3_expect[3][3] = {{2, 0, 0}, {0, 2, 0}, {2, 4, 1}};
  for (int i = 0; i < 3; i++) {
    for (int j = 0; j < 3; j++) {
      EXPECT_FLOAT_EQ(m3[i][j], m3_expect[i][j]) << "m3[" << i << "][" << j << "]";
    }
  }

  float m4[4][4];
  BLI_rctf_transform_calc_m4_pivot_min(&dst, &src, m4);
  const float m4_expect[4][4] = {{2, 0, 0, 0}, {0, 2, 0, 0}, {0, 0, 1, 0}, {2, 4, 0, 1}};
  for (int i = 0; i < 4; i++) {
    for (int j = 0; j < 4; j++) {
      EXPECT_FLOAT_EQ(m4[i][j], m4_expect[i][j]) << "m4[" << i << "][" << j << "]";
    }
  }

  /* Map the rectangle's Y axis onto the matrix Z axis. */
  BLI_rctf_transform_calc_m4_pivot_min_ex(&dst, &src, m4, 0, 2);
  const float m4_ex_expect[4][4] = {{2, 0, 0, 0}, {0, 1, 0, 0}, {0, 0, 2, 0}, {2, 0, 4, 1}};
  for (int i = 0; i < 4; i++) {
    for (int j = 0; j < 4; j++) {
      EXPECT_FLOAT_EQ(m4[i][j], m4_ex_expect[i][j]) << "m4_ex[" << i << "][" << j << "]";
    }
  }
}

TEST(rect, RotateExpand)
{
  const rctf src = {-1.0f, 1.0f, -2.0f, 2.0f};
  rctf dst;

  BLI_rctf_rotate_expand(&dst, &src, 0.0f);
  expect_rctf_near(dst, -1.0f, 1.0f, -2.0f, 2.0f, 1e-5f);

  /* A quarter turn swaps width and height. */
  BLI_rctf_rotate_expand(&dst, &src, float(M_PI_2));
  expect_rctf_near(dst, -2.0f, 2.0f, -1.0f, 1.0f, 1e-5f);

  BLI_rctf_rotate_expand(&dst, &src, float(M_PI));
  expect_rctf_near(dst, -1.0f, 1.0f, -2.0f, 2.0f, 1e-5f);

  /* A unit square rotated 45 degrees has a half-extent of sqrt(2). */
  const rctf square = {-1.0f, 1.0f, -1.0f, 1.0f};
  BLI_rctf_rotate_expand(&dst, &square, float(M_PI_4));
  const float s = float(M_SQRT2);
  expect_rctf_near(dst, -s, s, -s, s, 1e-5f);

  /* The center is preserved for off-origin rectangles. */
  const rctf offset = {9.0f, 11.0f, 18.0f, 22.0f};
  BLI_rctf_rotate_expand(&dst, &offset, float(M_PI_2));
  expect_rctf_near(dst, 8.0f, 12.0f, 19.0f, 21.0f, 1e-5f);
}

TEST(rect, RotateExpandAround)
{
  /* Center (2, 0) rotated a quarter turn around the origin lands on (0, 2). */
  const rctf src = {1.0f, 3.0f, -1.0f, 1.0f};
  const float pivot[2] = {0.0f, 0.0f};
  rctf dst;
  BLI_rctf_rotate_expand_around(&dst, &src, pivot, float(M_PI_2));
  expect_rctf_near(dst, -1.0f, 1.0f, 1.0f, 3.0f, 1e-5f);

  /* Rotating around the rectangle's own center matches #BLI_rctf_rotate_expand. */
  const float own_center[2] = {2.0f, 0.0f};
  rctf dst_expand;
  BLI_rctf_rotate_expand_around(&dst, &src, own_center, 0.3f);
  BLI_rctf_rotate_expand(&dst_expand, &src, 0.3f);
  EXPECT_TRUE(BLI_rctf_compare(&dst, &dst_expand, 1e-5f));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Clamping
 * \{ */

TEST(rect, ClampPt)
{
  const rcti ri = {0, 10, 0, 10};
  int pt_i[2] = {5, 5};
  EXPECT_FALSE(BLI_rcti_clamp_pt_v(&ri, pt_i));
  EXPECT_EQ(pt_i[0], 5);
  EXPECT_EQ(pt_i[1], 5);

  int pt_i_out[2] = {-3, 12};
  EXPECT_TRUE(BLI_rcti_clamp_pt_v(&ri, pt_i_out));
  EXPECT_EQ(pt_i_out[0], 0);
  EXPECT_EQ(pt_i_out[1], 10);

  const rctf rf = {0.0f, 1.0f, 0.0f, 1.0f};
  float pt_f[2] = {1.5f, -0.5f};
  EXPECT_TRUE(BLI_rctf_clamp_pt_v(&rf, pt_f));
  EXPECT_FLOAT_EQ(pt_f[0], 1.0f);
  EXPECT_FLOAT_EQ(pt_f[1], 0.0f);

  /* Points on the boundary are not changed. */
  float pt_edge[2] = {1.0f, 0.0f};
  EXPECT_FALSE(BLI_rctf_clamp_pt_v(&rf, pt_edge));
}

TEST(rect, ClampRect)
{
  const rcti bounds = {0, 10, 0, 10};
  int ofs[2];

  rcti ri = {2, 4, 2, 4};
  EXPECT_FALSE(BLI_rcti_clamp(&ri, &bounds, ofs));
  expect_rcti_eq(ri, 2, 4, 2, 4);
  EXPECT_EQ(ofs[0], 0);
  EXPECT_EQ(ofs[1], 0);

  ri = {8, 12, -2, 2};
  EXPECT_TRUE(BLI_rcti_clamp(&ri, &bounds, ofs));
  expect_rcti_eq(ri, 6, 10, 0, 4);
  EXPECT_EQ(ofs[0], -2);
  EXPECT_EQ(ofs[1], 2);

  /* A rectangle larger than the bounds keeps the top-left corner (X-min, Y-max) inside. */
  ri = {-5, 15, -5, 15};
  EXPECT_TRUE(BLI_rcti_clamp(&ri, &bounds, ofs));
  expect_rcti_eq(ri, 0, 20, -10, 10);
  EXPECT_EQ(ofs[0], 5);
  EXPECT_EQ(ofs[1], -5);

  const rctf bounds_f = {0.0f, 1.0f, 0.0f, 1.0f};
  float ofs_f[2];
  rctf rf = {-0.25f, 0.25f, 0.5f, 1.5f};
  EXPECT_TRUE(BLI_rctf_clamp(&rf, &bounds_f, ofs_f));
  expect_rctf_near(rf, 0.0f, 0.5f, 0.0f, 1.0f);
  EXPECT_FLOAT_EQ(ofs_f[0], 0.25f);
  EXPECT_FLOAT_EQ(ofs_f[1], -0.5f);
}

TEST(rect, ClampSegment)
{
  const rctf rf = {0.0f, 10.0f, 0.0f, 10.0f};

  /* Both points inside: unchanged. */
  float s1[2] = {1.0f, 2.0f}, s2[2] = {3.0f, 4.0f};
  EXPECT_TRUE(BLI_rctf_clamp_segment(&rf, s1, s2));
  EXPECT_FLOAT_EQ(s1[0], 1.0f);
  EXPECT_FLOAT_EQ(s1[1], 2.0f);
  EXPECT_FLOAT_EQ(s2[0], 3.0f);
  EXPECT_FLOAT_EQ(s2[1], 4.0f);

  /* Second point outside on the right: clamped to the right edge. */
  float a1[2] = {5.0f, 5.0f}, a2[2] = {15.0f, 5.0f};
  EXPECT_TRUE(BLI_rctf_clamp_segment(&rf, a1, a2));
  EXPECT_FLOAT_EQ(a1[0], 5.0f);
  EXPECT_FLOAT_EQ(a1[1], 5.0f);
  EXPECT_NEAR(a2[0], 10.0f, 1e-5f);
  EXPECT_NEAR(a2[1], 5.0f, 1e-5f);

  /* First point outside below: clamped to the bottom edge. */
  float b1[2] = {4.0f, -6.0f}, b2[2] = {4.0f, 4.0f};
  EXPECT_TRUE(BLI_rctf_clamp_segment(&rf, b1, b2));
  EXPECT_NEAR(b1[0], 4.0f, 1e-5f);
  EXPECT_NEAR(b1[1], 0.0f, 1e-5f);
  EXPECT_FLOAT_EQ(b2[0], 4.0f);
  EXPECT_FLOAT_EQ(b2[1], 4.0f);

  /* Diagonal exit through the top-right area. */
  float c1[2] = {5.0f, 5.0f}, c2[2] = {15.0f, 10.0f};
  EXPECT_TRUE(BLI_rctf_clamp_segment(&rf, c1, c2));
  EXPECT_NEAR(c2[0], 10.0f, 1e-5f);
  EXPECT_NEAR(c2[1], 7.5f, 1e-5f);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Comparison & Conversion
 * \{ */

TEST(rect, Compare)
{
  const rcti a = {0, 1, 2, 3};
  const rcti b = {0, 1, 2, 3};
  const rcti c = {0, 1, 2, 4};
  EXPECT_TRUE(BLI_rcti_compare(&a, &b));
  EXPECT_FALSE(BLI_rcti_compare(&a, &c));

  const rctf af = {0.0f, 1.0f, 0.0f, 1.0f};
  const rctf bf = {0.05f, 1.0f, 0.0f, 1.0f};
  const rctf cf = {0.0f, 1.0f, 0.0f, 1.2f};
  EXPECT_TRUE(BLI_rctf_compare(&af, &af, 0.0f));
  EXPECT_TRUE(BLI_rctf_compare(&af, &bf, 0.1f));
  EXPECT_FALSE(BLI_rctf_compare(&af, &bf, 0.01f));
  EXPECT_FALSE(BLI_rctf_compare(&af, &cf, 0.1f));
}

TEST(rect, CopyConversions)
{
  const rcti ri = {1, 2, 3, 4};
  rctf rf;
  BLI_rctf_rcti_copy(&rf, &ri);
  expect_rctf_near(rf, 1.0f, 2.0f, 3.0f, 4.0f);

  const rctf src = {-0.5f, 1.75f, 2.25f, 3.5f};
  rcti dst;
  BLI_rcti_rctf_copy_floor(&dst, &src);
  expect_rcti_eq(dst, -1, 1, 2, 3);
  BLI_rcti_rctf_copy_round(&dst, &src);
  expect_rcti_eq(dst, 0, 2, 2, 4);
}

TEST(rect, CopyPreservesSize)
{
  /* #BLI_rcti_rctf_copy rounds the size, independently rounding each edge may not. */
  const rctf src = {0.5f, 1.25f, 0.0f, 2.0f};
  rcti dst;
  BLI_rcti_rctf_copy(&dst, &src);
  expect_rcti_eq(dst, 1, 2, 0, 2);
  EXPECT_EQ(BLI_rcti_size_x(&dst), 1);

  BLI_rcti_rctf_copy_round(&dst, &src);
  expect_rcti_eq(dst, 1, 1, 0, 2);
  EXPECT_EQ(BLI_rcti_size_x(&dst), 0);
}

/** \} */

}  // namespace blender::tests
