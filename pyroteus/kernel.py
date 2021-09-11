"""
Functions which generate C kernels for dense numerical linear algebra.
"""
from firedrake import op2
import os

try:
    from firedrake.slate.slac.compiler import PETSC_ARCH
except ImportError:
    PETSC_ARCH = os.path.join(os.environ.get('PETSC_DIR'), os.environ.get('PETSC_ARCH'))
include_dir = ["%s/include/eigen3" % PETSC_ARCH]


def eigen_kernel(kernel, *args, **kwargs):
    """
    Helper function to easily pass Eigen kernels
    to Firedrake via PyOP2.

    :arg kernel: a string containing C code which
        is to be formatted.
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
    Extract eigenvectors/eigenvalues from a
    metric field.

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
    Extract eigenvectors/eigenvalues from a
    metric field, with eigenvalues
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
      B(i,j) = 0.5*(B(i,j) + B(j,i));
      B(j,i) = B(i,j);
    }
  }

  // Solve eigenvalue problem
  SelfAdjointEigenSolver<Matrix<double, %d, %d, RowMajor>> eigensolver(B);
  Matrix<double, %d, %d, RowMajor> Q = eigensolver.eigenvectors();
  Vector%dd D = eigensolver.eigenvalues();

  // Take modulus of eigenvalues
  for (i=0; i<%d; i++) D(i) = fmin(1.0e+30, fmax(1.0e-30, abs(D(i))));

  // Build metric from eigendecomposition
  A += Q * D.asDiagonal() * Q.transpose();
}
""" % (d*d, d, d, d, d, d, d, d, d, d, d, d, d)


def set_eigendecomposition(d):
    """
    Construct a metric from eigenvectors
    and eigenvalues as an orthogonal
    eigendecomposition.

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


def get_min_angle2d():
    """
    Compute the minimum angle of each cell
    in a 2D triangular mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector2d P1, Vector2d P2)  {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2));
}

void get_min_angle2d(double *MinAngles, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector2d> P1((double *) &Coords[0]);
  Map<Vector2d> P2((double *) &Coords[2]);
  Map<Vector2d> P3((double *) &Coords[4]);

  // Compute edge vectors and distances
  Vector2d V12 = P2 - P1;
  Vector2d V23 = P3 - P2;
  Vector2d V13 = P3 - P1;
  double d12 = distance(P1, P2);
  double d23 = distance(P2, P3);
  double d13 = distance(P1, P3);

  // Compute angles from cosine formula
  double a1 = acos (V12.dot(V13) / (d12 * d13));
  double a2 = acos (-V12.dot(V23) / (d12 * d23));
  double a3 = acos (V23.dot(V13) / (d23 * d13));
  double aMin = std::min(a1, a2);
  MinAngles[0] = std::min(aMin, a3);
}
"""


def get_min_angle3d():
    """
    Compute the minimum angle of each cell
    in a 3D tetrahedral mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector3d P1, Vector3d P2) {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2) + pow(P1[2] - P2[2], 2));
}

void get_min_angle3d(double *MinAngles, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector3d> P1((double *) &Coords[0]);
  Map<Vector3d> P2((double *) &Coords[3]);
  Map<Vector3d> P3((double *) &Coords[6]);
  Map<Vector3d> P4((double *) &Coords[9]);

  // Compute edge vectors and distances
  Vector3d V12 = P2 - P1;
  Vector3d V13 = P3 - P1;
  Vector3d V14 = P4 - P1;
  Vector3d V23 = P3 - P2;
  Vector3d V24 = P4 - P2;
  Vector3d V34 = P4 - P3;

  double d12 = distance(P1, P2);
  double d13 = distance(P1, P3);
  double d14 = distance(P1, P4);
  double d23 = distance(P2, P3);
  double d24 = distance(P2, P4);
  double d34 = distance(P3, P4);

  double angles[12];
  // Compute angles from cosine formula
  angles[0] = acos(V13.dot(V14) / (d13 * d14));
  angles[1] = acos(V12.dot(V14) / (d12 * d14));
  angles[2] = acos(V13.dot(V12) / (d13 * d12));
  angles[3] = acos(V23.dot(V24) / (d23 * d24));
  angles[4] = acos(-V12.dot(V24) / (d12 * d24));
  angles[5] = acos(-V12.dot(V23) / (d12 * d23));
  angles[6] = acos(-V23.dot(V34) / (d23 * d34));
  angles[7] = acos(-V13.dot(V34) / (d13 * d34));
  angles[8] = acos(V13.dot(V23) / (d13 * d23));
  angles[9] = acos(V24.dot(V34) / (d24 * d34));
  angles[10] = acos(V14.dot(V34) / (d14 * d34));
  angles[11] = acos(V14.dot(V24) / (d14 * d24));

  double aMin = 3.14;
  for (int i = 0; i < 12; i++) {
    aMin = std::min(aMin, angles[i]);
  }

  MinAngles[0] = aMin;
}
"""


def get_area2d():
    """
    Compute the area of each cell
    in a 2D triangular mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector2d P1, Vector2d P2)  {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2));
}

