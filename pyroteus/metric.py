"""
Driver functions for metric-based mesh adaptation.
"""
from __future__ import absolute_import
from .utility import *
from . import kernel as kernels


__all__ = ["metric_complexity", "isotropic_metric", "hessian_metric", "enforce_element_constraints",
           "space_normalise", "space_time_normalise",
           "metric_relaxation", "metric_average", "metric_intersection", "combine_metrics",
           "density_and_quotients", "check_spd"]


# --- General

def metric_complexity(metric, boundary=False):
    """
    Compute the complexity of a metric.

    This is the continuous analogue of the
    (discrete) mesh vertex count.

    :kwarg boundary: compute metric on domain
        interior or boundary?
    """
    differential = ds if boundary else dx
    return assemble(sqrt(det(metric))*differential)


def isotropic_metric(error_indicator, target_space=None, f_min=1.0e-12):
    r"""
    Compute an isotropic metric from some error indicator.

    The result is a :math:`\mathbb P1` diagonal tensor
    field whose entries are projections of the error
    indicator in modulus.

    :arg error_indicator: the error indicator
    :kwarg target_space: :class:`TensorFunctionSpace` in
        which the metric will exist
    :kwarg f_min: minimum tolerated function value
    """
    fs = error_indicator.function_space()
    family = fs.ufl_element().family()
    degree = fs.ufl_element().degree()
    mesh = fs.mesh()
    dim = mesh.topological_dimension()
    assert dim in (2, 3), f"Spatial dimension {dim:d} not supported."
    target_space = target_space or TensorFunctionSpace(mesh, "CG", 1)
    assert target_space.ufl_element().family() == 'Lagrange'
    assert target_space.ufl_element().degree() == 1

    # Compute metric diagonal
    if family == 'Lagrange' and degree == 1:
        M_diag = interpolate(max_value(abs(error_indicator), f_min), fs)
    else:
        M_diag = project(error_indicator, FunctionSpace(mesh, "CG", 1))
        M_diag.interpolate(max_value(abs(M_diag), f_min))

    # Assemble full metric
    return interpolate(M_diag*Identity(dim), target_space)


def hessian_metric(hessian):
    """
    Modify the eigenvalues of a Hessian matrix so
    that it is positive-definite.

    :arg hessian: the Hessian matrix
    """
    fs = hessian.function_space()
    mesh = fs.mesh()
    dim = mesh.topological_dimension()
    if fs.ufl_element().value_shape() != (dim, dim):
        raise ValueError(
            f"Expected {(dim,dim)} tensor field, "
            + f"got {fs.ufl_element().value_shape()}."
        )
    metric = Function(fs)
    kernel = kernels.eigen_kernel(kernels.metric_from_hessian, dim)
    op2.par_loop(kernel, fs.node_set, metric.dat(op2.RW), hessian.dat(op2.READ))
    return metric


