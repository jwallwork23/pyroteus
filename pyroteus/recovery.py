"""
Driver functions for derivative recovery.
"""
from __future__ import absolute_import
from .interpolation import clement_interpolant
from .utility import *


__all__ = ["recover_hessian", "recover_boundary_hessian"]


def recover_hessian(f, method='L2', **kwargs):
    """
    Recover the Hessian of a scalar field.

    :arg f: the scalar field whose Hessian we seek to recover
    :kwarg method: recovery method
    """
    if method.upper() == 'L2':
        g, H = double_l2_projection(f, **kwargs)
    elif method.capitalize() == 'Clement':
        mesh = kwargs.get('mesh') or f.function_space().mesh()
        g = clement_interpolant(interpolate(grad(f), VectorFunctionSpace(mesh, "DG", 0)))
        H = clement_interpolant(interpolate(grad(g), TensorFunctionSpace(mesh, "DG", 0)))
    elif method.upper() == 'ZZ':
        raise NotImplementedError("Zienkiewicz-Zhu recovery not yet implemented.")  # TODO
    else:
        raise ValueError(f"Recovery method '{method}' not recognised.")
    return H


@PETSc.Log.EventDecorator("pyroteus.double_l2_projection")
def double_l2_projection(f, mesh=None, target_spaces=None, mixed=False):
    r"""
    Recover the gradient and Hessian of a scalar field using a
    double :math:`L^2` projection.

    :arg f: the scalar field whose derivatives we seek to recover
    :kwarg mesh: the underlying mesh
    :kwarg target_spaces: the :class:`VectorFunctionSpace` and
        :class:`TensorFunctionSpace` the recovered gradient and
        Hessian should live in
    :kwarg mixed: solve as a mixed system, or separately?
    """
    mesh = mesh or f.function_space().mesh()
    if target_spaces is None:
        P1_vec = VectorFunctionSpace(mesh, "CG", 1)
        P1_ten = TensorFunctionSpace(mesh, "CG", 1)
    else:
        P1_vec, P1_ten = target_spaces
    if not mixed:
        g = project(grad(f), P1_vec)
        H = project(grad(g), P1_ten)
        return g, H
    W = P1_vec*P1_ten
    g, H = TrialFunctions(W)
    phi, tau = TestFunctions(W)
    l2_projection = Function(W)
    n = FacetNormal(mesh)

    # The formulation is chosen such that f does not need to have any
    # finite element derivatives
    a = inner(tau, H)*dx + inner(div(tau), g)*dx - dot(g, dot(tau, n))*ds
    a += inner(phi, g)*dx
    L = f*dot(phi, n)*ds - f*div(phi)*dx

    # Apply stationary preconditioners in the Schur complement to get away
    # with applying GMRES to the whole mixed system
    sp = {
        "mat_type": "aij",
        "ksp_type": "gmres",
        "ksp_max_it": 20,
        "pc_type": "fieldsplit",
        "pc_fieldsplit_type": "schur",
        "pc_fieldsplit_0_fields": "1",
        "pc_fieldsplit_1_fields": "0",
        "pc_fieldsplit_schur_precondition": "selfp",
        "fieldsplit_0_ksp_type": "preonly",
        "fieldsplit_1_ksp_type": "preonly",
        "fieldsplit_1_pc_type": "gamg",
        "fieldsplit_1_mg_levels_ksp_max_it": 5,
    }
    if COMM_WORLD.size == 1:
        sp["fieldsplit_0_pc_type"] = "ilu"
        sp["fieldsplit_1_mg_levels_pc_type"] = "ilu"
    else:
        sp["fieldsplit_0_pc_type"] = "bjacobi"
        sp["fieldsplit_0_sub_ksp_type"] = "preonly"
        sp["fieldsplit_0_sub_pc_type"] = "ilu"
        sp["fieldsplit_1_mg_levels_pc_type"] = "bjacobi"
        sp["fieldsplit_1_mg_levels_sub_ksp_type"] = "preonly"
        sp["fieldsplit_1_mg_levels_sub_pc_type"] = "ilu"
    try:
        solve(a == L, l2_projection, solver_parameters=sp)
    except ConvergenceError:
        PETSc.Sys.Print("L2 projection failed to converge with"
                        " iterative solver parameters, trying direct.")
        sp = {"pc_mat_factor_solver_type": "mumps"}
        solve(a == L, l2_projection, solver_parameters=sp)
    return l2_projection.split()


