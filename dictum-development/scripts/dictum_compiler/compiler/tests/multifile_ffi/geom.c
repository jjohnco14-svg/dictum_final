#include "geom.h"
#include <math.h>

float point_distance(Point2D a, Point2D b) {
    float dx = a.x - b.x;
    float dy = a.y - b.y;
    return sqrtf(dx*dx + dy*dy);
}

Point2D point_midpoint(Point2D a, Point2D b) {
    Point2D r;
    r.x = (a.x + b.x) / 2.0f;
    r.y = (a.y + b.y) / 2.0f;
    return r;
}

int get_status(int code, int *out_severity) {
    *out_severity = code % 3;
    return code * 2;
}
