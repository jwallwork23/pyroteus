from firedrake import op2
import os

try:
    from firedrake.slate.slac.compiler import PETSC_ARCH
except ImportError:
    PETSC_ARCH = os.path.join(os.environ.get('PETSC_DIR'), os.environ.get('PETSC_ARCH'))
include_dir = ["%s/include/eigen3" % PETSC_ARCH]


def eigen_kernel(kernel, *args, **kwargs):
    """
    Helper function to easily pass Eigen kernels to Firedrake via PyOP2.
    """
    return op2.Kernel(kernel(*args, **kwargs), kernel.__name__, cpp=True, include_dirs=include_dir)


def postproc_metric(d, a_max):
    """
    Post-process a metric field in order to enforce
    max/min element sizes and anisotropy.

    :arg d: spatial dimension
    :arg a_max: maximum element anisotropy
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

void postproc_metric(double A_[%d], const double * h_min_, const double * h_max_)
{

  // Map input/output metric onto an Eigen object and map h_min/h_max to doubles
  Map<Matrix<double, %d, %d, RowMajor> > A((double *)A_);
  double h_min = *h_min_;
  double h_max = *h_max_;

  // Solve eigenvalue problem
  SelfAdjointEigenSolver<Matrix<double, %d, %d, RowMajor>> eigensolver(A);
  Matrix<double, %d, %d, RowMajor> Q = eigensolver.eigenvectors();
  Vector%dd D = eigensolver.eigenvalues();

  // Scale eigenvalues appropriately
  int i;
  double max_eig = 0.0;
  for (i=0; i<%d; i++) {
    D(i) = fmin(pow(h_min, -2), fmax(pow(h_max, -2), abs(D(i))));
    max_eig = fmax(max_eig, D(i));
  }
  for (i=0; i<%d; i++) D(i) = fmax(D(i), pow(%f, -2) * max_eig);

  // Build metric from eigendecomposition
  A = Q * D.asDiagonal() * Q.transpose();
}
""" % (d*d, d, d, d, d, d, d, d, d, d, a_max)


def intersect(d):
    """
    Intersect two metric fields.

    :arg d: spatial dimension
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

void intersect(double M_[%d], const double * A_, const double * B_) {

  // Map inputs and outputs onto Eigen objects
  Map<Matrix<double, %d, %d, RowMajor> > M((double *)M_);
  Map<Matrix<double, %d, %d, RowMajor> > A((double *)A_);
  Map<Matrix<double, %d, %d, RowMajor> > B((double *)B_);

  // Solve eigenvalue problem of first metric, taking square root of eigenvalues
  SelfAdjointEigenSolver<Matrix<double, %d, %d, RowMajor>> eigensolver(A);
  Matrix<double, %d, %d, RowMajor> Q = eigensolver.eigenvectors();
  Matrix<double, %d, %d, RowMajor> D = eigensolver.eigenvalues().array().sqrt().matrix().asDiagonal();

  // Compute square root and inverse square root metrics
  Matrix<double, %d, %d, RowMajor> Sq = Q * D * Q.transpose();
  Matrix<double, %d, %d, RowMajor> Sqi = Q * D.inverse() * Q.transpose();

  // Solve eigenvalue problem for triple product of inverse square root metric and the second metric
  SelfAdjointEigenSolver<Matrix<double, %d, %d, RowMajor>> eigensolver2(Sqi.transpose() * B * Sqi);
  Q = eigensolver2.eigenvectors();
  D = eigensolver2.eigenvalues().array().max(1).matrix().asDiagonal();

  // Compute metric intersection
  M = Sq.transpose() * Q * D * Q.transpose() * Sq;
}
""" % (d*d, d, d, d, d, d, d, d, d, d, d, d, d, d, d, d, d, d, d)