void get_area2d(double *Areas, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector2d> P1((double *) &Coords[0]);
  Map<Vector2d> P2((double *) &Coords[2]);
  Map<Vector2d> P3((double *) &Coords[4]);

  // Compute edge lengths
  double d12 = distance(P1, P2);
  double d23 = distance(P2, P3);
  double d13 = distance(P1, P3);
  double s = (d12 + d23 + d13) / 2;
  // Compute area using Heron's formula
  Areas[0] = sqrt(s * (s - d12) * (s - d23) * (s - d13));
}
"""


def get_volume3d():
    """
    Compute the volume of each cell in
    a 3D tetrahedral mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector3d P1, Vector3d P2) {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2) + pow(P1[2] - P2[2], 2));
}

void get_volume3d(double *Volumes, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector3d> P1((double *) &Coords[0]);
  Map<Vector3d> P2((double *) &Coords[3]);
  Map<Vector3d> P3((double *) &Coords[6]);
  Map<Vector3d> P4((double *) &Coords[9]);

  // Compute edge vectors
  Vector3d V12 = P2 - P1;
  Vector3d V13 = P3 - P1;
  Vector3d V14 = P4 - P1;
  Vector3d V23 = P3 - P2;
  Vector3d V24 = P4 - P2;
  Vector3d V34 = P4 - P3;

  Matrix3d volumeMatrix;
  for (int i = 0; i < 3; i++) {
    volumeMatrix(0, i) = V12[i];
    volumeMatrix(1, i) = V13[i];
    volumeMatrix(2, i) = V14[i];
  }
  Volumes[0] = std::abs(volumeMatrix.determinant() / 6);
}
"""


def get_eskew2d():
    """
    Compute the area of each cell
    in a 2D triangular mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector2d P1, Vector2d P2)  {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2));
}

void get_eskew2d(double *ESkews, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector2d> P1((double *) &Coords[0]);
  Map<Vector2d> P2((double *) &Coords[2]);
  Map<Vector2d> P3((double *) &Coords[4]);

  // Compute edge vectors and distances
  Vector2d V12 = P2 - P1;
  Vector2d V23 = P3 - P2;
  Vector2d V13 = P3 - P1;
  double d12 = distance(P1, P2);
  double d23 = distance(P2, P3);
  double d13 = distance(P1, P3);

  // Compute angles from cosine formula
  double a1 = acos (V12.dot(V13) / (d12 * d13));
  double a2 = acos (-V12.dot(V23) / (d12 * d23));
  double a3 = acos (V23.dot(V13) / (d23 * d13));
  double pi = 3.14159265358979323846;

  // Plug values into equiangle skew formula as per:
  // http://www.lcad.icmc.usp.br/~buscaglia/teaching/mfcpos2013/bakker_07-mesh.pdf
  double aMin = std::min(a1, a2);
  aMin = std::min(aMin, a3);
  double aMax = std::max(a1, a2);
  aMax = std::max(aMax, a3);
  double aIdeal = pi / 3;
  ESkews[0] = std::max((aMax - aIdeal / (pi - aIdeal)), (aIdeal - aMin) / aIdeal);
}
"""


def get_eskew3d():
    """
    Compute the equiangle skew of each
    cell in a 3D tetrahedral mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector3d P1, Vector3d P2) {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2) + pow(P1[2] - P2[2], 2));
}