def anisotropic_metric(error_indicator, hessian, target_space=None, **kwargs):
    r"""
    Compute an anisotropic metric from some error
    indicator, given a Hessian field.

    The formulation used is based on that presented
    in [Carpio et al. 2013].

    Whilst an element-based formulation is used to
    derive the metric, the result is projected into
    :math:`\mathbb P1` space, by default.

    Note that normalisation is implicit in the metric
    construction and involves the `convergence_rate`
    parameter, named :math:`alpha` in [Carpio et al. 2013].

    :arg error_indicator: the error indicator
    :arg hessian: the Hessian
    :kwarg target_space: :class:`TensorFunctionSpace` in
        which the metric will exist
    :kwarg target_complexity: target metric complexity
    :kwarg convergence rate: normalisation parameter

    [Carpio et al. 2013] J Carpio, JL Prieto, R Bermejo,
        'Anisotropic goal-oriented mesh adaptivity for
        elliptic problems', SIAM Journal on Scientific
        Computing, 2013.
    """
    target_complexity = kwargs.get('target_complexity', None)
    assert target_complexity > 0.0, "Target complexity must be positive"
    convergence_rate = kwargs.get('convergence_rate', 1.0)
    assert convergence_rate >= 1.0, "Convergence rate must be at least one"
    mesh = hessian.function_space().mesh()
    dim = mesh.topological_dimension()
    assert dim in (2, 3), f"Spatial dimension {dim:d} not supported."

    # Get current element volume
    P0 = FunctionSpace(mesh, "DG", 0)
    K_hat = 1/2 if dim == 2 else 1/3
    K = interpolate(K_hat*abs(JacobianDeterminant(mesh)), P0)

    # Get optimal element volume
    K_opt = interpolate(pow(error_indicator, 1/(convergence_rate+1)), P0)
    K_opt.interpolate(K.opt.vector().gather().sum()/target_complexity*K/K_opt)

    # Compute eigendecomposition
    P0_ten = TensorFunctionSpace(mesh, "DG", 0)
    P0_vec = VectorFunctionSpace(mesh, "DG", 0)
    P0_metric = hessian_metric(project(hessian, P0_ten))
    evectors, evalues = Function(P0_ten), Function(P0_vec)
    kernel = kernels.eigen_kernel(kernels.get_reordered_eigendecomposition, dim)
    op2.par_loop(
        kernel, P0_ten.node_set,
        evectors.dat(op2.RW), evalues.dat(op2.RW), P0_metric.dat(op2.READ)
    )

    # Compute stretching factors, in descending order
    if dim == 2:
        S = as_vector([
            sqrt(abs(evalues[0]/evalues[1])),
            sqrt(abs(evalues[1]/evalues[0])),
        ])
    else:
        S = as_vector([
            pow(abs((evalues[0]*evalues[0])/(evalues[1]*evalues[2])), 1/3),
            pow(abs((evalues[1]*evalues[1])/(evalues[2]*evalues[0])), 1/3),
            pow(abs((evalues[2]*evalues[2])/(evalues[0]*evalues[1])), 1/3),
        ])

    # Assemble metric
    evalues.interpolate(abs(K_hat/K_opt)*S)
    kernel = kernels.eigen_kernel(kernels.set_eigendecomposition, dim)
    op2.par_loop(
        kernel, P0_ten.node_set, P0_metric.dat(op2.RW),
        evectors.dat(op2.READ), evalues.dat(op2.READ)
    )

    # Project metric into target space and ensure SPD
    target_space = target_space or TensorFunctionSpace(mesh, "CG", 1)
    return hessian_metric(project(P0_metric, target_space))


def enforce_element_constraints(metrics, h_min, h_max, a_max=1000):
    """
    Post-process a list of metrics to enforce minimum and maximum
    element sizes, as well as maximum anisotropy.

    :arg metrics: the metrics
    :arg h_min: minimum tolerated element size.
    :arg h_max: maximum tolerated element size.
    :kwarg a_max: maximum tolerated element anisotropy (default 1000).
    """
    if not (0 < h_min < h_max):
        raise ValueError(
            f"Min/max tolerated element sizes {h_min}/{h_max} not valid"
        )
    if a_max <= 0:
        raise ValueError(f"Max tolerated anisotropy {a_max} not valid")
    for metric in [metrics] if isinstance(metrics, Function) else metrics:
        fs = metric.function_space()
        dim = fs.mesh().topological_dimension()
        kernel = kernels.eigen_kernel(kernels.postproc_metric, dim, h_min, h_max, a_max)
        op2.par_loop(kernel, fs.node_set, metric.dat(op2.RW))
    return metrics


# --- Normalisation


def space_normalise(metric, target, p):
    """
    Apply L-p normalisation in space alone.

    :arg metric: class:`Function`s corresponding to the
        metric to be normalised.
    :arg target: target metric complexity *in space alone*.
    :arg p: normalisation order.
    """
    assert p == 'inf' or p >= 1.0, f"Norm order {p} not valid"
    d = metric.function_space().mesh().topological_dimension()

    # Compute global normalisation factor
    detM = det(metric)
    integral = assemble(sqrt(detM)*dx if p == 'inf' else pow(detM, p/(2*p + d))*dx)
    global_norm = Constant(pow(target/integral, 2/d))

    # Normalise
    determinant = 1 if p == 'inf' else pow(det(metric), -1/(2*p + d))
    metric.interpolate(global_norm*determinant*metric)
    return metric


