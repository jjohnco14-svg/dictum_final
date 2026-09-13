#ifndef GEOM_H
#define GEOM_H

typedef struct {
    float x;
    float y;
} Point2D;

float point_distance(Point2D a, Point2D b);
Point2D point_midpoint(Point2D a, Point2D b);
int get_status(int code, int *out_severity);

#endif