void get_eskew3d(double *ESkews, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector3d> P1((double *) &Coords[0]);
  Map<Vector3d> P2((double *) &Coords[3]);
  Map<Vector3d> P3((double *) &Coords[6]);
  Map<Vector3d> P4((double *) &Coords[9]);

  // Compute edge vectors and distances
  Vector3d V12 = P2 - P1;
  Vector3d V13 = P3 - P1;
  Vector3d V14 = P4 - P1;
  Vector3d V23 = P3 - P2;
  Vector3d V24 = P4 - P2;
  Vector3d V34 = P4 - P3;

  double d12 = distance(P1, P2);
  double d13 = distance(P1, P3);
  double d14 = distance(P1, P4);
  double d23 = distance(P2, P3);
  double d24 = distance(P2, P4);
  double d34 = distance(P3, P4);

  double angles[12];
  // Compute angles from cosine formula
  angles[0] = acos(V13.dot(V14) / (d13 * d14));
  angles[1] = acos(V12.dot(V14) / (d12 * d14));
  angles[2] = acos(V13.dot(V12) / (d13 * d12));
  angles[3] = acos(V23.dot(V24) / (d23 * d24));
  angles[4] = acos(-V12.dot(V24) / (d12 * d24));
  angles[5] = acos(-V12.dot(V23) / (d12 * d23));
  angles[6] = acos(-V23.dot(V34) / (d23 * d34));
  angles[7] = acos(-V13.dot(V34) / (d13 * d34));
  angles[8] = acos(-V13.dot(-V23) / (d13 * d23));
  angles[9] = acos(-V24.dot(-V34) / (d24 * d34));
  angles[10] = acos(-V14.dot(-V34) / (d14 * d34));
  angles[11] = acos(-V14.dot(-V24) / (d14 * d24));
  double pi = 3.14159265358979323846;

  double aMin = pi;
  double aMax = 0.0;
  for (int i = 0; i < 12; i++) {
    aMin = std::min(aMin, angles[i]);
    aMax = std::max(aMax, angles[i]);
  }
  double aIdeal = pi / 3;
  ESkews[0] = std::max((aMax - aIdeal) / (pi - aIdeal), (aIdeal - aMin) / aIdeal);
}
"""


def get_aspect_ratio2d():
    """
    Compute the area of each cell
    in a 2D triangular mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector2d P1, Vector2d P2)  {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2));
}

void get_aspect_ratio2d(double *AspectRatios, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector2d> P1((double *) &Coords[0]);
  Map<Vector2d> P2((double *) &Coords[2]);
  Map<Vector2d> P3((double *) &Coords[4]);

  // Compute edge vectors and distances
  Vector2d V12 = P2 - P1;
  Vector2d V23 = P3 - P2;
  Vector2d V13 = P3 - P1;
  double d12 = distance(P1, P2);
  double d23 = distance(P2, P3);
  double d13 = distance(P1, P3);
  double s = (d12 + d23 + d13) / 2;

  // Calculate aspect ratio based on the circumradius and inradius as per:
  // https://stackoverflow.com/questions/10289752/aspect-ratio-of-a-triangle-of-a-meshed-surface
  AspectRatios[0] = (d12 * d23 * d13) / (8 * (s - d12) * (s - d23) * (s - d13));
}
"""


def get_aspect_ratio3d():
    """
    Compute the aspect ratio of each cell
    in a 3D tetrahedral mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector3d P1, Vector3d P2) {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2) + pow(P1[2] - P2[2], 2));
}