def space_time_normalise(metrics, end_time, timesteps, target, p):
    """
    Apply L-p normalisation is both space and time.

    :arg metrics: list of :class:`Function`s corresponding
        to the metric associated with each subinterval
    :arg end_time: end time of simulation
    :arg timesteps: list of timesteps specified in each subinterval
    :arg target: target *space-time* metric complexity
    :arg p: normalisation order
    """
    # NOTE: Assumes uniform subinterval lengths
    assert p == 'inf' or p >= 1.0, f"Norm order {p} not valid"
    num_subintervals = len(metrics)
    assert len(timesteps) == num_subintervals
    dt_per_mesh = [end_time/num_subintervals/dt for dt in timesteps]
    d = metrics[0].function_space().mesh().topological_dimension()

    # Compute global normalisation factor
    integral = 0
    for metric, tau in zip(metrics, dt_per_mesh):
        detM = det(metric)
        integral += assemble(tau*sqrt(detM)*dx if p == 'inf' else pow(tau**2*detM, p/(2*p + d))*dx)
    global_norm = Constant(pow(target/integral, 2/d))

    # Normalise on each subinterval
    for metric, tau in zip(metrics, dt_per_mesh):
        determinant = 1 if p == 'inf' else pow(tau**2*det(metric), -1/(2*p + d))
        metric.interpolate(global_norm*determinant*metric)
    return metrics


# --- Combination

def metric_relaxation(*metrics, weights=None, function_space=None):
    """
    Combine a list of metrics with a weighted average.

    :args metrics: the metrics to be combined
    :kwarg weights: a list of weights
    :kwarg function_space: the :class:`FunctionSpace`
        the relaxed metric should live in
    """
    n = len(metrics)
    assert n > 0, "Nothing to combine"
    weights = weights or np.ones(n)/n
    if len(weights) != n:
        raise ValueError(
            "Number of weights do not match number of metrics"
            + f"({len(weights)} vs. {n})")
    fs = function_space or metrics[0].function_space()
    relaxed_metric = Function(fs)
    for weight, metric in zip(weights, metrics):
        if not isinstance(metric, Function) or metric.function_space() != fs:
            metric = interpolate(metric, function_space)
        relaxed_metric += weight*metric
    return relaxed_metric


def metric_average(*metrics, function_space=None):
    """
    Combine a list of metrics by averaging.

    :args metrics: the metrics to be combined
    :kwarg function_space: the :class:`FunctionSpace`
        the averaged metric should live in
    """
    return metric_relaxation(*metrics, function_space=function_space)


def metric_intersection(*metrics, function_space=None, boundary_tag=None):
    """
    Combine a list of metrics by intersection.

    :args metrics: the metrics to be combined
    :kwarg function_space: the :class:`FunctionSpace`
        the intersected metric should live in
    :kwarg boundary_tag: boundary segment physical
        ID for boundary intersection
    """
    n = len(metrics)
    assert n > 0, "Nothing to combine"
    fs = function_space or metrics[0].function_space()
    for metric in metrics:
        if not isinstance(metric, Function) or metric.function_space() != fs:
            metric = interpolate(metric, function_space)
    intersected_metric = Function(metrics[0])
    node_set = fs.node_set if boundary_tag is None else DirichletBC(fs, 0, boundary_tag).node_set
    dim = fs.mesh().topological_dimension()
    assert dim in (2, 3), f"Spatial dimension {dim:d} not supported."

    def intersect_pair(M1, M2):
        M12 = Function(M1)
        kernel = kernels.eigen_kernel(kernels.intersect, dim)
        op2.par_loop(kernel, node_set, M12.dat(op2.RW), M1.dat(op2.READ), M2.dat(op2.READ))
        return M12

    for metric in metrics[1:]:
        intersected_metric = intersect_pair(intersected_metric, metric)
    return intersected_metric


def combine_metrics(*metrics, average=True, **kwargs):
    """
    Combine a list of metrics.

    :kwarg average: combination by averaging or intersection?
    """
    if average:
        kwargs.pop('boundary_tag')
        return metric_relaxation(*metrics, **kwargs)
    else:
        kwargs.pop('weights')
        return metric_intersection(*metrics, **kwargs)


# --- Metric decompositions and properties