@PETSc.Log.EventDecorator("pyroteus.recovery_boundary_hessian")
def recover_boundary_hessian(f, mesh, method='Clement', target_space=None, **kwargs):
    """
    Recover the Hessian of a scalar field
    on the domain boundary.

    :arg f: dictionary of boundary tags and corresponding
        fields, which we seek to recover, as well as an
        'interior' entry for the domain interior
    :arg mesh: the mesh
    :kwarg method: choose from 'L2' and 'Clement'
    :kwarg target_space: :class:`TensorFunctionSpace` in
        which the metric will exist
    """
    from pyroteus.math import construct_orthonormal_basis
    from pyroteus.metric import hessian_metric

    d = mesh.topological_dimension()
    assert d in (2, 3)

    # Apply Gram-Schmidt to get tangent vectors
    n = FacetNormal(mesh)
    s = construct_orthonormal_basis(n)
    ns = as_vector([n, *s])

    # Setup
    P1 = FunctionSpace(mesh, "CG", 1)
    P1_ten = target_space or TensorFunctionSpace(mesh, "CG", 1)
    assert P1_ten.ufl_element().family() == 'Lagrange'
    assert P1_ten.ufl_element().degree() == 1
    boundary_tag = kwargs.get('boundary_tag', 'on_boundary')
    Hs, v = TrialFunction(P1), TestFunction(P1)
    l2_proj = [[Function(P1) for i in range(d-1)] for j in range(d-1)]
    h = interpolate(CellSize(mesh), FunctionSpace(mesh, "DG", 0))
    h = Constant(1/h.vector().gather().max()**2)
    f.pop('interior')
    sp = {
        "ksp_type": "gmres",
        "ksp_gmres_restart": 20,
        "ksp_rtol": 1.0e-05,
        "pc_type": "sor",
    }

    if method.upper() == 'L2':

        # Arbitrary value on domain interior
        a = v*Hs*dx
        L = v*h*dx

        # Hessian on boundary
        nullspace = VectorSpaceBasis(constant=True)
        for j, s1 in enumerate(s):
            for i, s0 in enumerate(s):
                bcs = []
                for tag, fi in f.items():
                    a_bc = v*Hs*ds(tag)
                    L_bc = -dot(s0, grad(v))*dot(s1, grad(fi))*ds(tag)
                    bcs.append(EquationBC(a_bc == L_bc, l2_proj[i][j], tag))
                solve(a == L, l2_proj[i][j], bcs=bcs,
                      nullspace=nullspace, solver_parameters=sp)

    elif method.capitalize() == 'Clement':
        P0_vec = VectorFunctionSpace(mesh, "DG", 0)
        P0_ten = TensorFunctionSpace(mesh, "DG", 0)
        P1_vec = VectorFunctionSpace(mesh, "CG", 1)
        H = Function(P1_ten)
        p0test = TestFunction(P0_vec)
        p1test = TestFunction(P1)
        fa = get_facet_areas(mesh)
        for tag, fi in f.items():
            source = assemble(inner(p0test, grad(fi))/fa*ds)

            # Recover gradient
            c = clement_interpolant(source, boundary_tag=tag, target_space=P1_vec)

            # Recover Hessian
            H += clement_interpolant(interpolate(grad(c), P0_ten),
                                     boundary_tag=tag, target_space=P1_ten)

        # Compute tangential components
        for j, s1 in enumerate(s):
            for i, s0 in enumerate(s):
                l2_proj[i][j] = assemble(p1test*dot(dot(s0, H), s1)/fa*ds)
    else:
        raise ValueError(f"Recovery method '{method}' not supported"
                         " for Hessians on the boundary.")

    # Construct tensor field
    Hbar = Function(P1_ten)
    if d == 2:
        Hsub = interpolate(abs(l2_proj[0][0]), P1)
        H = as_matrix([[h, 0],
                       [0, Hsub]])
    else:
        Hsub = Function(TensorFunctionSpace(mesh, "CG", 1, shape=(2, 2)))
        Hsub.interpolate(as_matrix([[l2_proj[0][0], l2_proj[0][1]],
                                    [l2_proj[1][0], l2_proj[1][1]]]))
        Hsub = hessian_metric(Hsub)
        H = as_matrix([[h, 0, 0],
                       [0, Hsub[0, 0], Hsub[0, 1]],
                       [0, Hsub[1, 0], Hsub[1, 1]]])

    # Arbitrary value on domain interior
    sigma, tau = TrialFunction(P1_ten), TestFunction(P1_ten)
    a = inner(tau, sigma)*dx
    L = inner(tau, h*Identity(d))*dx

    # Boundary values imposed as in [Loseille et al. 2011]
    a_bc = inner(tau, sigma)*ds
    L_bc = inner(tau, dot(transpose(ns), dot(H, ns)))*ds
    bcs = EquationBC(a_bc == L_bc, Hbar, boundary_tag)
    solve(a == L, Hbar, bcs=bcs, solver_parameters=sp)
    return Hbar