void get_aspect_ratio3d(double *AspectRatios, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector3d> P1((double *) &Coords[0]);
  Map<Vector3d> P2((double *) &Coords[3]);
  Map<Vector3d> P3((double *) &Coords[6]);
  Map<Vector3d> P4((double *) &Coords[9]);

  // Compute edge vectors and distances
  Vector3d V12 = P2 - P1;
  Vector3d V13 = P3 - P1;
  Vector3d V14 = P4 - P1;
  Vector3d V23 = P3 - P2;
  Vector3d V24 = P4 - P2;
  Vector3d V34 = P4 - P3;

  double d12 = distance(P1, P2);
  double d13 = distance(P1, P3);
  double d14 = distance(P1, P4);
  double d23 = distance(P2, P3);
  double d24 = distance(P2, P4);
  double d34 = distance(P3, P4);

  Matrix3d volumeMatrix;
  for (int i = 0; i < 3; i++) {
    volumeMatrix(0, i) = V12[i];
    volumeMatrix(1, i) = V13[i];
    volumeMatrix(2, i) = V14[i];
  }
  double volume = std::abs(volumeMatrix.determinant() / 6);

  // Reference for inradius and circumradius calculations on the tetrahedron
  // https://en.wikipedia.org/wiki/Tetrahedron#Inradius
  double cir_radius = sqrt((d12 * d34 + d13 * d24 + d14 * d23) *
                           (d12 * d34 + d13 * d24 - d14 * d23) *
                           (d12 * d34 - d13 * d24 + d14 * d23) *
                           (-d12 * d34 + d13 * d24 + d14 * d23)) / (24 * volume);

  double s1 = (d23 + d24 + d34) / 2;
  double s2 = (d13 + d14 + d34) / 2;
  double s3 = (d12 + d14 + d24) / 2;
  double s4 = (d12 + d13 + d23) / 2;
  double f_area1 = sqrt(s1 * (s1 - d23) * (s1 - d24) * (s1 - d34));
  double f_area2 = sqrt(s2 * (s2 - d13) * (s2 - d14) * (s2 - d34));
  double f_area3 = sqrt(s3 * (s3 - d12) * (s3 - d14) * (s3 - d24));
  double f_area4 = sqrt(s4 * (s4 - d12) * (s4 - d13) * (s4 - d23));
  double in_radius = 3 * volume / (f_area1 + f_area2 + f_area3 + f_area4);

  AspectRatios[0] = cir_radius / (3 * in_radius);
}
"""


def get_scaled_jacobian2d():
    """
    Compute the scaled jacobian of each
    cell in a 2D triangular mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector2d P1, Vector2d P2)  {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2));
}

void get_scaled_jacobian2d(double *SJacobians, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector2d> P1((double *) &Coords[0]);
  Map<Vector2d> P2((double *) &Coords[2]);
  Map<Vector2d> P3((double *) &Coords[4]);

  // Compute edge vectors and distances
  Vector2d V12 = P2 - P1;
  Vector2d V23 = P3 - P2;
  Vector2d V13 = P3 - P1;
  double d12 = distance(P1, P2);
  double d23 = distance(P2, P3);
  double d13 = distance(P1, P3);

  // Definition and calculation reference:
  // https://cubit.sandia.gov/15.5/help_manual/WebHelp/mesh_generation/mesh_quality_assessment/triangular_metrics.htm
  // https://www.osti.gov/biblio/5009
  double sj1 = std::abs(V12[0] * V13[1] - V13[0]*V12[1]) / (d12 * d13);
  double sj2 = std::abs(V12[0] * V23[1] - V23[0]*V12[1]) / (d12 * d23);
  double sj3 = std::abs(V23[0] * V13[1] - V13[0]*V23[1]) / (d13 * d23);
  SJacobians[0] = std::min(sj1, sj2);
  SJacobians[0] = std::min(sj3, SJacobians[0]);
}
"""


def get_scaled_jacobian3d():
    """
    Compute the scaled jacobian of each cell
    in a 3D tetrahedral mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector3d P1, Vector3d P2) {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2) + pow(P1[2] - P2[2], 2));
}

