"""
Test matrix decomposition par_loops.
"""
from firedrake import *
from firedrake.meshadapt import RiemannianMetric
from pyroteus import *
from utility import uniform_mesh
import pytest


# ---------------------------
# standard tests for pytest
# ---------------------------


@pytest.fixture(params=[2, 3])
def dim(request):
    return request.param


@pytest.fixture(params=[True, False])
def reorder(request):
    return request.param


@pytest.mark.slow
def test_eigendecomposition(dim, reorder):
    """
    Check decomposition of a metric into its eigenvectors
    and eigenvalues.

      * The eigenvectors should be orthonormal.
      * Applying `compute_eigendecomposition` followed by
        `set_eigendecomposition` should get back the metric.
    """
    mesh = uniform_mesh(dim, 1)

    # Create a simple metric
    P1_ten = TensorFunctionSpace(mesh, "CG", 1)
    metric = RiemannianMetric(P1_ten)
    mat = [[1, 0], [0, 2]] if dim == 2 else [[1, 0, 0], [0, 2, 0], [0, 0, 3]]
    metric.interpolate(as_matrix(mat))

    # Extract the eigendecomposition
    evectors, evalues = compute_eigendecomposition(metric, reorder=reorder)

    # Check eigenvectors are orthonormal
    err = Function(P1_ten)
    err.interpolate(dot(evectors, transpose(evectors)) - Identity(dim))
    if not np.isclose(norm(err), 0.0):
        raise ValueError(f"Eigenvectors are not orthonormal: {evectors.dat.data}")

    # Check eigenvalues are in descending order
    if reorder:
        P1 = FunctionSpace(mesh, "CG", 1)
        for i in range(dim - 1):
            f = interpolate(evalues[i], P1)
            f -= interpolate(evalues[i + 1], P1)
            if f.vector().gather().min() < 0.0:
                raise ValueError(
                    f"Eigenvalues are not in descending order: {evalues.dat.data}"
                )

    # Reassemble it and check the two match
    metric -= assemble_eigendecomposition(evectors, evalues)
    if not np.isclose(norm(metric), 0.0):
        raise ValueError(f"Reassembled metric does not match. Error: {metric.dat.data}")


def test_density_quotients_decomposition(dim, reorder):
    """
    Check decomposition of a metric into its density
    and anisotropy quotients.

    Reassembling should get back the metric.
    """
    mesh = uniform_mesh(dim, 1)

    # Create a simple metric
    P1_ten = TensorFunctionSpace(mesh, "CG", 1)
    metric = RiemannianMetric(P1_ten)
    mat = [[1, 0], [0, 2]] if dim == 2 else [[1, 0, 0], [0, 2, 0], [0, 0, 3]]
    metric.interpolate(as_matrix(mat))

    # Extract the density, anisotropy quotients and eigenvectors
    density, quotients, evectors = density_and_quotients(metric, reorder=reorder)
    quotients.interpolate(as_vector([pow(density / Q, 2 / dim) for Q in quotients]))

    # Reassemble the matrix and check the two match
    metric -= assemble_eigendecomposition(evectors, quotients)
    if not np.isclose(norm(metric), 0.0):
        raise ValueError(f"Reassembled metric does not match. Error: {metric.dat.data}")
