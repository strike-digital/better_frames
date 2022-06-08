layout (triangles) in;
layout (triangle_strip, max_vertices = 6) out;

in vec2 Pos[];
flat in vec2 P1[];
flat in vec2 P2[];
flat in vec2 P3[];
flat in vec2 P4[];

flat out int isShadow;
out vec2 pos;
flat out vec2 inP1;
flat out vec2 inP2;
flat out vec2 inP3;
flat out vec2 inP4;

void main() {
    // loop through all points twice, and output them the same the first time, and the second time with an offset
    for (int i = 0; i < 2; i++) {
        for (int j = 0; j < 3; j++) {
            pos = Pos[j];
            inP1 = P1[j];
            inP2 = P2[j];
            inP3 = P3[j];
            inP4 = P4[j];
            vec4 offset;
            if (i > 0) {
                isShadow = 0;
                offset = vec4(0);
            } else {
                isShadow = 1;
                offset = vec4(0.0, -0.0, 0, 0);
            }
            gl_Position = gl_in[j].gl_Position + offset;
            EmitVertex();
        }
        EndPrimitive();
    }
    // EndPrimitive();
}