def density_and_quotients(metric, reorder=False):
    r"""
    Extract the density and anisotropy quotients from a metric.

    By symmetry, Riemannian metrics admit an orthogonal
    eigendecomposition,

  ..math::
        \underline{\mathbf M}(\mathbf x)
        = \underline{\mathbf V}(\mathbf x)\:
        \underline{\boldsymbol\Lambda}(\mathbf x)\:
        \underline{\mathbf V}(\mathbf x)^T,

    at each point :math:`\mathbf x\in\Omega`, where
    :math:`\underline{\mathbf V}` and
    :math:`\underline{\boldsymbol\Sigma}` are matrices holding
    the eigenvectors and eigenvalues, respectively. By
    positive-definiteness, entries of
    :math:`\underline{\boldsymbol\Lambda}` are all positive.

    An alternative decomposition,

  ..math::
        \underline{\mathbf M}(\mathbf x)
        = d(\mathbf x)^\frac2n
        \underline{\mathbf V}(\mathbf x)\:
        \underline{\mathbf R}(\mathbf x)^{-\frac2n}
        \underline{\mathbf V}(\mathbf x)^T

    can also be deduced, in terms of the <em>metric density</em>
    and <em>anisotropy quotients</em>,

  ..math::
        d = \sum_{i=1}^n h_i,\quad
        r_i = h_i^n/d,\quad \forall i=1:n,

    where :math:`h_i := \frac1{\sqrt{\lambda_i}}`.

    :arg metric: the metric to extract density and quotients from
    :kwarg reorder: should the eigendecomposition be reordered?
    """
    fs_ten = metric.function_space()
    mesh = fs_ten.mesh()
    fe = (fs_ten.ufl_element().family(), fs_ten.ufl_element().degree())
    fs_vec = VectorFunctionSpace(mesh, *fe)
    fs = FunctionSpace(mesh, *fe)
    dim = mesh.topological_dimension()

    # Setup fields
    evectors = Function(fs_ten)
    evalues = Function(fs_vec)
    density = Function(fs, name="Metric density")
    quotients = Function(fs_vec, name="Anisotropic quotients")

    # Compute eigendecomposition
    if reorder:
        kernel = kernels.eigen_kernel(kernels.get_reordered_eigendecomposition, dim)
    else:
        kernel = kernels.eigen_kernel(kernels.get_eigendecomposition, dim)
    op2.par_loop(kernel, fs_ten.node_set,
                 evectors.dat(op2.RW), evalues.dat(op2.RW), metric.dat(op2.READ))

    # Extract density and quotients
    h = [1/sqrt(evalues[i]) for i in range(dim)]
    density.interpolate(1/prod(h))
    quotients.interpolate(as_vector([density*h[i]**dim for i in range(dim)]))
    return density, quotients


def is_symmetric(M, rtol=1.0e-08):
    """
    Determine whether a tensor field is symmetric.

    :arg M: the tensor field
    :kwarg rtol: relative tolerance for the test
    """
    err = assemble(abs(det(M - transpose(M)))*dx)
    return err/assemble(abs(det(M))*dx) < rtol


def is_pos_def(M):
    """
    Determine whether a tensor field is positive-definite.

    :arg M: the tensor field
    """
    fs = M.function_space()
    fs_vec = VectorFunctionSpace(fs.mesh(), fs.ufl_element().family(), fs.ufl_element().degree())
    evectors = Function(fs)
    evalues = Function(fs_vec)
    kernel = kernels.eigen_kernel(kernels.get_eigendecomposition, fs.mesh().topological_dimension())
    op2.par_loop(kernel, fs.node_set, evectors.dat(op2.RW), evalues.dat(op2.RW), M.dat(op2.READ))
    return evalues.vector().gather().min() > 0.0


def is_spd(M):
    """
    Determine whether a tensor field is symmetric positive-definite.

    :arg M: the tensor field
    """
    return is_symmetric(M) and is_pos_def(M)


def check_spd(M):
    """
    Verify that a tensor field is symmetric positive-definite.

    :arg M: the tensor field
    """
    try:
        assert is_symmetric(M)
    except AssertionError:
        raise ValueError("FAIL: Matrix is not symmetric")
    try:
        assert is_pos_def(M)
    except AssertionError:
        raise ValueError("FAIL: Matrix is not positive-definite")
