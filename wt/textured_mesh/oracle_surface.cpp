// Rasterize a triangle soup against the closed cells of the canonical 32-grid.
// Clipping carries polygons across cell boundaries, including zero-area contacts.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace {
using Vec = std::array<double, 3>;
struct Poly { std::array<Vec, 24> p{}; int n=0; };
Poly clip(const Poly &src, int axis, double bound, int sign) {
    Poly out;
    for (int i=0; i<src.n; ++i) {
        const auto &a=src.p[i], &b=src.p[(i+1)%src.n];
        double da=sign*(a[axis]-bound), db=sign*(b[axis]-bound);
        if (da>=0) out.p[out.n++]=a;
        if ((da>0 && db<0) || (da<0 && db>0)) {
            Vec q;
            for(int k=0;k<3;++k) q[k]=a[k]+da/(da-db)*(b[k]-a[k]);
            q[axis]=bound;
            out.p[out.n++]=q;
        }
    }
    return out;
}
double area(const Poly &s) {
    double total=0;
    for(int i=1;i+1<s.n;++i) {
        Vec a,b,c;
        for(int k=0;k<3;++k) {a[k]=s.p[i][k]-s.p[0][k]; b[k]=s.p[i+1][k]-s.p[0][k];}
        for(int k=0;k<3;++k) c[k]=a[(k+1)%3]*b[(k+2)%3]-a[(k+2)%3]*b[(k+1)%3];
        total+=0.5*std::hypot(c[0],c[1],c[2]);
    }
    return total;
}
void cells(const Poly &s,int axis,int prefix,uint8_t *mask) {
    double lo=s.p[0][axis],hi=lo;
    for(int i=1;i<s.n;++i){lo=std::min(lo,s.p[i][axis]);hi=std::max(hi,s.p[i][axis]);}
    int first=std::max(0,int(std::ceil(lo))-1), last=std::min(31,int(std::floor(hi)));
    for(int j=first;j<=last;++j) {
        int id=32*prefix+j;
        if(axis==2){mask[id]=1;continue;} // A convex polygon projects to a continuous interval.
        Poly slab=s;
        if(lo<j) slab=clip(slab,axis,j,1);
        if(hi>j+1) slab=clip(slab,axis,j+1,-1);
        if(slab.n) cells(slab,axis+1,id,mask);
    }
}
}
extern "C" void raster(const double *tri,int64_t n,uint8_t *mask,double *areas) {
    for(int64_t t=0;t<n;++t){
        Poly s; s.n=3;
        for(int i=0;i<3;++i) for(int k=0;k<3;++k) s.p[i][k]=32*(tri[9*t+3*i+k]+0.5);
        double a=area(s); if(a==0) continue;
        areas[0]+=a;
        for(int k=0;k<3 && s.n;++k) {
            bool lower=false,upper=false;
            for(int i=0;i<s.n;++i){lower|=s.p[i][k]<0;upper|=s.p[i][k]>32;}
            if(lower) s=clip(s,k,0,1);
            if(upper) s=clip(s,k,32,-1);
        }
        if(s.n){areas[1]+=area(s);cells(s,0,0,mask);}
    }
}
