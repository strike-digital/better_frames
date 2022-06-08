#version 330
uniform mat4 ModelViewProjectionMatrix;
uniform vec2 center;

in vec2 pos;
in vec2 p1;
in vec2 p2;
in vec2 p3;
in vec2 p4;

out vec2 Pos;
flat out vec2 P1;
flat out vec2 P2;
flat out vec2 P3;
flat out vec2 P4;

void main() {
  vec2 main_pos = (pos - center) * 1.5 + center;
  gl_Position = ModelViewProjectionMatrix * vec4(main_pos, 0.0, 1.0);
  Pos = pos;

  P1 = p1;
  P2 = p2;
  P3 = p3;
  P4 = p4;
}