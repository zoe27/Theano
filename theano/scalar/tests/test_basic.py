"""
These routines are not well-tested. They are also old.
OB says that it is not important to test them well because Scalar Ops
are rarely used by themselves, instead they are the basis for Tensor Ops
(which should be checked thoroughly). Moreover, Scalar will be changed
to use numpy's scalar routines.
If you do want to rewrite these tests, bear in mind:
  * You don't need to use Composite.
  * FunctionGraph and DualLinker are old, use compile.function instead.
"""

import unittest

import theano
from theano.gof import FunctionGraph
from theano import gof
from theano.tests import unittest_tools as utt

from theano.scalar.basic import (floats, float32, float64,
                                 ints, int8, int32, complex64,
                                 ComplexError, IntDiv, TrueDiv,
                                 Composite, add, div_proxy, clip,
                                 and_, eq, neq, invert, mul)
import numpy

def inputs():
    return floats('xyz')


class test_ScalarOps(unittest.TestCase):

    def test_straightforward(self):
        x, y, z = inputs()
        e = mul(add(x, y), div_proxy(x, y))
        g = FunctionGraph([x, y], [e])
        fn = gof.DualLinker().accept(g).make_function()
        assert fn(1.0, 2.0) == 1.5

    #This test is moved to theano.tensor.tests.test_basic.py:test_mod
    #We move it their as under ubuntu the c_extract call of theano.scalar
    #call PyInt_check and it fail under some os. If work in other case.
    #As we use theano.scalar normally, but we use theano.tensor.scalar
    #that is not important. Also this make the theano fct fail at call time
    #so this is not a silent bug.
    # --> This is why it is purposedly named 'tes_mod' instead of 'test_mod'.
    def tes_mod(self):
        """
        We add this test as not all language and C implementation give the same
        signe to the result. This check that the c_code of `Mod` is implemented
        as Python. That is what we want.
        """
        x, y = ints('xy')
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x%y])).make_function()
        for a,b in ((0,1), (1,1), (0,-1), (1,-1), (-1,-1),
                    (1,2), (-1,2), (1,-2), (-1,-2),
                    (5,3), (-5,3), (5,-3), (-5,-3)
                    ):
            self.assertTrue(fn(a,b) == a%b, (a,))


    def test_clip_grad(self):
        #This is testing for the issue #633
        x, y = floats('xy')
        a = theano.tensor.clip(x, y, x)
        g = theano.gradient.grad(a, x)
        fn = gof.DualLinker().accept(FunctionGraph([x, y], [g])).make_function()

        # Test the other way around as well
        a2 = theano.tensor.clip(x, x, y)
        g2 = theano.gradient.grad(a2, x)
        fn2 = gof.DualLinker().accept(FunctionGraph([x, y], [g2])).make_function()

        # Test for the equal case too .
        a3 = theano.tensor.clip(x, x, x)
        g3 = theano.gradient.grad(a3, x)
        fn3 = gof.DualLinker().accept(FunctionGraph([x], [g3])).make_function()

        rng = numpy.random.RandomState(utt.fetch_seed())

        ntests = 50
        for i in xrange(ntests):
            xval = rng.rand(1)
            #To ensure that the min < x .
            yval_mn = rng.rand(1) - 1.0

            #To ensure that the max > x.
            yval_mx = rng.rand(1) + 1.0

            aval = fn(xval, yval_mn)
            aval2 = fn2(xval, yval_mx)
            aval3 = fn3(xval)
            self.assertTrue(aval == 1.)
            self.assertTrue(aval2 == 1.)
            self.assertTrue(aval3 == 1.)


class test_composite(unittest.TestCase):

    def test_straightforward(self):
        x, y, z = inputs()
        e = mul(add(x, y), div_proxy(x, y))
        C = Composite([x, y], [e])
        c = C.make_node(x, y)
        # print c.c_code(['x', 'y'], ['z'], dict(id = 0))
        g = FunctionGraph([x, y], [c.out])
        fn = gof.DualLinker().accept(g).make_function()
        assert fn(1.0, 2.0) == 1.5

    def test_flatten(self):
        #Test that we flatten multiple Composite.
        x, y, z = inputs()
        C = Composite([x, y], [x + y])
        CC = Composite([x, y], [C(x * y, y)])
        assert not isinstance(CC.outputs[0].owner.op, Composite)

        # Test with multiple outputs
        CC = Composite([x, y, z], [C(x * y, y), C(x * z, y)])
        #We don't flatten that case.
        assert isinstance(CC.outputs[0].owner.op, Composite)

    def test_with_constants(self):
        x, y, z = inputs()
        e = mul(add(70.0, y), div_proxy(x, y))
        C = Composite([x, y], [e])
        c = C.make_node(x, y)
        assert "70.0" in c.op.c_code(c, 'dummy', ['x', 'y'], ['z'], dict(id = 0))
        # print c.c_code(['x', 'y'], ['z'], dict(id = 0))
        g = FunctionGraph([x, y], [c.out])
        fn = gof.DualLinker().accept(g).make_function()
        assert fn(1.0, 2.0) == 36.0

    def test_many_outputs(self):
        x, y, z = inputs()
        e0 = x + y + z
        e1 = x + y * z
        e2 = x / y
        C = Composite([x, y, z], [e0, e1, e2])
        c = C.make_node(x, y, z)
        # print c.c_code(['x', 'y', 'z'], ['out0', 'out1', 'out2'], dict(id = 0))
        g = FunctionGraph([x, y, z], c.outputs)
        fn = gof.DualLinker().accept(g).make_function()
        assert fn(1.0, 2.0, 3.0) == [6.0, 7.0, 0.5]

    def test_make_node_continue_graph(self):
        # This is a test for a bug (now fixed) that disabled the
        # local_gpu_elemwise_0 optimization and printed an
        # optimization warning on the terminal.

        # We test that Composite.make_node accept as inputs Variable
        # some that represent existing computation.

        si0 = theano.scalar.int8()
        si1 = theano.scalar.int8()
        si2 = theano.scalar.float32()
        sout = (si0 * si1) / si2
        sop = theano.scalar.Composite([si0, si1, si2],
                                      [sout])
        si0 = theano.scalar.int8()
        si1 = theano.scalar.int8()
        si2 = theano.scalar.float32()
        si3 = theano.scalar.float32()
        sop.make_node(si0 * si3, si1, si2)


