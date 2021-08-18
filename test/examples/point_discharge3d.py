"""
Problem specification for a simple
advection-diffusion test case with a
point source. Extended from
[Riadh et al. 2014] as in
[Wallwork et al. 2020].

This test case is notable for Pyroteus
because it is in 3D and has an
analytical solution, meaning the
effectivity index can be computed.

[Riadh et al. 2014] A. Riadh, G.
    Cedric, M. Jean, "TELEMAC modeling
    system: 2D hydrodynamics TELEMAC-2D
    software release 7.0 user manual."
    Paris: R&D, Electricite de France,
    p. 134 (2014).

[Wallwork et al. 2020] J.G. Wallwork,
    N. Barral, D.A. Ham, M.D. Piggott,
    "Anisotropic Goal-Oriented Mesh
    Adaptation in Firedrake". In:
    Proceedings of the 28th International
    Meshing Roundtable (2020).
"""
from firedrake import *
from point_discharge2d import bessi0, bessk0
from pyroteus.runge_kutta import SteadyState


# Problem setup
n = 0
mesh = BoxMesh(100*2**n, 20*2**n, 20*2**n, 50, 10, 10)
fields = ['tracer_3d']
end_time = 20.0
dt = 20.0
dt_per_export = 1
src_x, src_y, src_z, src_r = 2.0, 5.0, 5.0, 6.51537538e-02
rec_x, rec_y, rec_z, rec_r = 20.0, 7.5, 7.5, 0.5
steady = True
tableau = SteadyState()


def get_function_spaces(mesh):
    r"""
    :math:`\mathbb P1` space.
    """
    return {'tracer_3d': FunctionSpace(mesh, "CG", 1)}


def source(mesh):
    """
    Gaussian approximation to a point source
    at (2, 5, 5) with discharge rate 100 on a
    given mesh.
    """
    x, y, z = SpatialCoordinate(mesh)
    return 100.0*exp(-((x - src_x)**2 + (y - src_y)**2 + (z - src_z)**2)/src_r**2)


def get_solver(self):
    """
    Advection-diffusion equation
    solved using a direct method.
    """
    def solver(i, ic):
        fs = self.function_spaces['tracer_3d'][i]
        D = Constant(0.1)
        u = Constant(as_vector([1.0, 0.0, 0.0]))
        n = FacetNormal(self[i])
        h = CellSize(self[i])
        S = source(self[i])

        # Ensure dependence on initial condition
        c = Function(fs, name='tracer_3d_old')
        c.assign(ic['tracer_3d'])

        # Stabilisation parameter
        unorm = sqrt(dot(u, u))
        tau = 0.5*h/unorm
        tau = min_value(tau, unorm*h/(6*D))

        # Setup variational problem
        psi = TestFunction(fs)
        psi = psi + tau*dot(u, grad(psi))
        F = S*psi*dx \
            - dot(u, grad(c))*psi*dx \
            - inner(D*grad(c), grad(psi))*dx
        bc = DirichletBC(fs, 0, 1)

        # Solve
        sp = {
            'mat_type': 'aij',
            'snes_type': 'ksponly',
            'ksp_type': 'preonly',
            'pc_type': 'lu',
            'pc_factor_mat_solver_type': 'mumps',
        }
        solve(F == 0, c, bcs=bc, solver_parameters=sp, ad_block_tag='tracer_3d')
        return {'tracer_3d': c}

    return solver


def get_initial_condition(self):
    """
    Dummy initial condition function which
    acts merely to pass over the
    :class:`FunctionSpace`.
    """
    return {'tracer_3d': Function(self.function_spaces['tracer_3d'][0])}


def get_qoi(self, i):
    """
    Quantity of interest which integrates
    the tracer concentration over an offset
    receiver region.
    """
    def steady_qoi(sol):
        c = sol['tracer_3d']
        x, y, z = SpatialCoordinate(self[i])
        kernel = conditional((x - rec_x)**2 + (y - rec_y)**2 + (z - rec_z)**2 < rec_r**2, 1, 0)
        area = assemble(kernel*dx)
        area_analytical = pi*rec_r**2
        scaling = 1.0 if np.allclose(area, 0.0) else area_analytical/area
        return scaling*kernel*c*dx

    return steady_qoi

def analytical_solution(mesh):
    """
    Analytical solution as represented on
    a given mesh.
    """
    x, y, z = SpatialCoordinate(mesh)
    u = Constant(1.0)
    D = Constant(0.1)
    Pe = 0.5*u/D
    r = max_value(sqrt((x - src_x)**2 + (y - src_y)**2 + (z - src_z)**2), src_r)
    return 0.5/(pi*D)*exp(Pe*(x - src_x))*bessk0(Pe*r)