void get_scaled_jacobian3d(double *SJacobians, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector3d> P1((double *) &Coords[0]);
  Map<Vector3d> P2((double *) &Coords[3]);
  Map<Vector3d> P3((double *) &Coords[6]);
  Map<Vector3d> P4((double *) &Coords[9]);

  // Compute edge vectors and distances
  Vector3d V12 = P2 - P1;
  Vector3d V13 = P3 - P1;
  Vector3d V14 = P4 - P1;
  Vector3d V23 = P3 - P2;
  Vector3d V24 = P4 - P2;
  Vector3d V34 = P4 - P3;

  double d12 = distance(P1, P2);
  double d13 = distance(P1, P3);
  double d14 = distance(P1, P4);
  double d23 = distance(P2, P3);
  double d24 = distance(P2, P4);
  double d34 = distance(P3, P4);

  Matrix3d M1, M2, M3, M4;
  double sj[4];
  for (int i = 0; i < 3; i++) {
    M1(0, i) = V12[i];
    M1(1, i) = V13[i];
    M1(2, i) = V14[i];

    M2(0, i) = -V12[i];
    M2(1, i) = V23[i];
    M2(2, i) = V24[i];

    M3(0, i) = -V13[i];
    M3(1, i) = -V23[i];
    M3(2, i) = V34[i];

    M4(0, i) = -V14[i];
    M4(1, i) = -V24[i];
    M4(2, i) = -V34[i];
  }
  sj[0] = std::abs(M1.determinant()) / (d12 * d13 * d14);
  sj[1] = std::abs(M2.determinant()) / (d12 * d23 * d24);
  sj[2] = std::abs(M3.determinant()) / (d13 * d23 * d34);
  sj[3] = std::abs(M4.determinant()) / (d14 * d24 * d34);

  SJacobians[0] = std::min(sj[0], sj[1]);
  SJacobians[0] = std::min(SJacobians[0], sj[2]);
  SJacobians[0] = std::min(SJacobians[0], sj[3]);
}
"""


def get_skewness2d():
    """
    Compute the skewness of each cell
    in a 2D triangular mesh.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector2d P1, Vector2d P2)  {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2));
}

void get_skewness2d(double *Skews, double *Coords) {
  // Map coordinates onto Eigen objects
  Map<Vector2d> P1((double *) &Coords[0]);
  Map<Vector2d> P2((double *) &Coords[2]);
  Map<Vector2d> P3((double *) &Coords[4]);

  // Calculating in accordance with:
  // https://www.engmorph.com/skewness-finite-elemnt
  Vector2d midPoint1 = P2 + (P3 - P2) / 2;
  Vector2d midPoint2 = P3 + (P1 - P3) / 2;
  Vector2d midPoint3 = P1 + (P2 - P1) / 2;
  double pi = 3.14159265358979323846;

  Vector2d lineNormal1 = midPoint1 - P1;
  Vector2d lineOrth1 = midPoint3 - midPoint2;
  double t1 = acos (lineNormal1.dot(lineOrth1) / (distance(P1, midPoint1) * distance(midPoint2, midPoint3)));
  double t2 = pi - t1;
  double tMin = std::min(t1, t2);

  Vector2d lineNormal2 = midPoint2 - P2;
  Vector2d lineOrth2 = midPoint1 - midPoint3;
  double t3 = acos (lineNormal2.dot(lineOrth2) / (distance(P2, midPoint2) * distance(midPoint1, midPoint3)));
  double t4 = std::min(t3, pi - t3);
  tMin = std::min(tMin, t4);

  Vector2d lineNormal3 = midPoint3 - P3;
  Vector2d lineOrth3 = midPoint2 - midPoint1;
  double t5 = acos (lineNormal3.dot(lineOrth3) / (distance(P3, midPoint3) * distance(midPoint1, midPoint2)));
  double t6 = std::min(t3, pi - t5);
  tMin = std::min(tMin, t6);

  Skews[0] = pi/2 - tMin;
}
"""


def get_metric2d():
    """
    Given a matrix M, a linear function in 2 dimensions,
    this function outputs the value of the Quality metric Q_M
    based on the transformation encoded in M.
    The suggested use case is to create the matrix M,
    interpolate to all vertices of the mesh and pass it with
    its corresponding cell_node_map() to this kernel.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector2d P1, Vector2d P2)  {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2));
}