def get_eigendecomposition(d):
    """
    Extract eigenvectors/eigenvalues from a metric field.

    :arg d: spatial dimension
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

void get_eigendecomposition(double EVecs_[%d], double EVals_[%d], const double * M_) {

  // Map inputs and outputs onto Eigen objects
  Map<Matrix<double, %d, %d, RowMajor> > EVecs((double *)EVecs_);
  Map<Vector%dd> EVals((double *)EVals_);
  Map<Matrix<double, %d, %d, RowMajor> > M((double *)M_);

  // Solve eigenvalue problem
  SelfAdjointEigenSolver<Matrix<double, %d, %d, RowMajor>> eigensolver(M);
  EVecs = eigensolver.eigenvectors();
  EVals = eigensolver.eigenvalues();
}
""" % (d*d, d, d, d, d, d, d, d, d)


def get_reordered_eigendecomposition(d):
    """
    Extract eigenvectors/eigenvalues from a metric field, with eigenvalues
    **decreasing** in magnitude.
    """
    assert d in (2, 3), f"Spatial dimension {d:d} not supported."
    if d == 2:
        return """
#include <Eigen/Dense>

using namespace Eigen;

void get_reordered_eigendecomposition(double EVecs_[4], double EVals_[2], const double * M_) {

  // Map inputs and outputs onto Eigen objects
  Map<Matrix<double, 2, 2, RowMajor> > EVecs((double *)EVecs_);
  Map<Vector2d> EVals((double *)EVals_);
  Map<Matrix<double, 2, 2, RowMajor> > M((double *)M_);

  // Solve eigenvalue problem
  SelfAdjointEigenSolver<Matrix<double, 2, 2, RowMajor>> eigensolver(M);
  Matrix<double, 2, 2, RowMajor> Q = eigensolver.eigenvectors();
  Vector2d D = eigensolver.eigenvalues();

  // Reorder eigenpairs by magnitude of eigenvalue
  if (fabs(D(0)) > fabs(D(1))) {
    EVecs = Q;
    EVals = D;
  } else {
    EVecs(0,0) = Q(0,1);EVecs(0,1) = Q(0,0);
    EVecs(1,0) = Q(1,1);EVecs(1,1) = Q(1,0);
    EVals(0) = D(1);
    EVals(1) = D(0);
  }
}
"""
    else:
        return """
#include <Eigen/Dense>

using namespace Eigen;

void get_reordered_eigendecomposition(double EVecs_[9], double EVals_[3], const double * M_) {

  // Map inputs and outputs onto Eigen objects
  Map<Matrix<double, 3, 3, RowMajor> > EVecs((double *)EVecs_);
  Map<Vector3d> EVals((double *)EVals_);
  Map<Matrix<double, 3, 3, RowMajor> > M((double *)M_);

  // Solve eigenvalue problem
  SelfAdjointEigenSolver<Matrix<double, 3, 3, RowMajor>> eigensolver(M);
  Matrix<double, 3, 3, RowMajor> Q = eigensolver.eigenvectors();
  Vector3d D = eigensolver.eigenvalues();

  // Reorder eigenpairs by magnitude of eigenvalue
  if (fabs(D(0)) > fabs(D(1))) {
    if (fabs(D(1)) > fabs(D(2))) {
      EVecs = Q;
      EVals = D;
    } else if (fabs(D(0)) > fabs(D(2))) {
      EVecs(0,0) = Q(0,0);EVecs(0,1) = Q(0,2);EVecs(0,2) = Q(0,1);
      EVecs(1,0) = Q(1,0);EVecs(1,1) = Q(1,2);EVecs(1,2) = Q(1,1);
      EVecs(2,0) = Q(2,0);EVecs(2,1) = Q(2,2);EVecs(2,2) = Q(2,1);
      EVals(0) = D(0);
      EVals(1) = D(2);
      EVals(2) = D(1);
    } else {
      EVecs(0,0) = Q(0,2);EVecs(0,1) = Q(0,0);EVecs(0,2) = Q(0,1);
      EVecs(1,0) = Q(1,2);EVecs(1,1) = Q(1,0);EVecs(1,2) = Q(1,1);
      EVecs(2,0) = Q(2,2);EVecs(2,1) = Q(2,0);EVecs(2,2) = Q(2,1);
      EVals(0) = D(2);
      EVals(1) = D(0);
      EVals(2) = D(1);
    }
  } else {
    if (fabs(D(0)) > fabs(D(2))) {
      EVecs(0,0) = Q(0,1);EVecs(0,1) = Q(0,0);EVecs(0,2) = Q(0,2);
      EVecs(1,0) = Q(1,1);EVecs(1,1) = Q(1,0);EVecs(1,2) = Q(1,2);
      EVecs(2,0) = Q(2,1);EVecs(2,1) = Q(2,0);EVecs(2,2) = Q(2,2);
      EVals(0) = D(1);
      EVals(1) = D(0);
      EVals(2) = D(2);
    } else if (fabs(D(1)) > fabs(D(2))) {
      EVecs(0,0) = Q(0,1);EVecs(0,1) = Q(0,2);EVecs(0,2) = Q(0,0);
      EVecs(1,0) = Q(1,1);EVecs(1,1) = Q(1,2);EVecs(1,2) = Q(1,0);
      EVecs(2,0) = Q(2,1);EVecs(2,1) = Q(2,2);EVecs(2,2) = Q(2,0);
      EVals(0) = D(1);
      EVals(1) = D(2);
      EVals(2) = D(0);
    } else {
      EVecs(0,0) = Q(0,2);EVecs(0,1) = Q(0,1);EVecs(0,2) = Q(0,0);
      EVecs(1,0) = Q(1,2);EVecs(1,1) = Q(1,1);EVecs(1,2) = Q(1,0);
      EVecs(2,0) = Q(2,2);EVecs(2,1) = Q(2,1);EVecs(2,2) = Q(2,0);
      EVals(0) = D(2);
      EVals(1) = D(1);
      EVals(2) = D(0);
    }
  }
}
"""


