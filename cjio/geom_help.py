import math

import numpy as np

MODULE_TRIANGLE_AVAILABLE = True
try:
    import triangle
except ImportError:
    MODULE_TRIANGLE_AVAILABLE = False

MODULE_EARCUT_AVAILABLE = True
try:
    import mapbox_earcut
except ImportError:
    MODULE_EARCUT_AVAILABLE = False


def to_2d(p, n):
    # -- n must be normalised
    # p = np.array([1, 2, 3])
    # newell = np.array([1, 3, 4.2])
    # n = newell/math.sqrt(p[0]*p[0] + p[1]*p[1] + p[2]*p[2])
    x3 = np.array([1.1, 1.1, 1.1])  # -- is this always a good value??
    if (n == x3).all():
        x3 += np.array([1, 2, 3])
    x3 = x3 - np.dot(x3, n) * n
    # print(n, x3)
    x3 /= math.sqrt((x3**2).sum())  # make x a unit vector
    y3 = np.cross(n, x3)
    return (np.dot(p, x3), np.dot(p, y3))


def get_normal_newell(poly):
    """
    Compute the normal vector of a polygon using Newell's method.
    """
    n = np.array([0.0, 0.0, 0.0], dtype=np.float64)

    for i, p in enumerate(poly):
        if len(p) < 3:  # -- if it does not have 3 points then skip
            continue
        ne = i + 1
        if ne == len(poly):
            ne = 0
        n[0] += (poly[i][1] - poly[ne][1]) * (poly[i][2] + poly[ne][2])
        n[1] += (poly[i][2] - poly[ne][2]) * (poly[i][0] + poly[ne][0])
        n[2] += (poly[i][0] - poly[ne][0]) * (poly[i][1] + poly[ne][1])

    if (n == np.array([0.0, 0.0, 0.0])).all():
        # print("one wrong")
        return (n, False)
    n = n / math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
    return (n, True)


def triangulate_face(face, vnp, sloppy=False):
    if not sloppy:
        return triangulate_face_shewchuk(face, vnp)
    else:
        return triangulate_face_mapbox_earcut(face, vnp)


##-- with Shewchuk Triangle library
def triangulate_face_shewchuk(face, vnp):
    # print(face)
    # -- remove duplicate vertices, which can *easily* make Triangle segfault
    for i, each in enumerate(face):
        if len(set(each)) < len(each):  # -- there are duplicates
            re = []
            for k in each:
                if re.count(k) == 0:
                    re.append(k)
            face[i] = re
    # print(face)
    # print(len(face))
    if (len(face) == 1) and (len(face[0]) <= 3):
        if len(face[0]) == 3:
            # -- if a triangle then do nothing
            return (np.array(face), True)
        else:
            # -- if collapsed then ignore and return false
            return (np.array(face), False)

    for i, ring in enumerate(face):
        if len(ring) < 3:
            # -- if a triangle then do nothing
            return (np.zeros(1), False)
    sf = np.array([], dtype=np.int64)
    for ring in face:
        sf = np.hstack((sf, np.array(ring)))
    sfv = vnp[sf]

    rings = np.zeros(len(face), dtype=np.int64)
    total = 0
    for i in range(len(face)):
        total += len(face[i])
        rings[i] = total

    # 1. normal with Newell's method
    n, b = get_normal_newell(sfv)

    # 2. project to the plane to get xy
    sfv2d = np.zeros((sfv.shape[0], 2))
    for i, p in enumerate(sfv):
        xy = to_2d(p, n)
        sfv2d[i][0] = xy[0]
        sfv2d[i][1] = xy[1]

    # -- 3. deal with segments/constraints, prepare the Triangle input
    sg = np.zeros((rings[-1], 2), dtype=np.int64)
    for i, e in enumerate(sg):
        sg[i][0] = i
        sg[i][1] = i + 1
    starti = 0
    for each in rings:
        sg[each - 1][1] = starti
        starti = each
    # -- deal with holes
    if len(rings) > 1:
        holes = np.zeros((len(rings) - 1, 2))
        for k in range(len(rings) - 1):
            # -- basically triangulate the Triangle the Ring, and find the centre
            # -- of mass of the first triangle
            a = sfv2d[rings[k] : rings[k + 1]]
            sg1 = np.zeros((a.shape[0], 2), dtype=np.int64)
            for i, e in enumerate(sg1):
                sg1[i][0] = i
                sg1[i][1] = i + 1
            sg1[-1][1] = 0
            pcl = dict(vertices=a, segments=sg1)
            trl = triangle.triangulate(pcl, "p")
            t = trl["triangles"][0]
            c = np.average(a[t], axis=0)  # -- find its centre of mass
            holes[k][0] = c[0]
            holes[k][1] = c[1]
        A = dict(vertices=sfv2d, segments=sg, holes=holes)
    else:
        A = dict(vertices=sfv2d, segments=sg)

    try:
        re = triangle.triangulate(A, "p")
    except Exception as e:
        print(e)
        print("Houston we have a problem...")
        # re = {}
        return (np.array(face), False)
    # -- check the output
    if "triangles" not in re:
        return ([], False)
    re = re["triangles"]
    for i, each in enumerate(re):
        try:
            re[i] = sf[each]
        except Exception as exp:
            print(exp)
            return (re, False)
    return (re, True)