void get_metric2d(double *Metrics, const double *T_, double *Coords) {
    // Map coordinates onto Eigen objects
    Map<Vector2d> P1((double *) &Coords[0]);
    Map<Vector2d> P2((double *) &Coords[2]);
    Map<Vector2d> P3((double *) &Coords[4]);

    // Compute edge vectors and distances
    Vector2d V12 = P2 - P1;
    Vector2d V23 = P3 - P2;
    Vector2d V13 = P3 - P1;
    double d12 = distance(P1, P2);
    double d23 = distance(P2, P3);
    double d13 = distance(P1, P3);
    double s = (d12 + d23 + d13) / 2;
    double area = sqrt(s * (s-d12) * (s-d13) * (s-d23));

    // Map tensor  function as 2x2 Matrices
    Map<Matrix2d> M1((double *) &T_[0]);
    Map<Matrix2d> M2((double *) &T_[4]);
    Map<Matrix2d> M3((double *) &T_[8]);

    // Compute M(x, y) at centroid x_c to get area_M
    Matrix2d Mxc = (M1 + M2 + M3) / 3;
    double areaM = area * sqrt(Mxc.determinant());

    // Compute (squared) edge lengths in metric space
    double L1 = V23.dot(((M2 + M3)/2) * V23);
    double L2 = V13.dot(((M1 + M3)/2) * V13);
    double L3 = V12.dot(((M1 + M2)/2) * V12);

    // Calculated using Q_M formula in 2D, reference:
    // https://epubs.siam.org/doi/10.1137/090754078
    Metrics[0] = sqrt(3) * (L1 + L2 + L3) / (2 * areaM);
}
"""


def get_metric3d():
    """
    Given a matrix M, a linear function in 3 dimensions,
    this function outputs the value of the Quality metric Q_M
    based on the transformation encoded in M.
    The suggested use case is to create the matrix M,
    interpolate to all vertices of the mesh and pass it with
    its corresponding cell_node_map() to this kernel.
    """
    return """
#include <Eigen/Dense>

using namespace Eigen;

double distance(Vector3d P1, Vector3d P2) {
  return sqrt(pow(P1[0] - P2[0], 2) + pow(P1[1] - P2[1], 2) + pow(P1[2] - P2[2], 2));
}

void get_metric3d(double *Metrics, const double *T_, double *Coords) {
  // Map vertices as vectors
  Map<Vector3d> P1((double *) &Coords[0]);
  Map<Vector3d> P2((double *) &Coords[3]);
  Map<Vector3d> P3((double *) &Coords[6]);
  Map<Vector3d> P4((double *) &Coords[9]);

  // Precompute some vectors, and distances
  Vector3d V12 = P2 - P1;
  Vector3d V13 = P3 - P1;
  Vector3d V14 = P4 - P1;
  Vector3d V23 = P3 - P2;
  Vector3d V24 = P4 - P2;
  Vector3d V34 = P4 - P3;

  double d12 = distance(P1, P2);
  double d13 = distance(P1, P3);
  double d14 = distance(P1, P4);
  double d23 = distance(P2, P3);
  double d24 = distance(P2, P4);
  double d34 = distance(P3, P4);

  Matrix3d volMatrix;
  for (int i = 0; i < 3; i++) {
    volMatrix(0, i) = V12[i];
    volMatrix(1, i) = V13[i];
    volMatrix(2, i) = V14[i];
  }

  double volume = std::abs(volMatrix.determinant()) / 6;

  // Map tensor as 3x3 Matrices
  Map<Matrix3d> M1((double *) &T_[0]);
  Map<Matrix3d> M2((double *) &T_[9]);
  Map<Matrix3d> M3((double *) &T_[18]);
  Map<Matrix3d> M4((double *) &T_[27]);

  // Compute M(x, y) at centroid x_c to get area_M
  Matrix3d Mxc = (M1 + M2 + M3 + M4) / 3;
  double volumeM = volume * sqrt(Mxc.determinant());

  // Compute (squared) edge lengths in metric
  double L1 = V12.dot(((M1 + M2)/2) * V12);
  double L2 = V13.dot(((M1 + M3)/2) * V13);
  double L3 = V14.dot(((M1 + M4)/2) * V14);
  double L4 = V23.dot(((M2 + M3)/2) * V23);
  double L5 = V24.dot(((M2 + M4)/2) * V24);
  double L6 = V34.dot(((M3 + M4)/2) * V34);

  Metrics[0] = sqrt(3) * (L1 + L2 + L3 + L4 + L5 + L6) / (216 * volumeM);
}
"""