def metric_from_hessian(d):
    """
    Modify the eigenvalues of a Hessian matrix so
    that it is positive-definite.

    :arg d: spatial dimension
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

void metric_from_hessian(double A_[%d], const double * B_) {

  // Map inputs and outputs onto Eigen objects
  Map<Matrix<double, %d, %d, RowMajor> > A((double *)A_);
  Map<Matrix<double, %d, %d, RowMajor> > B((double *)B_);

  // Compute mean diagonal and set values appropriately
  double mean_diag;
  int i,j;
  for (i=0; i<%d-1; i++) {
    for (j=i+1; i<%d; i++) {
      mean_diag = 0.5*(B(i,j) + B(j,i));
      B(i,j) = mean_diag;
      B(j,i) = mean_diag;
    }
  }

  // Solve eigenvalue problem
  SelfAdjointEigenSolver<Matrix<double, %d, %d, RowMajor>> eigensolver(B);
  Matrix<double, %d, %d, RowMajor> Q = eigensolver.eigenvectors();
  Vector%dd D = eigensolver.eigenvalues();

  // Take modulus of eigenvalues
  for (i=0; i<%d; i++) D(i) = fmax(1e-10, abs(D(i)));

  // Build metric from eigendecomposition
  A += Q * D.asDiagonal() * Q.transpose();
}
""" % (d*d, d, d, d, d, d, d, d, d, d, d, d, d)


def set_eigendecomposition(d):
    """
    Construct a metric from eigenvectors and eigenvalues as an
    orthogonal eigendecomposition.

    :arg d: spatial dimension
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

void set_eigendecomposition(double M_[%d], const double * EVecs_, const double * EVals_) {

  // Map inputs and outputs onto Eigen objects
  Map<Matrix<double, %d, %d, RowMajor> > M((double *)M_);
  Map<Matrix<double, %d, %d, RowMajor> > EVecs((double *)EVecs_);
  Map<Vector%dd> EVals((double *)EVals_);

  // Compute metric from eigendecomposition
  M = EVecs * EVals.asDiagonal() * EVecs.transpose();
}
""" % (d*d, d, d, d, d, d)
