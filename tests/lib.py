from pytest import mark
from pytest_mock import MockFixture

from OpenPGP import lib


@mark.unit
def test_greet(mocker: MockFixture):
    prt = mocker.patch.object(lib, 'print')
    assert lib.greet('Alice') is None
    prt.assert_called_once_with('Hello, Alice!')
