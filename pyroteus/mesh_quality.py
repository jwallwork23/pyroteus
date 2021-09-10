from pyroteus.kernel import *
from firedrake import *


def get_min_angles2d(mesh, python=False):
    """
    Computes the minimum angle of each cell in a 2D triangular mesh

    :arg mesh: the input mesh to do computations on
    :kwarg python: compute the measure using Python?

    :rtype: firedrake.function.Function min_angles with
    minimum angle data
    """
    P0 = FunctionSpace(mesh, "DG", 0)
    if python:
        raise NotImplementedError
    else:
        coords = mesh.coordinates
        min_angles = Function(P0)
        kernel = eigen_kernel(get_min_angle2d)
        op2.par_loop(kernel, mesh.cell_set, min_angles.dat(op2.WRITE, min_angles.cell_node_map()),
                     coords.dat(op2.READ, coords.cell_node_map()))
    return min_angles


def get_areas2d(mesh, python=False):
    """
    Computes the area of each cell in a 2D triangular mesh

    :arg mesh: the input mesh to do computations on
    :kwarg python: compute the measure using Python?

    :rtype: firedrake.function.Function areas with
    area data
    """
    P0 = FunctionSpace(mesh, "DG", 0)
    if python:
        areas = interpolate(CellVolume(mesh), P0)
    else:
        coords = mesh.coordinates
        areas = Function(P0)
        kernel = eigen_kernel(get_area2d)
        op2.par_loop(kernel, mesh.cell_set, areas.dat(op2.WRITE, areas.cell_node_map()),
                     coords.dat(op2.READ, coords.cell_node_map()))
    return areas


def get_aspect_ratios2d(mesh, python=False):
    """
    Computes the aspect ratio of each cell in a 2D triangular mesh

    :arg mesh: the input mesh to do computations on
    :kwarg python: compute the measure using Python?

    :rtype: firedrake.function.Function aspect_ratios with
    aspect ratio data
    """
    P0 = FunctionSpace(mesh, "DG", 0)
    if python:
        P0_ten = TensorFunctionSpace(mesh, "DG", 0)
        J = interpolate(Jacobian(mesh), P0_ten)
        edge1 = as_vector([J[0, 0], J[1, 0]])
        edge2 = as_vector([J[0, 1], J[1, 1]])
        edge3 = edge1 - edge2
        a = sqrt(dot(edge1, edge1))
        b = sqrt(dot(edge2, edge2))
        c = sqrt(dot(edge3, edge3))
        aspect_ratios = interpolate(a*b*c/((a+b-c)*(b+c-a)*(c+a-b)), P0)
    else:
        coords = mesh.coordinates
        aspect_ratios = Function(P0)
        kernel = eigen_kernel(get_aspect_ratio2d)
        op2.par_loop(kernel, mesh.cell_set, aspect_ratios.dat(op2.WRITE, aspect_ratios.cell_node_map()),
                     coords.dat(op2.READ, coords.cell_node_map()))
    return aspect_ratios


def get_eskews2d(mesh, python=False):
    """
    Computes the equiangle skew of each cell in a 2D triangular mesh

    :arg mesh: the input mesh to do computations on
    :kwarg python: compute the measure using Python?

    :rtype: firedrake.function.Function eskews with equiangle skew
    data.
    """
    P0 = FunctionSpace(mesh, "DG", 0)
    if python:
        raise NotImplementedError
    else:
        coords = mesh.coordinates
        eskews = Function(P0)
        kernel = eigen_kernel(get_eskew2d)
        op2.par_loop(kernel, mesh.cell_set, eskews.dat(op2.WRITE, eskews.cell_node_map()),
                     coords.dat(op2.READ, coords.cell_node_map()))
    return eskews


def get_skewnesses2d(mesh, python=False):
    """
    Computes the skewness of each cell in a 2D triangular mesh

    :arg mesh: the input mesh to do computations on
    :kwarg python: compute the measure using Python?

    :rtype: firedrake.function.Function skews with skewness
    data.
    """
    P0 = FunctionSpace(mesh, "DG", 0)
    if python:
        raise NotImplementedError
    else:
        coords = mesh.coordinates
        skews = Function(P0)
        kernel = eigen_kernel(get_skewness2d)
        op2.par_loop(kernel, mesh.cell_set, skews.dat(op2.WRITE, skews.cell_node_map()),
                     coords.dat(op2.READ, coords.cell_node_map()))
    return skews


def get_scaled_jacobians2d(mesh, python=False):
    """
    Computes the scaled Jacobian of each cell in a 2D triangular mesh

    :arg mesh: the input mesh to do computations on
    :kwarg python: compute the measure using Python?

    :rtype: firedrake.function.Function scaled_jacobians with scaled
    jacobian data.
    """
    P0 = FunctionSpace(mesh, "DG", 0)
    if python:
        P0_ten = TensorFunctionSpace(mesh, "DG", 0)
        J = interpolate(Jacobian(mesh), P0_ten)
        edge1 = as_vector([J[0, 0], J[1, 0]])
        edge2 = as_vector([J[0, 1], J[1, 1]])
        edge3 = edge1 - edge2
        a = sqrt(dot(edge1, edge1))
        b = sqrt(dot(edge2, edge2))
        c = sqrt(dot(edge3, edge3))
        detJ = JacobianDeterminant(mesh)
        jacobian_sign = sign(detJ)
        max_product = Max(Max(Max(a*b, a*c), Max(b*c, b*a)), Max(c*a, c*b))
        scaled_jacobians = interpolate(detJ/max_product*jacobian_sign, P0)
    else:
        coords = mesh.coordinates
        scaled_jacobians = Function(P0)
        kernel = eigen_kernel(get_scaled_jacobian2d)
        op2.par_loop(kernel, mesh.cell_set, scaled_jacobians.dat(op2.WRITE, scaled_jacobians.cell_node_map()),
                     coords.dat(op2.READ, coords.cell_node_map()))
    return scaled_jacobians


def get_quality_metrics2d(mesh, M, python=False):
    """
    Given a matrix M, a linear function in 2 dimensions, this function
    outputs the value of the Quality metric Q_M based on the
    transformation encoded in M.

    :arg mesh: the input mesh to do computations on
    :arg M: the (2 x 2) matrix representing the metric space transformation
    :kwarg python: compute the measure using Python?

    :rtype: firedrake.function.Function metrics with metric data.
    """
    P0 = FunctionSpace(mesh, "DG", 0)
    if python:
        raise NotImplementedError
    else:
        P1_ten = TensorFunctionSpace(mesh, "CG", 1)
        coords = mesh.coordinates
        tensor = interpolate(as_matrix(M), P1_ten)
        metrics = Function(P0)
        kernel = eigen_kernel(get_metric2d)
        op2.par_loop(kernel, mesh.cell_set, metrics.dat(op2.WRITE, metrics.cell_node_map()),
                     tensor.dat(op2.READ, tensor.cell_node_map()),
                     coords.dat(op2.READ, coords.cell_node_map()))
    return metrics


if __name__ == "__main__":
    mesh = UnitSquareMesh(4, 4)
    mesh.coordinates.dat.data[:] += np.random.rand(*mesh.coordinates.dat.data.shape)
    f = get_aspect_ratios2d
    q = np.array(f(mesh).dat.data, dtype=float)
    qp = np.array(f(mesh, python=True).dat.data, dtype=float)
    print(q)
    print(qp)
    print(np.allclose(q, qp))
