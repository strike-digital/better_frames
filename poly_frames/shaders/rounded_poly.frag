#version 330
uniform vec4 color;
uniform vec2 center;
uniform float radius = .2;
uniform float line_width = 1.;
uniform bool is_active;
uniform bool is_selected;

in vec2 pos;
flat in int isShadow;
flat in vec2 inP1;
flat in vec2 inP2;
flat in vec2 inP3;
flat in vec2 inP4;

// A shader to draw a polygon with rounded corners.
// I have no idea if this is the best way to do this, but it works.
// To work, the shader must be passed the four nearest points to the current tri.

out vec4 fragColor;

float dot2(in vec2 v) {
  return dot(v, v);
}
float cro(in vec2 a, in vec2 b) {
  return a.x * b.y - a.y * b.x;
}

// Signed distance to a quadratic bezier written by the amazing Inigo Quilez.
// I have no idea how it works, and I think my mental health is better off for it.
// https://www.shadertoy.com/view/MlKcDD
float sdBezier(in vec2 pos, in vec2 A, in vec2 B, in vec2 C) {
  vec2 a = B - A;
  vec2 b = A - 2.0 * B + C;
  vec2 c = a * 2.0;
  vec2 d = A - pos;

  float kk = 1.0 / dot(b, b);
  float kx = kk * dot(a, b);
  float ky = kk * (2.0 * dot(a, a) + dot(d, b)) / 3.0;
  float kz = kk * dot(d, a);

  float res = 0.0;
  float sgn = 0.0;

  float p = ky - kx * kx;
  float q = kx * (2.0 * kx * kx - 3.0 * ky) + kz;
  float p3 = p * p * p;
  float q2 = q * q;
  float h = q2 + 4.0 * p3;

  if (h >= 0.0) {   // 1 root
    h = sqrt(h);
    vec2 x = (vec2(h, -h) - q) / 2.0;

    vec2 uv = sign(x) * pow(abs(x), vec2(1.0 / 3.0));
    float t = clamp(uv.x + uv.y - kx, 0.0, 1.0);
    vec2 q = d + (c + b * t) * t;
    res = dot2(q);
    sgn = cro(c + 2.0 * b * t, q);
  } else {   // 3 roots
    float z = sqrt(-p);
    float v = acos(q / (p * z * 2.0)) / 3.0;
    float m = cos(v);
    float n = sin(v) * 1.732050808;
    vec3 t = clamp(vec3(m + m, -n - m, n - m) * z - kx, 0.0, 1.0);
    vec2 qx = d + (c + b * t.x) * t.x;
    float dx = dot2(qx), sx = cro(c + 2.0 * b * t.x, qx);
    vec2 qy = d + (c + b * t.y) * t.y;
    float dy = dot2(qy), sy = cro(c + 2.0 * b * t.y, qy);
    if (dx < dy) {
      res = dx;
      sgn = sx;
    } else {
      res = dy;
      sgn = sy;
    }
  }

  return sqrt(res) * sign(sgn);
}


// Distance to a line segment, also by Inigo Quilez.
// https://www.shadertoy.com/view/3tdSDj
float sdSegment(in vec2 p, in vec2 a, in vec2 b) {
  vec2 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}

float[2] sdCorners(in vec2 pos, in float radius, in vec2 inP1, in vec2 inP2, in vec2 inP3, in vec2 inP4){
  // Calculate the signed distance to the first rounded corner.
  vec2 p1 = mix(inP1, inP2, radius);
  vec2 p3 = mix(inP3, inP2, radius);
  float dist1 = sdBezier(pos, p1, inP2, p3);

  // Calculate the signed distance to the second rounded corner.
  vec2 p2 = mix(inP2, inP3, radius);
  vec2 p4 = mix(inP4, inP3, radius);
  float dist2 = sdBezier(pos, p2, inP3, p4);

  float signed_dist = max(dist1, dist2); // The signed distance where points inside the polygon are negative.
  float edge_dist = sdSegment(pos, p2, p3); // The distance to the straight edges between the corners.
  float dist = min(edge_dist, min(abs(dist1), abs(dist2))); // The absolute distance to the edge
  return float[2](signed_dist, dist);
}

// This works by using bezier interpolation between adjascent points to create curved corners.
void main()
{
  // Remap the radius of the corners to the correct range.
  float radius = 1. - (radius / 2 + 0.0001);

  // Scale everything in slightly to prevent clipping on the edges of polys.
  float scale_offset = 1 + 0.01;
  vec2 pos = (pos - center) * 1.5 + center;

  float[2] distances = sdCorners(pos, radius, inP1, inP2, inP3, inP4);
  float signed_dist = distances[0];
  float dist = distances[1];

  if (isShadow == 1) {
    vec2 to_center = normalize(pos - center);
    vec2 direction = normalize(vec2(1, -1.5));
    fragColor = mix(vec4(0, 0, 0, .4), vec4(0), smoothstep(0, 1, dist / 10)); // Generate a shadow on all sides
    fragColor = mix(vec4(0.0), fragColor, clamp(dot(to_center, direction) + 0.2, 0, 1)); // Remove that shadow on the top left side
    return;
  }

  // Colour the inside of the polygon, and discard the outside
  fragColor = mix(vec4(0), color, int(signed_dist < 0.));

  vec4 edge_col = vec4(0, 0, 0, 1);
  if (is_active) {
    edge_col = vec4(1);
  } else if (is_selected) {
    edge_col = vec4(0.846874, 0.299308, 0., 1.);
  }
  // Draw a border around the edges
  vec4 other = edge_col;
  other.a = 0;
  vec4 outline = mix(edge_col, other, smoothstep(0, 1, dist/line_width));
  fragColor = mix(fragColor, outline, outline.a);

  #if 0
  fragColor += vec4(0, 0, 0, .8); // Show the full polygon for debugging
  #endif
  #if 1
  // Draw the centers of the polygons
  fragColor += vec4(clamp(1-length(pos - center)/10, 0, 1));
  #endif
  
  fragColor = blender_srgb_to_framebuffer_space(fragColor);
}