class test_logical(unittest.TestCase):
    def test_gt(self):
        x, y, z = inputs()
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x > y])).make_function()
        for a,b in ((3.,9), (3,0.9), (3,3)):
            self.assertTrue(fn(a,b) == (a>b))

    def test_lt(self):
        x, y, z = inputs()
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x < y])).make_function()
        for a,b in ((3.,9), (3,0.9), (3,3)):
            self.assertTrue(fn(a,b) == (a<b))

    def test_le(self):
        x, y, z = inputs()
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x <= y])).make_function()
        for a,b in ((3.,9), (3,0.9), (3,3)):
            self.assertTrue(fn(a,b) == (a<=b))

    def test_ge(self):
        x, y, z = inputs()
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x >= y])).make_function()
        for a,b in ((3.,9), (3,0.9), (3,3)):
            self.assertTrue(fn(a,b) == (a>=b))

    def test_eq(self):
        x, y, z = inputs()
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [eq(x,y)])).make_function()
        for a,b in ((3.,9), (3,0.9), (3,3)):
            self.assertTrue(fn(a,b) == (a==b))

    def test_neq(self):
        x, y, z = inputs()
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [neq(x,y)])).make_function()
        for a,b in ((3.,9), (3,0.9), (3,3)):
            self.assertTrue(fn(a,b) == (a!=b))


    def test_or(self):
        x, y, z = ints('xyz')
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x|y])).make_function()
        for a,b in ((0,1), (0,0), (1,0), (1,1)):
            self.assertTrue(fn(a,b) == (a|b), (a,b))

    def test_xor(self):
        x, y, z = ints('xyz')
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x^y])).make_function()
        for a,b in ((0,1), (0,0), (1,0), (1,1)):
            self.assertTrue(fn(a,b) == (a ^ b), (a,b))

    def test_and(self):
        x, y, z = ints('xyz')
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [and_(x, y)])).make_function()
        for a,b in ((0,1), (0,0), (1,0), (1,1)):
            self.assertTrue(fn(a,b) == (a & b), (a,b))

        x, y, z = ints('xyz')
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [x & y])).make_function()
        for a,b in ((0,1), (0,0), (1,0), (1,1)):
            self.assertTrue(fn(a,b) == (a & b), (a,b))

    def test_not(self):
        x, y, z = ints('xyz')
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [invert(x)])).make_function()
        for a,b in ((0,1), (0,0), (1,0), (1,1)):
            self.assertTrue(fn(a,b) == ~a, (a,))

        x, y, z = ints('xyz')
        fn = gof.DualLinker().accept(FunctionGraph([x,y], [~x])).make_function()
        for a,b in ((0,1), (0,0), (1,0), (1,1)):
            self.assertTrue(fn(a,b) == ~a, (a,))


class test_complex_mod(unittest.TestCase):
    """Make sure % fails on complex numbers."""

    def test_fail(self):
        x = complex64()
        y = int32()
        try:
            x % y
            assert False
        except ComplexError:
            pass


class test_div(unittest.TestCase):
    def test_0(self):
        a = int8()
        b = int32()
        c = complex64()
        d = float64()
        f = float32()

        #print (a//b).owner.op
        assert isinstance((a//b).owner.op, IntDiv)
        assert isinstance((b//a).owner.op, IntDiv)
        assert isinstance((b/d).owner.op, TrueDiv)
        assert isinstance((b/f).owner.op, TrueDiv)
        assert isinstance((f/a).owner.op, TrueDiv)
        assert isinstance((d/b).owner.op, TrueDiv)
        assert isinstance((d/f).owner.op, TrueDiv)
        assert isinstance((f/c).owner.op, TrueDiv)
        assert isinstance((a/c).owner.op, TrueDiv)

def test_grad_gt():
    x = float32(name = 'x')
    y = float32(name = 'y')
    z = x > y
    g = theano.gradient.grad(z, y)
    assert g.eval({ y : 1. }) == 0.

def test_grad_switch():

    # This is a code snippet from the mailing list
    # It caused an assert to be raised due to the
    # switch op's grad method not handling integer
    # inputs correctly

    x = theano.tensor.matrix()
    c = theano.tensor.matrix()

    s = theano.tensor.switch(c, x, 0)
    l = s.sum()

    theano.gradient.grad(l, x)

# Testing of Composite is done in tensor/tests/test_opt.py
# in test_fusion, TestCompositeCodegen


if __name__ == '__main__':
    unittest.main()
