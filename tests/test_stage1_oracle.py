import numpy as np
import pytest
from scripts.prepare_stage1_oracle import load_raster, normalize_gt, voxelize
from wt.textured_mesh.canon import CanonicalTransform

@pytest.fixture(scope="module")
def raster():
    return load_raster()

def test_axes_and_sort(raster):
    cell=np.array([22,8,19])
    v=(cell+np.array([[.2,.3,.4],[.8,.3,.4],[.2,.7,.4]]))/32-.5
    camera=v[:,[0,2,1]].copy()
    camera[:,1]*=-1
    xyz,clipped=voxelize(raster,camera,np.array([[0,1,2],[2,1,0]]),CanonicalTransform([0,0,0],1))
    np.testing.assert_array_equal(xyz,[cell])
    assert clipped==0

def test_crossing_and_closed_contact(raster):
    # Plane lies on an internal grid face; half of the rectangular surface is outside.
    v=np.array([[.25,.1,0],[.75,.1,0],[.75,.2,0],[.25,.2,0]])
    xyz,clipped=voxelize(raster,v,np.array([[0,1,2],[0,2,3]]),CanonicalTransform([0,0,0],1,"identity"))
    assert clipped==pytest.approx(.5) and set(xyz[:,2])=={15,16}
    np.testing.assert_array_equal(xyz,np.unique(xyz,axis=0))
    assert xyz[:,0].max()==31 and xyz[:,0].min()==23

def test_area_centroid_and_extent():
    v=np.array([[0,0,0],[6,0,0],[0,3,0],[3,1.5,0]],float)
    tf=normalize_gt(v,np.array([[0,1,3],[0,3,2]]),"identity")
    np.testing.assert_allclose(tf.centroid,[2,1,0])
    assert abs(tf.apply(v)).max()==pytest.approx(.45)