def triangulate_face_mapbox_earcut(face, vnp):
    sf = np.array([], dtype=np.int64)
    if (len(face) == 1) and (len(face[0]) == 3):
        return (np.array(face), True)
    for ring in face:
        sf = np.hstack((sf, np.array(ring)))
    sfv = vnp[sf]
    # print(sf)
    # print(sfv)
    rings = np.zeros(len(face), dtype=np.int32)
    total = 0
    for i in range(len(face)):
        total += len(face[i])
        rings[i] = total
    # print(rings)

    # 1. normal with Newell's method
    n, b = get_normal_newell(sfv)

    # -- if already a triangle then return it
    if not b:
        return (n, False)
    # print ("Newell:", n)

    # 2. project to the plane to get xy
    sfv2d = np.zeros((sfv.shape[0], 2))
    # print (sfv2d)
    for i, p in enumerate(sfv):
        xy = to_2d(p, n)
        # print("xy", xy)
        sfv2d[i][0] = xy[0]
        sfv2d[i][1] = xy[1]
    result = mapbox_earcut.triangulate_float64(sfv2d, rings)
    # print (result.reshape(-1, 3))

    for i, each in enumerate(result):
        # print (sf[i])
        result[i] = sf[each]

    # print (result.reshape(-1, 3))
    return (result.reshape(-1, 3), True)


def triangle_normal(tri, vertexlist, weighted=False):
    """Compute the triangle normal vector weighted by the triangle area.

    Returns None if the normal vector cannot be computed (mostly because the triangle
    is degenerate).
    """
    v0, v1, v2 = tri[0], tri[1], tri[2]
    p0 = np.array((vertexlist[v0][0], vertexlist[v0][1], vertexlist[v0][2]))
    p1 = np.array((vertexlist[v1][0], vertexlist[v1][1], vertexlist[v1][2]))
    p2 = np.array((vertexlist[v2][0], vertexlist[v2][1], vertexlist[v2][2]))
    cross_prod = np.cross(p1 - p0, p2 - p0)
    magnitude = np.linalg.norm(cross_prod)
    if math.isclose(magnitude, 0.0):
        return None
    else:
        norm_vec = cross_prod / magnitude
        if not weighted:
            return norm_vec
        else:
            tri_area = magnitude * 0.5
            return norm_vec * tri_area


def average_normal(normals):
    """Compute the smooth (average) normal vector from a list of vectors.
    Returns a numpy array of [x,y,z]. If the normal cannot be computed, then it returns
    a fake normal of [1.0, 0.0, 0.0].
    """
    s = sum(normals)
    n = np.linalg.norm(s)
    if math.isclose(n, 0.0):
        # Set a fake normal if length of the sum of normals is
        # 0. Can happen with opposite vectors.
        normal_vec = np.array([1.0, 0.0, 0.0])
    else:
        normal_vec = s / n
    return normal_vec
