"""
Problem specification for a simple steady
state flow-past-a-cylinder test case which
solves a Stokes problem.

The test case is notable for Pyroteus
because the prognostic equation is
nonlinear.

Code here is based on that found at
    https://nbviewer.jupyter.org/github/firedrakeproject/firedrake/blob/master/docs/notebooks/06-pde-constrained-optimisation.ipynb
"""
from firedrake import *
import os
from pyroteus.runge_kutta import SteadyState


mesh = Mesh(os.path.join(os.path.dirname(__file__), "mesh-with-hole.msh"))
fields = ["up"]
dt = 20.0
end_time = dt
dt_per_export = 1
num_subintervals = 1
steady = True
tableau = SteadyState


def get_function_spaces(mesh):
    r"""
    Taylor-Hood :math:`\mathbb P2-\mathbb P1` space.
    """
    return {'up': VectorFunctionSpace(mesh, "CG", 2)*FunctionSpace(mesh, "CG", 1)}


def get_solver(self):
    """
    Stokes problem solved using a
    direct method.
    """
    def solver(i, ic):
        W = self.function_spaces['up'][i]

        # Assign initial condition
        up = Function(W, name='up_old')
        up.assign(ic['up'])

        # Define inflow
        x, y = SpatialCoordinate(self[i])
        u_inflow = as_vector([y*(10-y)/25.0, 0])

        # Define viscosity
        nu = Constant(1)

        # Specify boundary conditions
        noslip = DirichletBC(W.sub(0), (0, 0), (3, 5))
        inflow = DirichletBC(W.sub(0), interpolate(u_inflow, W.sub(0)), 1)
        bcs = [inflow, noslip, DirichletBC(W.sub(0), 0, 4)]

        # Define variational problem
        u, p = split(up)
        v, q = TestFunctions(W)
        F = inner(dot(u, nabla_grad(u)), v)*dx \
            + nu*inner(grad(u), grad(v))*dx \
            - inner(p, div(v))*dx \
            - inner(q, div(u))*dx

        # Solve
        solve(F == 0, up, bcs=bcs, solver_parameters={
            "mat_type": "aij",
            "snes_type": "newtonls",
            "snes_monitor": None,
            "ksp_type": "preonly",
            "pc_type": "lu",
            "pc_factor_shift_type": "inblocks",
        }, ad_block_tag='up')

        return {'up': up}

    return solver


def get_initial_condition(self):
    """
    Dummy initial condition function which
    acts merely to pass over the
    :class:`FunctionSpace`.
    """
    x, y = SpatialCoordinate(self[0])
    u_inflow = as_vector([y*(10-y)/25.0, 0])
    up = Function(self.function_spaces['up'][0])
    u, p = up.split()
    u.interpolate(u_inflow)
    return {'up': up}


def get_qoi(self, i):
    """
    Quantity of interest which integrates
    pressure over the boundary of the hole.
    """
    def steady_qoi(sol):
        u, p = sol['up'].split()
        return p*ds(4)

    return steady_qoi
